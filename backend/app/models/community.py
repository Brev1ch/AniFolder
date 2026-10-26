from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        CheckConstraint("char_length(title) >= 1", name="title_length"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 20000", name="body_length"),
        Index("topics_last_comment_idx", text("last_comment_at DESC")),
        Index("topics_anime_last_comment_idx", "anime_id", text("last_comment_at DESC")),
        Index("topics_author_id_idx", "author_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # NULL — автор удалил аккаунт; тема остаётся
    author_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    # NULL — общая тема, не привязанная к тайтлу
    anime_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("anime.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    # comments_count и last_comment_at ведёт триггер на comments — из приложения не менять
    comments_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_comment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    """Комментарий. Таблица партиционирована по годам, поэтому PK = (id, created_at).

    У parent_id нет FK (на партиционированную таблицу ссылаться можно только по (id, created_at)),
    его проверяет триггер check_comment_parent: родитель должен существовать и быть в той же теме.
    """

    __tablename__ = "comments"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 10000", name="body_length"),
        Index("comments_topic_created_idx", "topic_id", "created_at"),
        Index("comments_author_id_idx", "author_id"),
        Index("comments_id_idx", "id"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True, server_default=func.now())
    topic_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("topics.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    body: Mapped[str] = mapped_column(Text)
