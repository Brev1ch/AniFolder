"""Обучение на данных сайта + optional AniList, публикация топ-50 в общей БД."""
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from uuid import uuid4

import pandas as pd
from sqlalchemy import Engine, bindparam, text

from app.config import Settings
from app.db import make_engine
from app.recsys.als import ALSRecommender
from app.recsys.popularity import GenrePopularityRecommender, PopularityRecommender
from app.training.datasets import filter_interactions, load_anilist, to_catalog_ids
from app.training.weights import DEFAULT_STATUS_WEIGHTS, weighted_interactions

ALS_PARAMS = dict(factors=64, alpha=5, regularization=0.1, iterations=20,
                  num_threads=4, random_state=42)
LOCK_ID = 734091126  # общий для HTTP и CLI, PostgreSQL session advisory lock
logger = logging.getLogger(__name__)


def fit_recommendations(history, users, genres, catalog, now):
    """Прежние модели; при нехватке данных дополняем популярным/каталогом."""
    training = filter_interactions(history, min_user_items=5, min_item_users=5)
    weighted = weighted_interactions(training, score_coef=0, min_score=5,
                                     status_weights=DEFAULT_STATUS_WEIGHTS, half_life_days=None)
    als = ALSRecommender(**ALS_PARAMS).fit(weighted, history=history) if len(weighted) else None
    popularity_data = training if len(training) else history
    all_time = PopularityRecommender(window_days=None).fit(popularity_data, now=now, history=history)
    genre = GenrePopularityRecommender(genres, window_days=28, beta=1).fit(
        popularity_data, now=now, history=history)
    counts = history.user_id.value_counts()
    seen = history.groupby('user_id').anime_id.agg(set).to_dict()
    recommendations, routes = {}, Counter()
    for user in users:
        if counts.get(user, 0) == 0:
            primary, route = all_time.recommend(user, 50), 'all_time'
        elif counts.get(user, 0) >= 5 and als is not None and user in als.user_index_:
            primary, route = als.recommend(user, 50), 'als'
        else:
            primary, route = genre.recommend(user, 50), 'genre28'
        result = []
        excluded = set(seen.get(user, ()))
        # Первый источник определяет порядок; fallback только дополняет короткий список.
        for item in primary + all_time.recommend(user, 50) + catalog:
            if item not in excluded:
                result.append(int(item))
                excluded.add(item)
            if len(result) == 50:
                break
        recommendations[int(user)] = result
        routes[route] += 1
    return als, recommendations, dict(routes), len(weighted)


def publish(connection, recommendations, version, generated_at):
    """Вызов только внутри транзакции; ошибка вставки откатывает удаление."""
    users = sorted(recommendations)
    if any(u <= 0 for u in users):
        raise ValueError('Публиковать можно только положительные ID пользователей сайта')
    if not users:
        return 0
    for items in recommendations.values():
        if len(items) > 50 or len(items) != len(set(items)) or any(i <= 0 for i in items):
            raise ValueError('Некорректный список рекомендаций')
    # Удалённые во время обучения пользователи не получают строк; новые — в следующем запуске.
    query = 'SELECT id FROM users WHERE id IN :users ORDER BY id'
    if connection.dialect.name == 'postgresql':
        query += ' FOR UPDATE'
    existing = set(connection.execute(text(query).bindparams(bindparam('users', expanding=True)),
                                      {'users': users}).scalars())
    if not existing:
        return 0
    connection.execute(text('DELETE FROM recommendations WHERE user_id IN :users')
                       .bindparams(bindparam('users', expanding=True)), {'users': sorted(existing)})
    rows = [dict(user_id=u, anime_id=item, relevance=1.0 / rank,
                 model_version=version, generated_at=generated_at)
            for u in sorted(existing) for rank, item in enumerate(recommendations[u], 1)]
    if rows:
        connection.execute(text('INSERT INTO recommendations '
            '(user_id, anime_id, relevance, model_version, generated_at) '
            'VALUES (:user_id, :anime_id, :relevance, :model_version, :generated_at)'), rows)
    return len(rows)


