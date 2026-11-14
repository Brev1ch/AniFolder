"""Контракт HTTP и реальные SQL-запросы в изолированной SQLite БД."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.db import make_engine
from app.main import create_app


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recommendations.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE recommendations (user_id BIGINT, anime_id BIGINT, relevance REAL, "
            "model_version TEXT, PRIMARY KEY (user_id, anime_id))"
        ))
        connection.execute(text("CREATE TABLE user_anime (user_id BIGINT, anime_id BIGINT)"))
        connection.execute(text("INSERT INTO user_anime VALUES (1, 101)"))
        connection.execute(text(
            "INSERT INTO recommendations VALUES (:user_id, :anime_id, :relevance, 'seed-popular')"
        ), [
            {"user_id": 1, "anime_id": i, "relevance": 1.0 if i in (101, 102) else 0.5}
            for i in reversed(range(101, 161))
        ] + [{"user_id": 2, "anime_id": 999, "relevance": 10.0}])
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    with TestClient(create_app(engine=engine, trainer=lambda: {"published": True})) as client:
        yield client


def test_recommendations_are_scoped_sorted_limited_and_keep_seen(client):
    response = client.get("/internal/v1/recommendations/1")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 20
    assert [r["anime_id"] for r in items] == list(range(101, 121))
    assert items[0] == {"anime_id": 101, "relevance": 1.0}
    # 101 есть в user_anime: фильтрация актуального списка остаётся backend.
    assert len(client.get("/internal/v1/recommendations/1?limit=50").json()) == 50
    assert client.get("/internal/v1/recommendations/2?limit=1").json() == [
        {"anime_id": 999, "relevance": 10.0}
    ]
    assert client.get("/internal/v1/recommendations/999").json() == []


@pytest.mark.parametrize("path", [
    "/recommendations/0", "/recommendations/-1", "/recommendations/9223372036854775808",
    "/recommendations/not-an-id", "/recommendations/1?limit=0",
    "/recommendations/1?limit=51", "/recommendations/1?limit=abc",
])
def test_invalid_identifiers_and_limits(client, path):
    response = client.get("/internal/v1" + path)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert all(set(e) == {"type", "loc", "msg"} for e in error["details"])


def test_train_accepts_real_job(client):
    response = client.post("/internal/v1/train")
    assert response.status_code == 202
    assert response.json() == {"status": "ok"}
    client.app.state.training.close()
    assert client.get("/internal/v1/train/status").json() == {
        "status": "succeeded", "result": {"published": True}}


def test_health_and_database_failure(client, engine):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/readiness").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE recommendations"))
    for path in ["/health/readiness", "/internal/v1/recommendations/1"]:
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"error": {
            "code": "DATABASE_UNAVAILABLE", "message": "База рекомендаций недоступна",
        }}
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("driver", ["postgresql", "postgresql+asyncpg", "postgresql+psycopg"])
def test_sync_driver_preserves_password_and_url_options(driver):
    engine = make_engine(f"{driver}://user:p%2Basyncpg@localhost/db?application_name=ml")
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.password == "p+asyncpg"
        assert engine.url.query == {"application_name": "ml"}
    finally:
        engine.dispose()


def test_train_returns_409_while_previous_job_runs(engine):
    from threading import Event
    entered, release = Event(), Event()

    def trainer():
        entered.set()
        assert release.wait(5)
        return {'published': True}

    with TestClient(create_app(engine=engine, trainer=trainer)) as client:
        try:
            assert client.post('/internal/v1/train').status_code == 202
            assert entered.wait(5)
            assert client.get('/internal/v1/train/status').json() == {'status': 'running'}
            response = client.post('/internal/v1/train')
            assert response.status_code == 409
            assert response.json()['error']['code'] == 'TRAIN_ALREADY_RUNNING'
        finally:
            release.set()
