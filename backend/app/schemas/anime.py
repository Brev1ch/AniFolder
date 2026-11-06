"""Схемы каталога: жанры, карточка тайтла в списке и детально со статистикой."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.models.anime import Anime


class GenreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name_ru: str | None
    name_en: str


class AnimeStatsResponse(BaseModel):
    """Агрегаты из anime_stats; пересчитывает refresh_anime_stats() в БД."""

    model_config = ConfigDict(from_attributes=True)

    scores_count: int
    avg_score: Decimal | None
    in_lists_count: int


class AnimeCard(BaseModel):
    """Тайтл в списке каталога."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    anilist_id: int
    mal_id: int | None
    title_ru: str | None
    title_en: str
    kind: str | None
    status: str
    episodes: int | None
    aired_on: date | None
    poster_url: str | None

    @classmethod
    def from_orm_list(cls, items: list[Anime]) -> list["AnimeCard"]:
        return [cls.model_validate(a) for a in items]


class AnimeDetail(AnimeCard):
    """Карточка тайтла: описание, жанры и заранее посчитанная статистика."""

    model_config = ConfigDict(from_attributes=True)

    description: str | None
    genres: list[GenreResponse]
    stats: AnimeStatsResponse | None


class AnimeListResponse(BaseModel):
    """Постраничная выдача каталога. Формат зеркалит frontend/src/types/anime.ts."""

    items: list[AnimeCard]
    total: int
    page: int
    limit: int
