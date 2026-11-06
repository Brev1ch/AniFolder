"""Catalog Sync Worker: импортирует каталог аниме из AniList в PostgreSQL.

Правила маппинга и upsert — строго из docs/database.md:
- тайтлы: upsert по anilist_id (ON CONFLICT (anilist_id) DO UPDATE), title_ru не трогаем;
- mal_id — idMal из того же ответа (NULL, если AniList его не знает);
- title_en — title.english, при отсутствии title.romaji; title_ru — NULL (в AniList русских названий нет);
- kind — format в нижнем регистре; status переводится в наши значения;
- жанры: upsert по name_en (ON CONFLICT DO NOTHING), name_ru не трогать; связи тайтла пересобираются.

Запуск:
    python -m app.workers.catalog_sync              # инкремент по курсору (Redis), без курсора — полный
    python -m app.workers.catalog_sync --full       # полный импорт
    python -m app.workers.catalog_sync --full --max-pages 3   # прогон нескольких страниц для проверки
"""

import argparse
import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.anime import Anime, Genre, anime_genres

logger = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"
PER_PAGE = 50
# AniList разрешает ~90 запросов/минуту: держим интервал с запасом
REQUEST_INTERVAL = 0.7
MAX_RETRIES = 3
BACKOFF_BASE = 1.0

CURSOR_KEY = "catalog:sync:updated_at"

# Статусы AniList -> наши значения (docs/database.md). Неизвестный статус — тайтл пропускаем:
# CHECK-ограничение в БД его всё равно отклонит.
STATUS_MAP = {
    "NOT_YET_RELEASED": "announced",
    "RELEASING": "ongoing",
    "FINISHED": "released",
    "HIATUS": "hiatus",
    "CANCELLED": "cancelled",
}

QUERY = """
query ($page: Int!, $perPage: Int!, $updatedAtGreater: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(type: ANIME, updatedAt_greater: $updatedAtGreater, sort: ID) {
      id
      idMal
      format
      status
      updatedAt
      title { english romaji }
      episodes
      description
      startDate { year month day }
      coverImage { large }
      genres
    }
  }
}
"""


def map_media(media: dict[str, Any]) -> dict[str, Any] | None:
    """AniList media -> значения колонок anime. None — тайтл пропускаем (неизвестный статус)."""
    status = STATUS_MAP.get(media.get("status") or "")
    if status is None:
        logger.warning("Тайтл %s: неизвестный статус %r — пропущен", media.get("id"), media.get("status"))
        return None

    title = media.get("title") or {}
    title_en = title.get("english") or title.get("romaji") or f"AniList #{media['id']}"

    start = media.get("startDate") or {}
    year, month, day = start.get("year"), start.get("month"), start.get("day")
    # Неполная дата (известен только год) -> NULL: врать date(year, 1, 1) хуже
    aired_on = date(year, month, day) if year and month and day else None

    cover = media.get("coverImage") or {}
    return {
        "anilist_id": media["id"],
        "mal_id": media.get("idMal"),
        "title_ru": None,
        "title_en": title_en[:512],
        "kind": media["format"].lower() if media.get("format") else None,
        "status": status,
        "episodes": media.get("episodes"),
        "aired_on": aired_on,
        "description": media.get("description"),
        "poster_url": cover.get("large"),
        "_genres": media.get("genres") or [],
        "_updated_at": media.get("updatedAt") or 0,
    }


async def apply_media_batch(session: AsyncSession, medias: list[dict[str, Any]]) -> int:
    """Применяет страницу AniList к БД: upsert тайтлов, жанров и связей. Возвращает число тайтлов."""
    rows = [r for r in (map_media(m) for m in medias) if r is not None]
    if not rows:
        return 0

    genre_names = {g for r in rows for g in r["_genres"]}
    if genre_names:
        await session.execute(
            pg_insert(Genre).values([{"name_en": n} for n in sorted(genre_names)]).on_conflict_do_nothing(
                index_elements=["name_en"]
            )
        )
        genre_ids = dict(
            (await session.execute(select(Genre.name_en, Genre.id).where(Genre.name_en.in_(genre_names)))).all()
        )
    else:
        genre_ids = {}

    stmt = (
        pg_insert(Anime)
        .values([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])
        .on_conflict_do_update(
            index_elements=["anilist_id"],
            set_={
                "mal_id": pg_insert(Anime).excluded.mal_id,
                "title_en": pg_insert(Anime).excluded.title_en,
                "kind": pg_insert(Anime).excluded.kind,
                "status": pg_insert(Anime).excluded.status,
                "episodes": pg_insert(Anime).excluded.episodes,
                "aired_on": pg_insert(Anime).excluded.aired_on,
                "description": pg_insert(Anime).excluded.description,
                "poster_url": pg_insert(Anime).excluded.poster_url,
                "synced_at": func.now(),
            },
        )
        .returning(Anime.id, Anime.anilist_id)
    )
    anime_ids = dict((await session.execute(stmt)).all())

    # Связи жанров — полный снимок из AniList: заменяем старый набор новым
    await session.execute(
        anime_genres.delete().where(anime_genres.c.anime_id.in_(anime_ids.values()))
    )
    links = [
        {"anime_id": anime_ids[r["anilist_id"]], "genre_id": genre_ids[g]}
        for r in rows
        for g in r["_genres"]
        if g in genre_ids
    ]
    if links:
        await session.execute(pg_insert(anime_genres).values(links).on_conflict_do_nothing())

    await session.commit()
    return len(rows)


