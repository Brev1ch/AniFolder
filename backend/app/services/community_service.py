"""Сообщество: темы и комментарии.

Счётчики темы (comments_count, last_comment_at) ведёт триггер update_topic_counters
на comments — из приложения не меняются. Родитель комментария проверяет триггер
check_comment_parent: нарушение приходит как foreign_key_violation и превращается
в 422. События ленты активности (topic_created, commented) пишутся той же транзакцией.
"""

import logging

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import errors
from app.models.anime import Anime
from app.models.community import Comment, Topic
from app.models.enums import ActivityType
from app.models.library import UserActivity
from app.models.user import User
from app.schemas.community import (
    DELETED_USERNAME,
    CommentCreate,
    CommentFeedResponse,
    CommentResponse,
    TopicCreate,
    TopicListResponse,
    TopicResponse,
)
from app.services.cursor import decode_cursor, encode_cursor

logger = logging.getLogger(__name__)


async def _get_topic(session: AsyncSession, topic_id: int) -> Topic:
    topic = await session.get(Topic, topic_id)
    if topic is None:
        raise errors.AppError(404, errors.TOPIC_NOT_FOUND, f"Тема с id={topic_id} не найдена")
    return topic


async def list_topics(
    session: AsyncSession, anime_id: int | None, page: int, limit: int
) -> TopicListResponse:
    """Темы по last_comment_at DESC: с фильтром по тайтлу и без. Индексы под оба варианта."""
    filters = []
    if anime_id is not None:
        filters.append(Topic.anime_id == anime_id)

    total = await session.scalar(select(func.count()).select_from(Topic).where(*filters))
    rows = (await session.execute(
        select(Topic, User.username)
        .join(User, User.id == Topic.author_id, isouter=True)
        .where(*filters)
        .order_by(Topic.last_comment_at.desc(), Topic.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )).all()

    items = [
        TopicResponse(
            id=topic.id, author_id=topic.author_id,
            username=username if topic.author_id is not None else DELETED_USERNAME,
            anime_id=topic.anime_id, title=topic.title, body=topic.body,
            comments_count=topic.comments_count,
            created_at=topic.created_at, last_comment_at=topic.last_comment_at,
        )
        for topic, username in rows
    ]
    return TopicListResponse(items=items, total=total or 0, page=page, limit=limit)


async def create_topic(session: AsyncSession, user: User, body: TopicCreate) -> TopicResponse:
    if body.anime_id is not None:
        anime_exists = await session.scalar(select(Anime.id).where(Anime.id == body.anime_id))
        if anime_exists is None:
            raise errors.AppError(404, errors.ANIME_NOT_FOUND, f"Аниме с id={body.anime_id} не найдено")

    topic = Topic(author_id=user.id, anime_id=body.anime_id, title=body.title, body=body.body)
    session.add(topic)
    await session.flush()
    session.add(UserActivity(
        user_id=user.id, anime_id=body.anime_id,
        type=ActivityType.TOPIC_CREATED, payload={"topic_id": topic.id},
    ))
    await session.commit()

    return TopicResponse(
        id=topic.id, author_id=user.id, username=user.username,
        anime_id=topic.anime_id, title=topic.title, body=topic.body,
        comments_count=topic.comments_count,
        created_at=topic.created_at, last_comment_at=topic.last_comment_at,
    )


async def list_comments(
    session: AsyncSession, topic_id: int, cursor: str | None, limit: int
) -> CommentFeedResponse:
    """Комментарии темы, новые первыми. Курсор — по (created_at, id), как у ленты активности."""
    await _get_topic(session, topic_id)

    stmt = select(Comment).where(Comment.topic_id == topic_id)
    if cursor is not None:
        cursor_created, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            # Скалярная граница позволяет planner исключить будущие партиции.
            # Равные timestamp не отсекаем: их разделяет id в tuple-условии.
            Comment.created_at <= cursor_created,
            tuple_(Comment.created_at, Comment.id) < (cursor_created, cursor_id),
        )
    rows = list((await session.scalars(
        stmt.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1)
    )).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)

    usernames = {}
    author_ids = {row.author_id for row in rows if row.author_id is not None}
    if author_ids:
        usernames = dict((await session.execute(
            select(User.id, User.username).where(User.id.in_(author_ids))
        )).all())

    items = [
        CommentResponse(
            id=row.id, topic_id=row.topic_id, author_id=row.author_id,
            username=usernames.get(row.author_id) if row.author_id is not None else DELETED_USERNAME,
            parent_id=row.parent_id,
            body=row.body, created_at=row.created_at,
        )
        for row in rows
    ]
    return CommentFeedResponse(items=items, next_cursor=next_cursor)


async def create_comment(
    session: AsyncSession, user: User, topic_id: int, body: CommentCreate
) -> CommentResponse:
    topic = await _get_topic(session, topic_id)

    comment = Comment(
        topic_id=topic_id, author_id=user.id, parent_id=body.parent_id, body=body.body
    )
    session.add(comment)
    try:
        await session.flush()
    except IntegrityError:
        # check_comment_parent: родителя нет или он из другой темы.
        # Откатываем транзакцию (в тестах — до savepoint), чтобы сессия осталась рабочей.
        await session.rollback()
        raise errors.AppError(
            422, errors.VALIDATION_ERROR,
            f"Родительский комментарий {body.parent_id} не найден в теме {topic_id}",
        ) from None

    session.add(UserActivity(
        user_id=user.id, anime_id=topic.anime_id,
        type=ActivityType.COMMENTED,
        payload={"topic_id": topic_id, "comment_id": comment.id},
    ))
    await session.commit()

    return CommentResponse(
        id=comment.id, topic_id=topic_id, author_id=user.id, username=user.username,
        parent_id=comment.parent_id, body=comment.body, created_at=comment.created_at,
    )
