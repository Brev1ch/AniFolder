"""Точка входа Backend API: uvicorn app.main:app."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_error_handlers
from app.db.session import get_session
from app.services import scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Подключение Redis и фоновые задачи. Redis необязателен: API работает и без него."""
    redis: Redis | None = None
    try:
        redis = Redis.from_url(settings.redis_url)
        await redis.ping()
    except RedisError:
        logger.warning("Redis недоступен (%s) — кэш отключён", settings.redis_url)
        if redis is not None:
            await redis.close(close_connection_pool=True)
        redis = None
    app.state.redis = redis

    scheduler_task = await scheduler.start()

    yield

    scheduler_task.cancel()
    if redis is not None:
        await redis.close(close_connection_pool=True)


def create_app() -> FastAPI:
    app = FastAPI(title="AniFolder API", version="0.1.0", lifespan=lifespan)

    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness-проба: приложение поднялось. Доступность БД сюда не включаем."""
        return {"status": "ok"}

    @app.get("/health/readiness")
    async def readiness(session: AsyncSession = Depends(get_session)) -> JSONResponse:
        """Readiness-проба: приложение может обслуживать запросы (БД доступна)."""
        try:
            await session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Readiness-проверка не пройдена: БД недоступна")
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ok"})

    return app


app = create_app()
