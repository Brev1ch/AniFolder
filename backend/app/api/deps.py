"""Общие FastAPI-зависимости."""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import errors
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User

# auto_error=False: без заголовка Authorization бросим свой AppError,
# а не стандартный 403 от FastAPI
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Защищённые роутеры получают текущего пользователя из Bearer access-токена."""
    if credentials is None:
        raise errors.AppError(401, errors.AUTHENTICATION_REQUIRED, "Требуется авторизация")
    user_id = decode_access_token(credentials.credentials)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise errors.AppError(401, errors.INVALID_TOKEN, "Пользователь не найден")
    return user
