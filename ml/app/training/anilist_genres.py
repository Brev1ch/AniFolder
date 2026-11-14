"""Возобновляемая загрузка жанров AniList для тайтлов из истории.

Из ml/: .venv/bin/python -m app.training.anilist_genres \
    --before 2026-09-02T00:34:23Z
Кэш не меняет исходные списки; жанры — текущие метаданные, не исторический снимок.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.training.anilist_crawler import AniListClient, DEFAULT_OUT
from app.training.datasets import DEFAULT_ANILIST_DIR, load_anilist

log = logging.getLogger(__name__)
DEFAULT_GENRES_PATH = DEFAULT_OUT / "genres.json"
GENRES_QUERY = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    media(id_in: $ids, type: ANIME, sort: ID) { id genres }
  }
}
"""


def read_cache(path: Path = DEFAULT_GENRES_PATH) -> dict:
    if not path.exists():
        return {"version": 1, "items": {}}
    cache = json.loads(path.read_text())
    if cache.get("version") != 1 or not isinstance(cache.get("items"), dict):
        raise ValueError("неизвестный формат кэша жанров")
    return cache


def fetch_genres(
    client: AniListClient,
    anime_ids: Iterable[int],
    path: Path = DEFAULT_GENRES_PATH,
    *,
    retry_missing: bool = False,
) -> dict:
    """Пачки до 50 ID, атомарное сохранение после каждого успешного ответа.

    genres=null в кэше — тайтл не вернулся в ответе; [] — вернулся без жанров.
    Сетевые/GraphQL-ошибки не помечают пачку обработанной. Повторный запуск
    докачивает отсутствующие ID; retry_missing повторяет также недоступные.
    """
    cache = read_cache(path)
    items = cache["items"]
    wanted = sorted({int(i) for i in anime_ids})
    pending = [i for i in wanted if str(i) not in items or
               (retry_missing and items[str(i)]["genres"] is None)]
    log.info("нужно %d тайтлов, осталось загрузить %d", len(wanted), len(pending))
    for offset in range(0, len(pending), 50):
        ids = pending[offset:offset + 50]
        page = client.query(GENRES_QUERY, {"ids": ids}).get("Page")
        if not isinstance(page, dict) or not isinstance(page.get("media"), list):
            raise RuntimeError("AniList не вернул Page.media")
        # Запрашиваем не больше 50 ID при perPage=50: вся выборка помещается
        # на страницу. hasNextPage у AniList бывает True даже при возврате
        # всех 50 запрошенных ID, поэтому не используем его как проверку.
        fetched_at = datetime.now(timezone.utc).isoformat()
        batch = {str(i): {"genres": None, "fetched_at": fetched_at} for i in ids}
        seen = set()
        for media in page["media"]:
            if not isinstance(media, dict) or media.get("id") not in ids or media["id"] in seen:
                raise RuntimeError("неожиданный или повторный ID в ответе жанров")
            genres = media.get("genres")
            if not isinstance(genres, list) or any(not isinstance(g, str) or not g for g in genres):
                raise RuntimeError("невалидный список жанров")
            seen.add(media["id"])
            batch[str(media["id"])]["genres"] = sorted(set(genres))
        items.update(batch)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp, path)
        log.info("сохранено %d/%d новых тайтлов; не вернулось в пачке %d",
                 min(offset + 50, len(pending)), len(pending), len(ids) - len(seen))
    return cache


def load_item_genres(path: Path = DEFAULT_GENRES_PATH) -> dict[int, set[str]]:
    """AniList ID → названия жанров; недоступные и пустые жанры пропускаются.

    Названия служат ключами только в офлайн-эксперименте, не являются genre.id БД.
    """
    if not path.exists():
        raise FileNotFoundError(f"сначала загрузите жанры: {path}")
    return {int(i): set(row["genres"]) for i, row in read_cache(path)["items"].items() if row["genres"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="граница train с часовым поясом (не включительно)")
    parser.add_argument("--lists", type=Path, default=DEFAULT_ANILIST_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_GENRES_PATH)
    parser.add_argument("--retry-missing", action="store_true")
    args = parser.parse_args()
    before = pd.Timestamp(args.before)
    if pd.isna(before) or before.tzinfo is None:
        parser.error("--before должен иметь часовой пояс")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    df = load_anilist(args.lists)
    history = df[df.updated_at.isna() | (df.updated_at < before)]
    client = AniListClient()
    try:
        fetch_genres(client, history.anime_id.unique(), args.out, retry_missing=args.retry_missing)
    finally:
        client.http.close()


if __name__ == "__main__":
    main()
