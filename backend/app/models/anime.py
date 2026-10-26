from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Identity, Index, Integer, Numeric,
    String, Table, Text, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

anime_genres = Table(
    "anime_genres",
    Base.metadata,
    Column("anime_id", BigInteger, ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True),
    Column("genre_id", Integer, ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True),
    Index("anime_genres_genre_id_idx", "genre_id", "anime_id"),
)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    # Естественный ключ: английские названия жанров в MAL и AniList совпадают.
    # Синхронизация делает upsert по name_en и не трогает name_ru.
    name_en: Mapped[str] = mapped_column(String(64), unique=True)
    # NULL, пока перевода нет — показывать name_en
    name_ru: Mapped[str | None] = mapped_column(String(64))


class Anime(Base):
    __tablename__ = "anime"
    __table_args__ = (
        CheckConstraint("mal_id IS NOT NULL OR anilist_id IS NOT NULL", name="external_id_present"),
        CheckConstraint("status IN ('announced', 'ongoing', 'released', 'hiatus', 'cancelled')", name="status_valid"),
        CheckConstraint("episodes >= 0", name="episodes_nonneg"),
        # Нечёткий поиск: title_ru ILIKE '%...%' или title_ru % 'запрос' (оператор pg_trgm)
        Index("anime_title_ru_trgm_idx", "title_ru", postgresql_using="gin",
              postgresql_ops={"title_ru": "gin_trgm_ops"}),
        Index("anime_title_en_trgm_idx", "title_en", postgresql_using="gin",
              postgresql_ops={"title_en": "gin_trgm_ops"}),
        Index("anime_kind_aired_on_idx", "kind", "aired_on"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # Внешние id: хотя бы один задан. mal_id нужен ML (датасеты размечены по MAL id);
    # у части тайтлов AniList его нет, поэтому поле необязательное.
    mal_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    anilist_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    # В MAL и AniList русских названий нет
    title_ru: Mapped[str | None] = mapped_column(String(512))
    title_en: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    episodes: Mapped[int | None] = mapped_column(Integer)
    aired_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    poster_url: Mapped[str | None] = mapped_column(String(512))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # lazy="raise": в async нельзя подгружать связи неявно — используйте selectinload(Anime.genres)
    genres: Mapped[list[Genre]] = relationship(secondary=anime_genres, lazy="raise")
    stats: Mapped["AnimeStats | None"] = relationship(lazy="raise", uselist=False)


class AnimeStats(Base):
    """Агрегаты по тайтлу. Пишет только refresh_anime_stats() в БД — из приложения не изменять."""

    __tablename__ = "anime_stats"

    anime_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True)
    scores_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    avg_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    in_lists_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnimeStatsDirty(Base):
    """Очередь тайтлов на пересчёт статистики. Заполняется триггером на user_anime."""

    __tablename__ = "anime_stats_dirty"

    anime_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
