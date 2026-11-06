"""Публичные эндпоинты каталога: GET /anime, GET /anime/{id}."""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.anime import AnimeDetail, AnimeListResponse
from app.services import catalog_service
from app.services.cache import cache_get_json, cache_set_json, get_redis

router = APIRouter(prefix="/anime", tags=["catalog"])

AnimeStatus = Literal["announced", "ongoing", "released", "hiatus", "cancelled"]
AnimeSort = Literal["popular", "date", "rating", "title"]


def _list_cache_key(params: dict[str, object]) -> str:
    """Ключ кэша выдачи — от всех параметров запроса."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, default=str)
    return "anime:list:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.get("", response_model=AnimeListResponse)
async def get_anime_list(
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    search: Annotated[str | None, Query(max_length=200)] = None,
    genre_id: Annotated[int | None, Query(ge=1)] = None,
    status: AnimeStatus | None = None,
    kind: Annotated[str | None, Query(max_length=16)] = None,
    year_from: Annotated[int | None, Query(ge=1950, le=2100)] = None,
    year_to: Annotated[int | None, Query(ge=1950, le=2100)] = None,
    sort: AnimeSort = "popular",
) -> AnimeListResponse:
    """Поиск и фильтрация каталога. Поиск — ILIKE по названиям (GIN pg_trgm)."""
    params = {
        "page": page, "limit": limit, "search": search, "genre_id": genre_id,
        "status": status, "kind": kind, "year_from": year_from, "year_to": year_to, "sort": sort,
    }
    cache_key = _list_cache_key(params)
    cached = await cache_get_json(redis, cache_key)
    if cached is not None:
        return AnimeListResponse.model_validate(cached)

    result = await catalog_service.list_anime(session, **params)
    await cache_set_json(redis, cache_key, result.model_dump(mode="json"), catalog_service.CACHE_TTL_LIST)
    return result


@router.get("/{anime_id}", response_model=AnimeDetail)
async def get_anime(
    anime_id: int,
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
) -> AnimeDetail:
    """Карточка тайтла со статистикой из anime_stats."""
    cache_key = f"anime:card:{anime_id}"
    cached = await cache_get_json(redis, cache_key)
    if cached is not None:
        return AnimeDetail.model_validate(cached)

    detail = await catalog_service.get_anime_detail(session, anime_id)
    await cache_set_json(redis, cache_key, detail.model_dump(mode="json"), catalog_service.CACHE_TTL_CARD)
    return detail
