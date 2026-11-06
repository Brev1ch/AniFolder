"""Словарь жанров: GET /genres."""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.anime import GenreResponse
from app.services import catalog_service
from app.services.cache import cache_get_json, cache_set_json, get_redis

router = APIRouter(tags=["catalog"])

GENRES_CACHE_KEY = "genres:all"


@router.get("/genres", response_model=list[GenreResponse])
async def get_genres(
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
) -> list[GenreResponse]:
    """Все жанры каталога; name_ru NULL → показывать name_en."""
    cached = await cache_get_json(redis, GENRES_CACHE_KEY)
    if cached is not None:
        return [GenreResponse.model_validate(g) for g in cached]

    genres = await catalog_service.list_genres(session)
    await cache_set_json(
        redis, GENRES_CACHE_KEY, [g.model_dump() for g in genres], catalog_service.CACHE_TTL_GENRES
    )
    return genres
