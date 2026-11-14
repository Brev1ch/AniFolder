"""Загрузка взаимодействий «пользователь — тайтл» для обучения.

Источники:
- списки AniList, собранные краулером (parquet в ml/data/anilist/lists);
- таблица user_anime нашей БД.

Все функции возвращают таблицу с колонками INTERACTION_COLUMNS, статусы
в нашем формате (planned/watching/completed/on_hold/dropped).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

log = logging.getLogger(__name__)

DEFAULT_ANILIST_DIR = Path(__file__).resolve().parents[2] / "data" / "anilist" / "lists"

INTERACTION_COLUMNS = ["user_id", "anime_id", "status", "score", "updated_at"]

# REPEATING — пересматривает: тайтл уже просмотрен, для модели это completed
ANILIST_STATUS = {
    "COMPLETED": "completed",
    "REPEATING": "completed",
    "CURRENT": "watching",
    "PLANNING": "planned",
    "PAUSED": "on_hold",
    "DROPPED": "dropped",
}


def make_engine(url: str | None = None) -> Engine:
    """Engine по DATABASE_URL. Бэкенд пишет адрес для asyncpg, мы работаем через psycopg."""
    url = url or os.environ["DATABASE_URL"]
    url = url.replace("+asyncpg", "+psycopg")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url)


def normalize_anilist(raw: pd.DataFrame) -> pd.DataFrame:
    """Сырые строки краулера → наш формат. anime_id здесь ещё id AniList."""
    df = raw.copy()
    df["status"] = df["status"].map(ANILIST_STATUS)
    unknown = df["status"].isna().sum()
    if unknown:
        log.warning("пропущено %d записей с неизвестным статусом AniList", unknown)
        df = df[df["status"].notna()]
    df["updated_at"] = pd.to_datetime(df["updated_at"], unit="s", utc=True)
    return df[INTERACTION_COLUMNS].reset_index(drop=True)


def load_anilist(path: Path = DEFAULT_ANILIST_DIR) -> pd.DataFrame:
    """Данные краулера, anime_id — id AniList (для EDA, пока каталог не заполнен)."""
    return normalize_anilist(pd.read_parquet(path))


def to_catalog_ids(df: pd.DataFrame, anilist_to_anime: pd.Series) -> pd.DataFrame:
    """Переводит id AniList в anime.id нашего каталога, тайтлы вне каталога отбрасывает.

    Пользователи AniList получают отрицательные id, чтобы не совпасть
    с пользователями сайта при объединении источников.
    """
    out = df.copy()
    out["anime_id"] = out["anime_id"].map(anilist_to_anime)
    matched = out["anime_id"].notna()
    log.info("в каталоге нашлось %.1f%% записей AniList", 100 * matched.mean() if len(out) else 0)
    out = out[matched].astype({"anime_id": "int64"})
    out["user_id"] = -out["user_id"]
    return out.reset_index(drop=True)


def load_catalog_mapping(engine: Engine) -> pd.Series:
    """anilist_id → anime.id."""
    with engine.connect() as conn:
        rows = pd.read_sql(text("SELECT id, anilist_id FROM anime"), conn)
    return rows.set_index("anilist_id")["id"]


def load_site(engine: Engine) -> pd.DataFrame:
    """Списки пользователей нашего сайта из user_anime."""
    query = text("SELECT user_id, anime_id, status::text AS status, score, updated_at FROM user_anime")
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df.astype({"user_id": "int64", "anime_id": "int64", "score": "Int8"})[INTERACTION_COLUMNS]


def filter_interactions(df: pd.DataFrame, min_user_items: int = 5, min_item_users: int = 5) -> pd.DataFrame:
    """Убирает пользователей с малым числом тайтлов и тайтлы с малым числом пользователей.

    Повторяет, пока таблица меняется: после удаления редких тайтлов у кого-то
    из пользователей может стать меньше min_user_items, и наоборот.
    """
    while True:
        item_counts = df["anime_id"].map(df["anime_id"].value_counts())
        user_counts = df["user_id"].map(df["user_id"].value_counts())
        keep = (item_counts >= min_item_users) & (user_counts >= min_user_items)
        if keep.all():
            return df.reset_index(drop=True)
        df = df[keep]


def load_interactions(
    engine: Engine,
    anilist_path: Path | None = DEFAULT_ANILIST_DIR,
) -> pd.DataFrame:
    """Полная история сайта + AniList в id каталога, без фильтра редких записей.

    Используется для холодного старта и исключения уже добавленных тайтлов.
    Для офлайн-проверки сначала разделите эту историю по времени: тестовые
    записи не должны попадать ни в обучение, ни в историю рекомендателя.
    """
    parts = [load_site(engine)]
    if anilist_path is not None and Path(anilist_path).exists():
        parts.append(to_catalog_ids(load_anilist(anilist_path), load_catalog_mapping(engine)))
    return pd.concat(parts, ignore_index=True)


def load_training_data(
    engine: Engine,
    anilist_path: Path | None = DEFAULT_ANILIST_DIR,
    min_user_items: int = 5,
    min_item_users: int = 5,
) -> pd.DataFrame:
    """Фильтрованные данные для обучения; не использовать как полную историю.

    Для cold start и seen используйте load_interactions. При оценке качества
    фильтруйте train после временного разбиения, а не результат этой функции.
    """
    df = load_interactions(engine, anilist_path)
    return filter_interactions(df, min_user_items, min_item_users)