class AniListClient:
    """HTTP-клиент AniList с троттлингом (~85 запросов/мин) и повторами на 429/5xx."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def _throttle(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = REQUEST_INTERVAL - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = asyncio.get_event_loop().time()

    async def fetch_page(self, page: int, updated_at_greater: int | None) -> dict[str, Any]:
        variables: dict[str, Any] = {"page": page, "perPage": PER_PAGE}
        if updated_at_greater is not None:
            variables["updatedAtGreater"] = updated_at_greater

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            await self._throttle()
            try:
                response = await self._http.post(
                    ANILIST_URL, json={"query": QUERY, "variables": variables}
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"AniList вернул {response.status_code}",
                        request=response.request, response=response,
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_error = exc
                delay = max(BACKOFF_BASE * (2 ** attempt), 5.0 if "429" in str(exc) else 0.0)
                logger.warning(
                    "Запрос страницы %s неудачен (попытка %s/%s): %s — пауза %.1f с",
                    page, attempt + 1, MAX_RETRIES, exc, delay,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(f"AniList недоступен на странице {page}") from last_error


async def _load_cursor(redis: Redis | None) -> int | None:
    if redis is None:
        return None
    try:
        value = await redis.get(CURSOR_KEY)
        return int(value) if value else None
    except RedisError:
        logger.warning("Не удалось прочитать курсор синхронизации из Redis")
        return None


async def _save_cursor(redis: Redis | None, updated_at: int) -> None:
    if redis is None:
        return
    try:
        await redis.set(CURSOR_KEY, updated_at)
    except RedisError:
        logger.warning("Не удалось сохранить курсор синхронизации — следующий прогон будет полным")


async def run(full: bool = False, max_pages: int | None = None) -> int:
    """Полный или инкрементальный импорт. Возвращает число обработанных тайтлов."""
    redis: Redis | None = None
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()
    except RedisError:
        logger.warning("Redis недоступен — курсор инкрементальной синхронизации не используется")
        if redis is not None:
            await redis.close(close_connection_pool=True)
        redis = None

    cursor = None if full else await _load_cursor(redis)
    if full or cursor is None:
        updated_at_greater: int | None = None
        logger.info("Полный импорт каталога из AniList")
    else:
        # строгое сравнение в AniList: пересекаем курсор на 1 секунду, upsert идемпотентен
        updated_at_greater = cursor - 1
        logger.info("Инкрементальный импорт: updatedAt > %s", updated_at_greater)

    client = AniListClient()
    total = 0
    max_updated_at = cursor or 0
    try:
        page = 1
        while True:
            payload = await client.fetch_page(page, updated_at_greater)
            data = payload.get("data", {}).get("Page", {})
            medias = data.get("media") or []
            if not medias:
                break

            async with SessionLocal() as session:
                applied = await apply_media_batch(session, medias)
            total += applied
            max_updated_at = max(max_updated_at, max(m.get("updatedAt") or 0 for m in medias))

            if page % 10 == 0 or applied < PER_PAGE:
                logger.info("Обработано страниц: %s, тайтлов: %s", page, total)

            if not data.get("pageInfo", {}).get("hasNextPage"):
                break
            if max_pages is not None and page >= max_pages:
                logger.info("Остановка по --max-pages=%s", max_pages)
                break
            page += 1
    finally:
        await client.close()
        if redis is not None:
            await _save_cursor(redis, max_updated_at)
            await redis.close(close_connection_pool=True)

    logger.info("Синхронизация завершена: %s тайтлов, курсор updatedAt=%s", total, max_updated_at)
    return total


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Импорт каталога аниме из AniList")
    parser.add_argument("--full", action="store_true", help="полный импорт вместо инкрементального")
    parser.add_argument("--max-pages", type=int, default=None, help="ограничить число страниц (отладка)")
    args = parser.parse_args()
    asyncio.run(run(full=args.full, max_pages=args.max_pages))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
