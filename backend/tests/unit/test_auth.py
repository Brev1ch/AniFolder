"""Тесты auth: регистрация, вход, refresh-ротация, детект повторного использования."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from app.core.security import hash_refresh_token, verify_password
from app.models.user import RefreshToken, User
from tests.conftest import ApiTestContext

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
ME_URL = "/api/v1/_test/me"

PASSWORD = "password123"


async def _register(api: ApiTestContext, username: str = "user1", email: str = "user1@example.com") -> dict:
    response = await api.client.post(
        REGISTER_URL,
        json={"username": username, "email": email, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_register_success(api: ApiTestContext) -> None:
    data = await _register(api)

    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "user1"
    assert data["user"]["email"] == "user1@example.com"

    user = await api.session.scalar(select(User).where(User.username == "user1"))
    assert user is not None
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash)

    # в БД лежит SHA-256 refresh-токена, а не сам токен
    row = await api.session.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
    assert row is not None
    assert row.token_hash == hash_refresh_token(data["refresh_token"])
    assert row.token_hash != data["refresh_token"]
    assert row.revoked is False
    assert row.expires_at > datetime.now(timezone.utc)


@pytest.mark.parametrize("username", ["ab", "кириллица", "bad name", "x" * 33, "-bad"])
async def test_register_invalid_username(api: ApiTestContext, username: str) -> None:
    response = await api.client.post(
        REGISTER_URL,
        json={"username": username, "email": "u@example.com", "password": PASSWORD},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_register_short_password(api: ApiTestContext) -> None:
    response = await api.client.post(
        REGISTER_URL,
        json={"username": "user1", "email": "u@example.com", "password": "short"},
    )
    assert response.status_code == 422
    # значения полей (input) не возвращаем: в деталях не должно быть самого пароля
    details = response.json()["error"]["details"]
    assert details and all("input" not in d for d in details)


async def test_register_username_taken_case_insensitive(api: ApiTestContext) -> None:
    await _register(api, username="User_One", email="u1@example.com")
    response = await api.client.post(
        REGISTER_URL,
        json={"username": "user_one", "email": "u2@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


async def test_register_email_taken_case_insensitive(api: ApiTestContext) -> None:
    await _register(api, username="user1", email="User@Example.com")
    response = await api.client.post(
        REGISTER_URL,
        json={"username": "user2", "email": "user@example.com", "password": PASSWORD},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_login_success(api: ApiTestContext) -> None:
    await _register(api)
    response = await api.client.post(
        LOGIN_URL, json={"username": "user1", "password": PASSWORD}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["username"] == "user1"

    user_id = data["user"]["id"]
    tokens_count = await api.session.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.user_id == user_id)
    )
    assert tokens_count == 2  # регистрация + вход, обе сессии активны


async def test_login_wrong_password(api: ApiTestContext) -> None:
    await _register(api)
    response = await api.client.post(
        LOGIN_URL, json={"username": "user1", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_user(api: ApiTestContext) -> None:
    response = await api.client.post(
        LOGIN_URL, json={"username": "ghost", "password": PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_refresh_success(api: ApiTestContext) -> None:
    data = await _register(api)
    response = await api.client.post(REFRESH_URL, json={"refresh_token": data["refresh_token"]})
    assert response.status_code == 200

    new_data = response.json()
    assert new_data["access_token"] != data["access_token"]
    assert new_data["refresh_token"] != data["refresh_token"]
    assert new_data["user"]["id"] == data["user"]["id"]

    # старая запись отозвана, новый хэш в БД
    old_hash = hash_refresh_token(data["refresh_token"])
    new_hash = hash_refresh_token(new_data["refresh_token"])
    old_row = await api.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == old_hash))
    new_row = await api.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == new_hash))
    assert old_row is not None and old_row.revoked is True
    assert new_row is not None and new_row.revoked is False


async def test_refresh_invalid_token(api: ApiTestContext) -> None:
    response = await api.client.post(REFRESH_URL, json={"refresh_token": "garbage"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_refresh_reuse_revokes_family(api: ApiTestContext) -> None:
    """Повторное использование отозванного токена отзывает все сессии пользователя."""
    data = await _register(api)
    login_response = await api.client.post(
        LOGIN_URL, json={"username": "user1", "password": PASSWORD}
    )
    assert login_response.status_code == 200

    # первая ротация проходит, токен из регистрации отзывается
    first = await api.client.post(REFRESH_URL, json={"refresh_token": data["refresh_token"]})
    assert first.status_code == 200

    # второй раз тем же токеном — детект компрометации, вся семья отозвана
    second = await api.client.post(REFRESH_URL, json={"refresh_token": data["refresh_token"]})
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    active = await api.session.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == data["user"]["id"], RefreshToken.revoked.is_(False))
    )
    assert active == 0

    # и токен из логина, и свежий из первой ротации — тоже мёртвы
    for token in (login_response.json()["refresh_token"], first.json()["refresh_token"]):
        dead = await api.client.post(REFRESH_URL, json={"refresh_token": token})
        assert dead.status_code == 401


async def test_refresh_expired_token(api: ApiTestContext) -> None:
    data = await _register(api)
    token_hash = hash_refresh_token(data["refresh_token"])
    await api.session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    response = await api.client.post(REFRESH_URL, json={"refresh_token": data["refresh_token"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "REFRESH_TOKEN_EXPIRED"

    # простое истечение срока — не признак компрометации, семья не отзывается
    row = await api.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    assert row is not None and row.revoked is False


async def test_me_requires_auth(api: ApiTestContext) -> None:
    response = await api.client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_me_with_access_token(api: ApiTestContext) -> None:
    data = await _register(api)
    response = await api.client.get(
        ME_URL, headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json() == {"id": data["user"]["id"], "username": "user1"}


async def test_me_with_expired_access_token(api: ApiTestContext, monkeypatch: pytest.MonkeyPatch) -> None:
    data = await _register(api)
    monkeypatch.setattr("app.core.security.settings.access_token_ttl", -10)
    from app.core.security import create_access_token

    expired = create_access_token(data["user"]["id"])
    monkeypatch.undo()

    response = await api.client.get(ME_URL, headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_me_with_garbage_token(api: ApiTestContext) -> None:
    response = await api.client.get(ME_URL, headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
