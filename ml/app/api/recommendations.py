"""Чтение готовых рекомендаций и запуск обучения."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from app.db import get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/v1")


class Recommendation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    anime_id: int
    relevance: float


class TrainAccepted(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/recommendations/{user_id}", response_model=list[Recommendation])
def recommendations(
    user_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    connection: Annotated[Connection, Depends(get_connection)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[dict]:
    """Готовые строки в ID сайта; актуальный user_anime фильтрует backend.

    Без сохранённых рекомендаций (включая неизвестного пользователя) — [].
    При одинаковой relevance порядок стабилен по anime_id.
    """
    rows = connection.execute(
        text("SELECT anime_id, relevance FROM recommendations "
             "WHERE user_id = :user_id "
             "ORDER BY relevance DESC, anime_id ASC LIMIT :limit"),
        {"user_id": user_id, "limit": limit},
    ).mappings()
    return [dict(row) for row in rows]


@router.post("/train", response_model=TrainAccepted, status_code=202)
def train(request: Request):
    """Запускает обучение в фоне. Результат — GET /internal/v1/train/status."""
    if not request.app.state.training.submit():
        return JSONResponse(status_code=409, content={"error": {
            "code": "TRAIN_ALREADY_RUNNING", "message": "Обучение уже выполняется"}})
    return TrainAccepted()


@router.get("/train/status")
def train_status(request: Request):
    """idle/running/succeeded/failed; статус хранится до перезапуска процесса."""
    return request.app.state.training.status()
