"""Отзывы на тайтлы: лента по аниме, создание, редактирование и удаление автором.

Один отзыв на тайтл на пользователя (unique reviews_one_per_anime): дубль — 409.
При создании пишется событие reviewed в ленту активности (той же транзакцией).
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import errors
from app.models.anime import Anime
from app.models.enums import ActivityType
from app.models.library import Review, UserActivity
from app.models.user import User
from app.schemas.community import (
    DELETED_USERNAME,
    ReviewCreate,
    ReviewListResponse,
    ReviewPatch,
    ReviewResponse,
)

logger = logging.getLogger(__name__)


def _check_author(review: Review, user_id: int) -> None:
    """Только автор меняет свой отзыв; удалённый автор (user_id NULL) — никто."""
    if review.user_id != user_id:
        raise errors.AppError(403, errors.FORBIDDEN, "Чужой отзыв менять нельзя")


async def _get_review(session: AsyncSession, review_id: int) -> Review:
    review = await session.get(Review, review_id)
    if review is None:
        raise errors.AppError(404, errors.REVIEW_NOT_FOUND, f"Отзыв с id={review_id} не найден")
    return review


async def list_reviews(
    session: AsyncSession, anime_id: int, page: int, limit: int
) -> ReviewListResponse:
    """Отзывы на тайтл, новые первыми. Лента по индексу (anime_id, created_at DESC)."""
    anime_exists = await session.scalar(select(Anime.id).where(Anime.id == anime_id))
    if anime_exists is None:
        raise errors.AppError(404, errors.ANIME_NOT_FOUND, f"Аниме с id={anime_id} не найдено")

    total = await session.scalar(
        select(func.count()).select_from(Review).where(Review.anime_id == anime_id)
    )
    rows = (await session.execute(
        select(Review, User.username)
        .join(User, User.id == Review.user_id, isouter=True)
        .where(Review.anime_id == anime_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).all()

    items = [
        ReviewResponse(
            id=review.id, user_id=review.user_id,
            username=username if review.user_id is not None else DELETED_USERNAME,
            score=review.score, text=review.text, created_at=review.created_at,
        )
        for review, username in rows
    ]
    return ReviewListResponse(items=items, total=total or 0, page=page, limit=limit)


async def create_review(
    session: AsyncSession, user: User, anime_id: int, body: ReviewCreate
) -> ReviewResponse:
    anime_exists = await session.scalar(select(Anime.id).where(Anime.id == anime_id))
    if anime_exists is None:
        raise errors.AppError(404, errors.ANIME_NOT_FOUND, f"Аниме с id={anime_id} не найдено")

    existing = await session.scalar(
        select(Review.id).where(Review.user_id == user.id, Review.anime_id == anime_id)
    )
    if existing is not None:
        raise errors.AppError(409, errors.REVIEW_EXISTS, "Отзыв на этот тайтл уже есть")

    review = Review(user_id=user.id, anime_id=anime_id, score=body.score, text=body.text)
    session.add(review)
    try:
        await session.flush()
    except IntegrityError:
        # Параллельный POST прошёл предпроверку одновременно: unique reviews_one_per_anime
        await session.rollback()
        raise errors.AppError(409, errors.REVIEW_EXISTS, "Отзыв на этот тайтл уже есть") from None
    session.add(UserActivity(
        user_id=user.id, anime_id=anime_id,
        type=ActivityType.REVIEWED, payload={"review_id": review.id},
    ))
    await session.commit()

    return ReviewResponse(
        id=review.id, user_id=user.id, username=user.username,
        score=review.score, text=review.text, created_at=review.created_at,
    )


async def patch_review(
    session: AsyncSession, user: User, review_id: int, body: ReviewPatch
) -> ReviewResponse:
    review = await _get_review(session, review_id)
    _check_author(review, user.id)

    provided = body.model_fields_set
    if not provided:
        raise errors.AppError(422, errors.VALIDATION_ERROR, "Пустой PATCH: передайте score и/или text")
    null_fields = [f for f in provided if getattr(body, f) is None]
    if null_fields:
        raise errors.AppError(
            422, errors.VALIDATION_ERROR,
            f"Поля не могут быть null: {', '.join(sorted(null_fields))}",
        )

    if "score" in provided:
        review.score = body.score
    if "text" in provided:
        review.text = body.text
    # updated_at обновляет триггер set_updated_at
    await session.flush()
    await session.refresh(review, attribute_names=["updated_at"])
    await session.commit()

    return ReviewResponse(
        id=review.id, user_id=user.id, username=user.username,
        score=review.score, text=review.text, created_at=review.created_at,
    )


async def delete_review(session: AsyncSession, user_id: int, review_id: int) -> None:
    review = await _get_review(session, review_id)
    _check_author(review, user_id)
    await session.delete(review)
    await session.commit()
