"""Публичные профили: карточка пользователя, его список и лента активности."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.enums import ListStatus
from app.models.user import User
from app.schemas.library import (
    ActivityFeedResponse,
    CompatibilityResponse,
    UserAnimeListResponse,
    UserProfileResponse,
)
from app.services import library_service

router = APIRouter(prefix="/users", tags=["users"])

# Формат username из контракта: ^[A-Za-z0-9_]{3,32}$. Мусор отсекаем 422 до запроса к БД.
UsernamePath = Annotated[str, Path(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")]


@router.get("/{username}", response_model=UserProfileResponse)
async def get_user_profile(
    username: UsernamePath,
    session: AsyncSession = Depends(get_session),
) -> UserProfileResponse:
    """Профиль со статистикой списка: счётчики по статусам, средняя оценка."""
    return await library_service.get_profile(session, username)


@router.get("/{username}/list", response_model=UserAnimeListResponse)
async def get_user_list(
    username: UsernamePath,
    status: ListStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    session: AsyncSession = Depends(get_session),
) -> UserAnimeListResponse:
    """Список пользователя; без status — все тайтлы, свежие обновления первыми."""
    return await library_service.get_user_list(session, username, status, page, limit)


@router.get("/{username}/activity", response_model=ActivityFeedResponse)
async def get_user_activity(
    username: UsernamePath,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    session: AsyncSession = Depends(get_session),
) -> ActivityFeedResponse:
    """Лента активности, курсорная пагинация; next_cursor = null — записи кончились."""
    return await library_service.get_activity(session, username, cursor, limit)


@router.get("/{username}/compatibility", response_model=CompatibilityResponse)
async def get_user_compatibility(
    username: UsernamePath,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CompatibilityResponse:
    """Совпадение вкусов с текущим пользователем: корреляция по общим оценкам."""
    return await library_service.get_compatibility(session, user, username)
