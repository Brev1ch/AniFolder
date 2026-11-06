"""Тестовый контур: БД anifolder_test, миграции alembic, транзакционный откат между тестами.

Логика изоляции: на каждый тест открывается одна внешняя транзакция; HTTP-запросы
через ASGI-клиент идут в сессию этой транзакции; «коммиты» сервиса — это savepoint
внутри неё, а после теста ROLLBACK откатывает всё. БД поднимается один раз на прогон:
DROP/CREATE + alembic upgrade head (реальный SQL миграции — партиции и триггеры).
"""

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

# Детерминированные настройки до импорта приложения; БД берём из .env/окружения пользователя
os.environ["JWT_SECRET"] = "test-secret-key-0123456789abcdef-not-for-production"
os.environ["DB_ECHO"] = "false"

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.api.deps import get_current_user  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import get_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.user import User  # noqa: E402
from tests.api_context import ApiTestContext

TEST_DATABASE_NAME = "anifolder_test"

_test_url = make_url(settings.database_url).set(database=TEST_DATABASE_NAME)
TEST_DATABASE_URL = _test_url.render_as_string(hide_password=False)
ADMIN_DATABASE_URL = make_url(settings.database_url).set(database="postgres").render_as_string(hide_password=False)


async def _recreate_database() -> None:
    """Пересоздание тестовой БД: DDL требует autocommit-изоляции."""
    engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME} WITH (FORCE)"))
        await connection.execute(text(f"CREATE DATABASE {TEST_DATABASE_NAME}"))
    await engine.dispose()


async def _drop_database() -> None:
    engine = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(f"DROP DATABASE IF EXISTS {TEST_DATABASE_NAME} WITH (FORCE)"))
    await engine.dispose()


@pytest.fixture(scope="session")
def database_ready() -> Iterator[None]:
    """Одна тестовая БД на прогон pytest: создаём, накатываем миграции, в конце удаляем."""
    asyncio.run(_recreate_database())
    # env.py читает URL из settings, а не из alembic.ini — подменяем до вызова upgrade
    settings.database_url = TEST_DATABASE_URL
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(alembic_cfg, "head")
    yield
    asyncio.run(_drop_database())


@pytest_asyncio.fixture
async def api(database_ready: None) -> AsyncIterator[ApiTestContext]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    app: FastAPI = create_app()

    # Защищённый эндпоинт для проверки get_current_user; прод-роутеры появятся на следующих этапах
    @app.get("/api/v1/_test/me")
    async def test_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
        return {"id": user.id, "username": user.username}

    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(bind=connection, expire_on_commit=False)
        session = session_factory()

        async def override_get_session() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_session] = override_get_session
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield ApiTestContext(client=client, session=session, app=app)
        app.dependency_overrides.clear()
        await session.close()
        await connection.rollback()
    await engine.dispose()
