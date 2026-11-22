"""Схемы отзывов, тем и комментариев (контракт — docs/api.md «Отзывы и сообщество»)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Автор удалил аккаунт: его отзывы/темы/комментарии остаются, в username приходит
# этот маркер (user_id — null). Решение тимлида, контракт docs/api.md.
DELETED_USERNAME = "deleted_user"


class ReviewCreate(BaseModel):
    """Тело POST /anime/{id}/reviews. Один отзыв на тайтл на пользователя (409 при повторе)."""

    score: int = Field(ge=1, le=10)
    text: str = Field(min_length=1, max_length=20000)


class ReviewPatch(BaseModel):
    """Тело PATCH /reviews/{id}: меняются только переданные поля (явный null — 422)."""

    score: int | None = Field(default=None, ge=1, le=10)
    text: str | None = Field(default=None, min_length=1, max_length=20000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None  # null — автор удалил аккаунт
    username: str | None
    score: int
    text: str
    created_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    total: int
    page: int
    limit: int


class TopicCreate(BaseModel):
    """Тело POST /topics. anime_id опционален: общая тема не привязана к тайтлу."""

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    anime_id: int | None = None


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_id: int | None
    username: str | None
    anime_id: int | None
    title: str
    body: str
    comments_count: int  # ведёт триггер на comments, приложение не меняет
    created_at: datetime
    last_comment_at: datetime


class TopicListResponse(BaseModel):
    items: list[TopicResponse]
    total: int
    page: int
    limit: int


class CommentCreate(BaseModel):
    """Тело POST /topics/{id}/comments. parent_id — комментарий той же темы (проверяет БД)."""

    body: str = Field(min_length=1, max_length=10000)
    parent_id: int | None = None


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic_id: int
    author_id: int | None
    username: str | None
    parent_id: int | None
    body: str
    created_at: datetime


class CommentFeedResponse(BaseModel):
    """Курсорная выдача комментариев: новые первыми; next_cursor = null в конце."""

    items: list[CommentResponse]
    next_cursor: str | None
