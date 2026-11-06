"""Регистрация, вход и обновление токенов: ротация refresh с детектом повторного использования."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import errors
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.schemas.user import AuthResponse, UserResponse

logger = logging.getLogger(__name__)


async def register(session: AsyncSession, username: str, email: str, password: str) -> AuthResponse:
    """Регистрация: уникальность username/email без учёта регистра, затем выдача пары токенов."""
    await _ensure_credentials_free(session, username, email)
    user = User(username=username, email=email, password_hash=hash_password(password))
    session.add(user)
    try:
        # flush, а не commit: токены добавим в ту же транзакцию
        await session.flush()
    except IntegrityError:
        # Гонка: запись появилась между проверкой и вставкой. Откатываемся и повторная
        # проверка скажет, какое именно поле занято, — вместо разбора текста ошибки БД.
        await session.rollback()
        await _ensure_credentials_free(session, username, email)
        raise
    return await _issue_tokens(session, user)


# bcrypt-хэш заведомо чужого пароля: вычисляется один раз при импорте. Когда пользователь
# не найден, verify всё равно выполняется против этой строки — по времени ответа нельзя
# отличить «нет такого логина» от «неверный пароль» (timing attack).
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing")


async def login(session: AsyncSession, username: str, password: str) -> AuthResponse:
    """Вход по логину и паролю. Единый текст ошибки, чтобы не подсвечивать существующие логины."""
    user = await _get_user_by_username(session, username)
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    if not verify_password(password, password_hash) or user is None:
        raise errors.AppError(401, errors.INVALID_CREDENTIALS, "Неверный логин или пароль")
    return await _issue_tokens(session, user)


async def refresh(session: AsyncSession, refresh_token: str) -> AuthResponse:
    """Ротация refresh-токена: старый отзывается, выдаётся новая пара.

    Повторное использование отозванного токена (в т.ч. гонка двух запросов с одним
    токеном) отзывает все токены пользователя — признак компрометации.
    """
    token_hash = hash_refresh_token(refresh_token)
    row = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    if row is None:
        raise errors.AppError(401, errors.INVALID_REFRESH_TOKEN, "Невалидный refresh-токен")

    user_id = row.user_id
    expires_at = row.expires_at

    if row.revoked:
        await _revoke_family(session, user_id)
        await session.commit()
        logger.warning("Повторное использование отозванного refresh-токена: user_id=%s", user_id)
        raise errors.AppError(401, errors.REFRESH_TOKEN_REUSED, "Токен уже использован, все сессии отозваны")

    if expires_at <= datetime.now(timezone.utc):
        raise errors.AppError(401, errors.REFRESH_TOKEN_EXPIRED, "Срок действия refresh-токена истёк")

    user = await session.get(User, user_id)
    if user is None:
        raise errors.AppError(401, errors.INVALID_REFRESH_TOKEN, "Невалидный refresh-токен")

    # Ротация под защитой от гонки: если revoked=false уже нет — кто-то обновил пару
    # по этому токену раньше, значит токен переиспользуется — отзываем всю семью.
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == row.id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    if result.rowcount != 1:
        await session.rollback()
        await _revoke_family(session, user_id)
        await session.commit()
        logger.warning("Гонка refresh-токенов: user_id=%s", user_id)
        raise errors.AppError(401, errors.REFRESH_TOKEN_REUSED, "Токен уже использован, все сессии отозваны")

    new_refresh_token, new_record = _build_refresh_token(user_id)
    session.add(new_record)
    await session.commit()
    return AuthResponse(
        access_token=create_access_token(user.id),
        refresh_token=new_refresh_token,
        user=UserResponse.model_validate(user),
    )


async def _ensure_credentials_free(session: AsyncSession, username: str, email: str) -> None:
    """Проверка занятости через lower(...): иначе unique-индекс users_username_lower_key не используется."""
    username_taken = await session.scalar(
        select(exists().where(func.lower(User.username) == username.lower()))
    )
    if username_taken:
        raise errors.AppError(409, errors.USERNAME_TAKEN, "Имя пользователя уже занято")
    email_taken = await session.scalar(
        select(exists().where(func.lower(User.email) == email.lower()))
    )
    if email_taken:
        raise errors.AppError(409, errors.EMAIL_TAKEN, "Email уже зарегистрирован")


async def _get_user_by_username(session: AsyncSession, username: str) -> User | None:
    """Поиск без учёта регистра — по индексу lower(username)."""
    return await session.scalar(
        select(User).where(func.lower(User.username) == username.lower())
    )


async def _issue_tokens(session: AsyncSession, user: User) -> AuthResponse:
    """Создаёт запись refresh-токена и коммитит транзакцию, возвращает пару токенов."""
    refresh_token, record = _build_refresh_token(user.id)
    session.add(record)
    await session.commit()
    return AuthResponse(
        access_token=create_access_token(user.id),
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


def _build_refresh_token(user_id: int) -> tuple[str, RefreshToken]:
    """Новый refresh-токен и его запись для БД (SHA-256 хэш, TTL из настроек)."""
    token, token_hash = generate_refresh_token()
    record = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl),
    )
    return token, record


async def _revoke_family(session: AsyncSession, user_id: int) -> None:
    """Отзыв всех refresh-токенов пользователя — при компрометации одного из них."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
