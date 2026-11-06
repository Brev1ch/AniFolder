"""Эндпоинты авторизации: POST /auth/register, /auth/login, /auth/refresh."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.user import AuthResponse, RefreshRequest, UserLoginRequest, UserRegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """Регистрация по username/email/password; сразу выдаёт пару токенов."""
    return await auth_service.register(session, body.username, body.email, body.password)


@router.post("/login", response_model=AuthResponse)
async def login(
    body: UserLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """Вход по username и паролю; выдача пары токенов."""
    return await auth_service.login(session, body.username, body.password)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """Обмен refresh-токена на новую пару; старый токен отзывается."""
    return await auth_service.refresh(session, body.refresh_token)
