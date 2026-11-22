"""Схемы списков пользователя, профилей и ленты активности (контракт — docs/api.md)."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ActivityType, ListStatus
from app.schemas.anime import AnimeCard


class UserListEntryPut(BaseModel):
    """Тело PUT /me/list/{anime_id}.

    Семантика полей (согласовано с тимлидом): пропущенное поле сохраняет
    прежнее значение; явный ``"score": null`` снимает оценку; прогресс
    сбрасывается явным ``episodes_watched: 0``. Различие «не передано / null»
    видно через model_fields_set.
    """

    status: ListStatus
    score: int | None = Field(default=None, ge=1, le=10)
    episodes_watched: int | None = Field(default=None, ge=0)


class UserListEntryResponse(BaseModel):
    """Запись списка после upsert + карточка тайтла."""

    model_config = ConfigDict(from_attributes=True)

    anime_id: int
    status: ListStatus
    score: int | None
    episodes_watched: int
    updated_at: datetime
    anime: AnimeCard


class UserListAnime(AnimeCard):
    """Элемент выдачи списка: карточка + поля записи.

    Поле status — статус списка: по контракту фронта (UserListAnime в
    frontend/src/types/anime.ts) оно затеняет статус самого тайтла.
    """

    model_config = ConfigDict(from_attributes=True)

    status: ListStatus
    score: int | None
    episodes_watched: int
    updated_at: datetime


class UserAnimeListResponse(BaseModel):
    """Постраничная выдача списка пользователя."""

    items: list[UserListAnime]
    total: int
    page: int
    limit: int


class UserProfileStats(BaseModel):
    """Статистика списка для профиля: счётчики по статусам и агрегаты по оценкам."""

    planned: int
    watching: int
    completed: int
    on_hold: int
    dropped: int
    scores_count: int
    mean_score: Decimal | None


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar_url: str | None
    bio: str | None
    created_at: datetime
    stats: UserProfileStats


class CompatibilityResponse(BaseModel):
    """Совпадение вкусов двух пользователей: корреляция Пирсона по общим оценкам."""

    common_titles: int
    compatibility: float | None


class ActivityItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: ActivityType
    anime_id: int | None
    payload: dict[str, Any]
    created_at: datetime
    anime: AnimeCard | None


class ActivityFeedResponse(BaseModel):
    """Курсорная лента: next_cursor = null, когда записи кончились."""

    items: list[ActivityItemResponse]
    next_cursor: str | None