def run_training(engine: Engine, settings: Settings, *, write: bool = True):
    version = 'als-v1-' + uuid4().hex[:16]
    now = pd.Timestamp.now(tz='UTC')
    with engine.connect() as connection:
        locked = False
        try:
            if connection.dialect.name == 'postgresql':
                locked = connection.execute(text('SELECT pg_try_advisory_lock(:id)'), {'id': LOCK_ID}).scalar_one()
                connection.commit()
                if not locked:
                    raise RuntimeError('Обучение уже выполняется другим процессом')
            with connection.begin():
                if connection.dialect.name == 'postgresql':
                    connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
                users = list(map(int, connection.execute(text('SELECT id FROM users ORDER BY id')).scalars()))
                site = pd.read_sql(text('SELECT user_id, anime_id, CAST(status AS TEXT) AS status, '
                                        'score, updated_at FROM user_anime'), connection)
                catalog_frame = pd.read_sql(text('SELECT a.id, a.anilist_id FROM anime a '
                    'LEFT JOIN anime_stats s ON s.anime_id=a.id '
                    'ORDER BY COALESCE(s.in_lists_count, 0) DESC, a.id'), connection)
                genre_rows = connection.execute(text('SELECT anime_id, genre_id FROM anime_genres')).all()
            if any(u <= 0 for u in users):
                raise ValueError('В users обнаружены неположительные ID')
            site = site.astype({'user_id': 'int64', 'anime_id': 'int64', 'score': 'Int8'})
            site['updated_at'] = pd.to_datetime(site.updated_at, utc=True)
            genres = {}
            for item, genre in genre_rows:
                genres.setdefault(int(item), []).append(int(genre))
            parts = [site]
            external_rows = matched_rows = 0
            if settings.ml_anilist_data_dir is not None:
                external = load_anilist(settings.ml_anilist_data_dir)
                if (external.user_id <= 0).any():
                    raise ValueError('AniList user_id должны быть положительными до преобразования')
                external_rows = len(external)
                mapped = to_catalog_ids(external, catalog_frame.set_index('anilist_id')['id'])
                matched_rows = len(mapped)
                if external_rows and not matched_rows:
                    logger.warning('No AniList interactions match the site catalog; training on site data only')
                parts.append(mapped)
            history = pd.concat(parts, ignore_index=True)
            if history.duplicated(['user_id', 'anime_id']).any():
                raise ValueError('Повторяющиеся пары user_id/anime_id')
            als, recs, routes, positives = fit_recommendations(
                history, users, genres, list(map(int, catalog_frame.id)), now)
            summary = dict(model_version=version, generated_at=now.isoformat(),
                als_parameters=ALS_PARAMS, score_coef=0, status_weights=DEFAULT_STATUS_WEIGHTS,
                min_score=5, min_user_items=5, min_item_users=5, half_life_days=None,
                item_id_namespace='site', external_user_ids='negative AniList IDs; never published',
                site_users=len(users), history_rows=len(history), positive_rows=positives,
                external_rows=external_rows, matched_external_rows=matched_rows, routes=routes,
                short_lists=sum(len(v)<50 for v in recs.values()), als_trained=als is not None,
                cold_policy='no history: all-time; short/unknown ALS: genre28 beta=1',
                fallback='all-time, then catalog in_lists_count; exclude snapshot history',
                published=False)
            folder = settings.ml_artifact_dir / version
            folder.mkdir(parents=True, exist_ok=False)
            if als is not None:
                als.save(folder / 'als.npz', metadata={k: v for k, v in summary.items() if k != 'published'})
            (folder / 'recommendations.json').write_text(json.dumps(recs) + '\n')
            (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
            if write:
                with connection.begin():
                    summary['written_rows'] = publish(connection, recs, version, now.to_pydatetime())
                summary['published'] = True
                try:
                    (folder / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
                except OSError:
                    # Коммит БД уже состоялся: не сообщаем об откате успешной публикации.
                    summary['manifest_update_failed'] = True
                    logger.error('Recommendations published, but artifact manifest could not be updated')
            return summary
        finally:
            if locked:
                connection.rollback()
                connection.execute(text('SELECT pg_advisory_unlock(:id)'), {'id': LOCK_ID})
                connection.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='атомарно опубликовать результаты в БД')
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings.database_url)
    try:
        print(json.dumps(run_training(engine, settings, write=args.write), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
