"""Все модели импортируются здесь, чтобы Base.metadata знал о каждой таблице (нужно для Alembic)."""

from app.models.anime import Anime, AnimeStats, AnimeStatsDirty, Genre, anime_genres
from app.models.community import Comment, Topic
from app.models.enums import ActivityType, ListStatus
from app.models.library import Recommendation, Review, UserActivity, UserAnime
from app.models.user import RefreshToken, User

__all__ = [
    "ActivityType",
    "Anime",
    "AnimeStats",
    "AnimeStatsDirty",
    "Comment",
    "Genre",
    "ListStatus",
    "Recommendation",
    "RefreshToken",
    "Review",
    "Topic",
    "User",
    "UserActivity",
    "UserAnime",
    "anime_genres",
]
