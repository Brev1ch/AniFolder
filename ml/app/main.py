"""Запуск из ml/: uvicorn app.main:app --port 8001."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.api.recommendations import router
from app.config import Settings
from app.db import get_connection, make_engine
from app.training.jobs import TrainingJobs
from app.training.train import run_training

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, *, engine: Engine | None = None, trainer=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned_engine = engine is None
        config = settings if settings is not None else Settings()
        app.state.engine = engine if engine is not None else make_engine(
            config.database_url
        )
        app.state.training = TrainingJobs(trainer if trainer is not None else
            lambda: run_training(app.state.engine, config))
        try:
            yield
        finally:
            app.state.training.close()
            if owned_engine:
                app.state.engine.dispose()

    app = FastAPI(title="AniFolder Recommendation Service", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Не включаем SQL, параметры и DSN в ответ или лог.
        logger.error("ML database operation failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={
            "error": {"code": "DATABASE_UNAVAILABLE", "message": "База рекомендаций недоступна"},
        })

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {
            "code": "VALIDATION_ERROR", "message": "Некорректные параметры запроса",
            "details": [{"type": e["type"], "loc": e["loc"], "msg": e["msg"]} for e in exc.errors()],
        }})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/readiness")
    def readiness(connection: Connection = Depends(get_connection)) -> dict[str, str]:
        # Проверяем и соединение, и наличие требуемой таблицы/колонок.
        connection.execute(text("SELECT user_id, anime_id, relevance FROM recommendations LIMIT 0"))
        return {"status": "ok"}

    return app


app = create_app()
