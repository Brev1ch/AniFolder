"""Сообщество: темы (GET/POST /topics) и комментарии (GET/POST /topics/{id}/comments)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.community import (
    CommentCreate,
    CommentFeedResponse,
    CommentResponse,
    TopicCreate,
    TopicListResponse,
    TopicResponse,
)
from app.services import community_service

router = APIRouter(tags=["community"])


@router.get("/topics", response_model=TopicListResponse)
async def get_topics(
    anime_id: Annotated[int | None, Query(ge=1)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    session: AsyncSession = Depends(get_session),
) -> TopicListResponse:
    """Темы сообщества, свежие комментарии первыми; anime_id — опциональный фильтр."""
    return await community_service.list_topics(session, anime_id, page, limit)


@router.post("/topics", response_model=TopicResponse, status_code=201)
async def post_topic(
    body: TopicCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TopicResponse:
    """Создать тему; без anime_id — общая, не привязанная к тайтлу."""
    return await community_service.create_topic(session, user, body)


@router.get("/topics/{topic_id}/comments", response_model=CommentFeedResponse)
async def get_comments(
    topic_id: Annotated[int, Path(ge=1)],
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
    session: AsyncSession = Depends(get_session),
) -> CommentFeedResponse:
    """Комментарии темы от старых к новым, курсорная пагинация."""
    return await community_service.list_comments(session, topic_id, cursor, limit)


@router.post("/topics/{topic_id}/comments", response_model=CommentResponse, status_code=201)
async def post_comment(
    body: CommentCreate,
    topic_id: Annotated[int, Path(ge=1)],
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CommentResponse:
    """Написать комментарий; parent_id — ответ на комментарий той же темы."""
    return await community_service.create_comment(session, user, topic_id, body)
