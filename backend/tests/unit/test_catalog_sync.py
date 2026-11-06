"""Тесты Catalog Sync Worker: маппинг AniList -> anime и upsert в БД.

Маппинг проверяется без сети; upsert — на тестовой БД (договорённости docs/database.md):
upsert по anilist_id, title_ru не перезаписывается, жанры — по name_en, связи пересобираются.
"""

from sqlalchemy import select

from app.models.anime import Anime, Genre, anime_genres
from app.workers.catalog_sync import apply_media_batch, map_media
from tests.api_context import ApiTestContext


def _media(anilist_id: int, **overrides: object) -> dict:
    media = {
        "id": anilist_id,
        "idMal": 1000 + anilist_id,
        "format": "TV",
        "status": "FINISHED",
        "updatedAt": 1_700_000_000 + anilist_id,
        "title": {"english": f"English {anilist_id}", "romaji": f"Romaji {anilist_id}"},
        "episodes": 12,
        "description": "Описание",
        "startDate": {"year": 2020, "month": 4, "day": 1},
        "coverImage": {"large": "https://img.example.com/large.jpg"},
        "genres": ["Action", "Comedy"],
    }
    media.update(overrides)
    return media


# --- Маппинг (без сети и БД) ---


def test_map_media_full() -> None:
    row = map_media(_media(7)) or {}
    assert row["anilist_id"] == 7
    assert row["mal_id"] == 1007
    assert row["title_en"] == "English 7"
    assert row["title_ru"] is None
    assert row["kind"] == "tv"
    assert row["status"] == "released"
    assert str(row["aired_on"]) == "2020-04-01"
    assert row["_genres"] == ["Action", "Comedy"]


def test_map_media_fallbacks() -> None:
    # english отсутствует -> romaji
    row = map_media(_media(8, title={"english": None, "romaji": "Romaji 8"}))
    assert row is not None and row["title_en"] == "Romaji 8"

    # нет ни english, ни romaji -> синтетическое название (title_en NOT NULL)
    row = map_media(_media(9, title={"english": None, "romaji": None}))
    assert row is not None and row["title_en"] == "AniList #9"

    # неполная дата -> aired_on NULL
    row = map_media(_media(10, startDate={"year": 2025, "month": None, "day": None}))
    assert row is not None and row["aired_on"] is None

    # idMal отсутствует -> NULL
    row = map_media(_media(11, idMal=None))
    assert row is not None and row["mal_id"] is None

    # формат отсутствует -> kind NULL
    row = map_media(_media(12, format=None))
    assert row is not None and row["kind"] is None


def test_map_media_status_map_and_unknown() -> None:
    assert (map_media(_media(20, status="NOT_YET_RELEASED")) or {})["status"] == "announced"
    assert (map_media(_media(21, status="RELEASING")) or {})["status"] == "ongoing"
    assert (map_media(_media(22, status="HIATUS")) or {})["status"] == "hiatus"
    assert (map_media(_media(23, status="CANCELLED")) or {})["status"] == "cancelled"
    # неизвестный статус — тайтл пропускается (CHECK в БД отклонил бы вставку)
    assert map_media(_media(24, status="UNKNOWN_VALUE")) is None


# --- Upsert на тестовой БД ---


async def test_apply_batch_inserts_with_genres(api: ApiTestContext) -> None:
    count = await apply_media_batch(api.session, [_media(1), _media(2, genres=[])])
    assert count == 2

    anime = await api.session.scalar(select(Anime).where(Anime.anilist_id == 1))
    assert anime is not None
    assert anime.title_en == "English 1"
    assert anime.kind == "tv"
    assert anime.status == "released"

    genre_rows = (
        await api.session.execute(
            select(Genre.name_en)
            .join(anime_genres, anime_genres.c.genre_id == Genre.id)
            .where(anime_genres.c.anime_id == anime.id)
        )
    ).scalars().all()
    assert set(genre_rows) == {"Action", "Comedy"}

    # новые жанры создались с name_ru = NULL, словарные переводы не тронуты
    action = await api.session.scalar(select(Genre).where(Genre.name_en == "Action"))
    assert action is not None and action.name_ru == "Экшен"
    comedy = await api.session.scalar(select(Genre).where(Genre.name_en == "Comedy"))
    assert comedy is not None and comedy.name_ru == "Комедия"


async def test_apply_batch_upsert_keeps_title_ru_and_replaces_genres(api: ApiTestContext) -> None:
    await apply_media_batch(api.session, [_media(1)])

    # ручной перевод названия, как договорённость: синхронизация его не трогает
    anime = await api.session.scalar(select(Anime).where(Anime.anilist_id == 1))
    assert anime is not None
    anime.title_ru = "Ручной перевод"
    anime_id = anime.id
    await api.session.flush()

    # повторная синхронизация: данные обновились
    await apply_media_batch(
        api.session, [_media(1, title={"english": "New Title", "romaji": None}, genres=["Drama"])]
    )

    await api.session.refresh(anime)
    assert anime.id == anime_id  # тот же тайтл, новых строк нет
    assert anime.title_en == "New Title"
    assert anime.title_ru == "Ручный перевод"  # не перезаписан

    genre_rows = (
        await api.session.execute(
            select(Genre.name_en)
            .join(anime_genres, anime_genres.c.genre_id == Genre.id)
            .where(anime_genres.c.anime_id == anime_id)
        )
    ).scalars().all()
    assert genre_rows == ["Drama"]  # связи пересобраны, старые удалены


async def test_apply_batch_skips_unknown_status(api: ApiTestContext) -> None:
    count = await apply_media_batch(api.session, [_media(30, status="WEIRD")])
    assert count == 0
    anime = await api.session.scalar(select(Anime).where(Anime.anilist_id == 30))
    assert anime is None
