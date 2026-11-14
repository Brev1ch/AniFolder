"""Рекомендации текущего пользователя из таблицы, которую заполняет ML."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.anime import Anime
from app.models.library import Recommendation, UserAnime
from app.models.user import User
from app.schemas.anime import AnimeCard

router = APIRouter(prefix="/me", tags=["recommendations"])


class RecommendationResponse(BaseModel):
    anime_id: int
    relevance: float
    anime: AnimeCard


@router.get("/recommendations", response_model=list[RecommendationResponse])
async def get_recommendations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[RecommendationResponse]:
    # Исключения проверяются при каждом чтении, после изменений списка и обучения.
    seen = exists(select(UserAnime.anime_id).where(
        UserAnime.user_id == user.id, UserAnime.anime_id == Recommendation.anime_id))
    rows = (await session.execute(
        select(Recommendation, Anime).join(Anime, Anime.id == Recommendation.anime_id)
        .where(Recommendation.user_id == user.id, ~seen)
        .order_by(Recommendation.relevance.desc(), Recommendation.anime_id)
        .limit(limit)
    )).all()
    return [RecommendationResponse(anime_id=r.anime_id, relevance=r.relevance,
                                   anime=AnimeCard.model_validate(anime)) for r, anime in rows]
