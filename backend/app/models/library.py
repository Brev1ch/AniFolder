"""Списки пользователей, оценки, отзывы, лента активности, рекомендации."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, REAL, SmallInteger, String,
    Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.anime import Anime
from app.models.enums import ActivityType, ListStatus, activity_type_type, list_status_type


class UserAnime(Base):
    """Тайтл в списке пользователя. Upsert: INSERT ... ON CONFLICT (user_id, anime_id) DO UPDATE."""

    __tablename__ = "user_anime"
    __table_args__ = (
        CheckConstraint("score BETWEEN 1 AND 10", name="score_range"),
        CheckConstraint("episodes_watched >= 0", name="episodes_nonneg"),
        Index("user_anime_user_status_idx", "user_id", "status", text("updated_at DESC")),
        Index("user_anime_anime_id_idx", "anime_id"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    anime_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[ListStatus] = mapped_column(list_status_type)
    score: Mapped[int | None] = mapped_column(SmallInteger)
    episodes_watched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # обновляется триггером в БД
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    anime: Mapped[Anime] = relationship(lazy="raise")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "anime_id", name="reviews_one_per_anime"),
        CheckConstraint("score BETWEEN 1 AND 10", name="score_range"),
        CheckConstraint("char_length(text) BETWEEN 1 AND 20000", name="text_length"),
        Index("reviews_anime_created_idx", "anime_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    anime_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserActivity(Base):
    """Лента активности. Таблица партиционирована по месяцам, поэтому PK = (id, created_at)."""

    __tablename__ = "user_activity"
    __table_args__ = (
        Index("user_activity_user_created_idx", "user_id", text("created_at DESC")),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[ActivityType] = mapped_column(activity_type_type)
    anime_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Recommendation(Base):
    """Пишет Recommendation Service; backend только читает."""

    __tablename__ = "recommendations"
    __table_args__ = (Index("recommendations_user_relevance_idx", "user_id", text("relevance DESC")),)

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    anime_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"), primary_key=True)
    relevance: Mapped[float] = mapped_column(REAL)
    model_version: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
