import json
from threading import Event

import pandas as pd
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.training.train import publish, run_training
from app.training.jobs import TrainingJobs


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'training.db'}")
    with engine.begin() as c:
        for ddl in [
            'CREATE TABLE users (id BIGINT PRIMARY KEY)',
            'CREATE TABLE anime (id BIGINT PRIMARY KEY, anilist_id BIGINT UNIQUE)',
            'CREATE TABLE anime_stats (anime_id BIGINT, in_lists_count INTEGER)',
            'CREATE TABLE anime_genres (anime_id BIGINT, genre_id INTEGER)',
            'CREATE TABLE user_anime (user_id BIGINT, anime_id BIGINT, status TEXT, score INTEGER, updated_at TEXT)',
            'CREATE TABLE recommendations (user_id BIGINT, anime_id BIGINT CHECK(anime_id>0), relevance REAL, model_version TEXT, generated_at TIMESTAMP, PRIMARY KEY(user_id, anime_id))',
        ]:
            c.execute(text(ddl))
        c.execute(text('INSERT INTO users VALUES (:u)'), [{'u':u} for u in range(1,8)])
        c.execute(text('INSERT INTO anime VALUES (:i,:a)'), [{'i':i,'a':i+1000} for i in range(1,61)])
        c.execute(text('INSERT INTO anime_stats VALUES (:i,:p)'), [{'i':i,'p':i} for i in range(1,61)])
        c.execute(text('INSERT INTO anime_genres VALUES (:i,1)'), [{'i':i} for i in range(1,61)])
        c.execute(text('INSERT INTO user_anime VALUES (:u,:i,:s,8,:d)'), [
            {'u':u,'i':i,'s':'completed','d':pd.Timestamp.now(tz='UTC').isoformat()}
            for u in range(1,6) for i in range(1,7)
        ] + [{'u':6,'i':1,'s':'dropped','d':pd.Timestamp.now(tz='UTC').isoformat()}])
    yield engine
    engine.dispose()


def config(tmp_path, **kwargs):
    return Settings(_env_file=None, ml_artifact_dir=tmp_path/'artifacts', **kwargs)


def test_training_maps_external_ids_and_only_publishes_site_users(database, tmp_path):
    external = tmp_path/'external'
    external.mkdir()
    pd.DataFrame([dict(user_id=u, anime_id=i+1000, status='COMPLETED', score=8,
                       updated_at=1700000000) for u in range(1,6) for i in range(1,9)]).to_parquet(external/'part.parquet')
    result = run_training(database, config(tmp_path, ml_anilist_data_dir=external))
    assert result['als_trained'] and result['published']
    assert result['routes'] == {'als':5,'genre28':1,'all_time':1}
    assert result['matched_external_rows'] == 40
    with database.connect() as c:
        rows = c.execute(text('SELECT * FROM recommendations')).mappings().all()
        assert len(rows)==350
        assert {r['user_id'] for r in rows} == set(range(1,8))
        assert all(1 <= r['anime_id'] <= 60 for r in rows)
        assert not c.execute(text('SELECT 1 FROM recommendations r JOIN user_anime u '
            'ON r.user_id=u.user_id AND r.anime_id=u.anime_id')).first()
    summary = json.loads((tmp_path/'artifacts'/result['model_version']/'summary.json').read_text())
    assert summary['published']
    from app.recsys.als import ALSRecommender
    als=ALSRecommender.load(tmp_path/'artifacts'/result['model_version']/'als.npz')
    assert als.params['alpha']==5 and any(u<0 for u in als.user_ids_)
    # Повторная публикация заменяет топ, не накапливает строки.
    second = run_training(database, config(tmp_path, ml_anilist_data_dir=external))
    with database.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM recommendations')).scalar_one()==350
        assert c.execute(text('SELECT DISTINCT model_version FROM recommendations')).scalars().all()==[second['model_version']]


def test_empty_history_uses_catalog_and_dry_run_does_not_write(database,tmp_path):
    with database.begin() as c: c.execute(text('DELETE FROM user_anime'))
    result=run_training(database,config(tmp_path),write=False)
    assert not result['als_trained'] and not result['published']
    recs=json.loads((tmp_path/'artifacts'/result['model_version']/'recommendations.json').read_text())
    assert recs['7']==list(range(60,10,-1))
    with database.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM recommendations')).scalar_one()==0


def test_failed_insert_rolls_back_replacement(database):
    with database.begin() as c:
        c.execute(text("INSERT INTO recommendations VALUES (1,60,1,'old',NULL)"))
        # Ошибка БД после DELETE, не проверка входных данных до него.
        c.execute(text("CREATE TRIGGER reject_insert BEFORE INSERT ON recommendations BEGIN SELECT RAISE(ABORT, 'test'); END"))
    with pytest.raises(IntegrityError), database.begin() as c:
        publish(c,{1:[50]},'new',pd.Timestamp.now().to_pydatetime())
    with database.connect() as c:
        assert c.execute(text('SELECT anime_id,model_version FROM recommendations')).all()==[(60,'old')]


def test_external_user_ids_cannot_be_published(database):
    with pytest.raises(ValueError), database.begin() as c:
        publish(c,{-1:[1]},'bad',None)


def test_jobs_reject_overlap_and_report_failure_without_sensitive_details():
    entered, release = Event(), Event()
    def trainer():
        entered.set()
        assert release.wait(5)
        raise ValueError('secret DSN')
    jobs=TrainingJobs(trainer)
    try:
        assert jobs.submit() and entered.wait(5)
        assert not jobs.submit()
        assert jobs.status()=={'status':'running'}
    finally:
        release.set(); jobs.close()
    assert jobs.status()=={'status':'failed','error':'TRAIN_FAILED'}


def test_artifact_failure_does_not_publish(database, tmp_path):
    blocked = tmp_path / 'not-a-directory'
    blocked.write_text('occupied')
    settings = Settings(_env_file=None, ml_artifact_dir=blocked)
    with database.begin() as c:
        c.execute(text("INSERT INTO recommendations VALUES (1,60,1,'old',NULL)"))
    with pytest.raises(OSError):
        run_training(database, settings)
    with database.connect() as c:
        assert c.execute(text('SELECT anime_id,model_version FROM recommendations')).all()==[(60,'old')]
