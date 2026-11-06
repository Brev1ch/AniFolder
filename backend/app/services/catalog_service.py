"""Чтение каталога: список с фильтрами и поиском, карточка тайтла, словарь жанров."""

import logging
from typing import Literal

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core import errors
from app.models.anime import Anime, AnimeStats, Genre, anime_genres
from app.schemas.anime import AnimeCard, AnimeDetail, AnimeListResponse, GenreResponse

logger = logging.getLogger(__name__)

SORT_POPULAR = "popular"
SORT_DATE = "date"
SORT_RATING = "rating"
SORT_TITLE = "title"
AnimeSort = Literal["popular", "date", "rating", "title"]

# Дефолтные сроки кэша каталога
CACHE_TTL_CARD = 600    # 10 минут
CACHE_TTL_LIST = 300    # 5 минут
CACHE_TTL_GENRES = 86_400  # сутки


def _escape_ilike(query: str) -> str:
    """Экранирует % и _ пользовательского запроса, чтобы ILIKE не ломался."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _build_filters(
    *,
    search: str | None,
    genre_id: int | None,
    status: str | None,
    kind: str | None,
    year_from: int | None,
    year_to: int | None,
) -> list[ColumnElement[bool]]:
    """Один набор условий для выборки и для count — итоги всегда согласованы."""
    filters: list[ColumnElement[bool]] = []
    if search:
        pattern = f"%{_escape_ilike(search)}%"
        filters.append(
            Anime.title_ru.ilike(pattern, escape="\\") | Anime.title_en.ilike(pattern, escape="\\")
        )
    if genre_id is not None:
        filters.append(
            exists().where(
                anime_genres.c.anime_id == Anime.id, anime_genres.c.genre_id == genre_id
            )
        )
    if status is not None:
        filters.append(Anime.status == status)
    if kind is not None:
        filters.append(Anime.kind == kind)
    if year_from is not None:
        filters.append(func.date_part("year", Anime.aired_on) >= year_from)
    if year_to is not None:
        filters.append(func.date_part("year", Anime.aired_on) <= year_to)
    return filters


def _relevance_expr(search: str) -> ColumnElement[float]:
    """Релевантность поиска: pg_trgm-similarity по обоим названиям."""
    return func.coalesce(
        func.greatest(
            func.similarity(Anime.title_ru, search), func.similarity(Anime.title_en, search)
        ),
        0.0,
    )


async def list_anime(
    session: AsyncSession,
    *,
    page: int,
    limit: int,
    search: str | None = None,
    genre_id: int | None = None,
    status: str | None = None,
    kind: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    sort: AnimeSort = SORT_POPULAR,
) -> AnimeListResponse:
    """Постраничная выдача каталога. При поиске и sort по умолчанию — по релевантности."""
    filters = _build_filters(
        search=search, genre_id=genre_id, status=status, kind=kind,
        year_from=year_from, year_to=year_to,
    )

    total = await session.scalar(select(func.count()).select_from(Anime).where(*filters))

    stmt = select(Anime).where(*filters)
    if search and sort == SORT_POPULAR:
        # при активном поиске дефолтный popular уступает релевантности
        stmt = stmt.order_by(_relevance_expr(search).desc(), Anime.id)
    elif sort == SORT_POPULAR:
        stmt = stmt.outerjoin(AnimeStats, AnimeStats.anime_id == Anime.id).order_by(
            func.coalesce(AnimeStats.in_lists_count, 0).desc(), Anime.id
        )
    elif sort == SORT_DATE:
        stmt = stmt.order_by(Anime.aired_on.desc().nulls_last(), Anime.id)
    elif sort == SORT_RATING:
        stmt = stmt.outerjoin(AnimeStats, AnimeStats.anime_id == Anime.id).order_by(
            AnimeStats.avg_score.desc().nulls_last(), Anime.id
        )
    else:  # title
        stmt = stmt.order_by(func.lower(Anime.title_en), Anime.id)

    stmt = stmt.limit(limit).offset((page - 1) * limit)
    items = list((await session.scalars(stmt)).all())
    return AnimeListResponse(
        items=AnimeCard.from_orm_list(items),
        total=total or 0,
        page=page,
        limit=limit,
    )


async def get_anime_detail(session: AsyncSession, anime_id: int) -> AnimeDetail:
    """Карточка тайтла со жанрами (selectinload) и статистикой (joinedload)."""
    stmt = (
        select(Anime)
        .where(Anime.id == anime_id)
        .options(
            selectinload(Anime.genres),
            joinedload(Anime.stats),
        )
    )
    anime = await session.scalar(stmt)
    if anime is None:
        raise errors.AppError(404, "ANIME_NOT_FOUND", f"Аниме с id={anime_id} не найдено")
    return AnimeDetail.model_validate(anime)


async def list_genres(session: AsyncSession) -> list[GenreResponse]:
    """Словарь жанров: name_ru может быть NULL — фронт тогда показывает name_en."""
    rows = await session.scalars(select(Genre).order_by(Genre.name_en))
    return [GenreResponse.model_validate(g) for g in rows]
