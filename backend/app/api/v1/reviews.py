"""Отзывы: лента по тайтлу (GET /anime/{id}/reviews), создание, редактирование и
удаление автором (PATCH/DELETE /reviews/{id})."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.community import ReviewCreate, ReviewListResponse, ReviewPatch, ReviewResponse
from app.services import review_service

router = APIRouter(tags=["reviews"])


@router.get("/anime/{anime_id}/reviews", response_model=ReviewListResponse)
async def get_reviews(
    anime_id: Annotated[int, Path(ge=1)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    session: AsyncSession = Depends(get_session),
) -> ReviewListResponse:
    """Отзывы на тайтл, новые первыми."""
    return await review_service.list_reviews(session, anime_id, page, limit)


@router.post("/anime/{anime_id}/reviews", response_model=ReviewResponse, status_code=201)
async def post_review(
    body: ReviewCreate,
    anime_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """Написать отзыв; повтор на тот же тайтл — 409 REVIEW_EXISTS."""
    return await review_service.create_review(session, user, anime_id, body)


@router.patch("/reviews/{review_id}", response_model=ReviewResponse)
async def patch_review(
    body: ReviewPatch,
    review_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """Изменить отзыв (только автор); меняются только переданные поля."""
    return await review_service.patch_review(session, user, review_id, body)


@router.delete("/reviews/{review_id}")
async def delete_review(
    review_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    """Удалить отзыв (только автор)."""
    await review_service.delete_review(session, user.id, review_id)
    return {"ok": True}
