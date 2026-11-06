"""Пароли (bcrypt) и токены (JWT access + случайный refresh с хранением SHA-256)."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core import errors
from app.core.config import settings

# access-токен: тип зашит в payload, чтобы refresh нельзя было подсунуть в защищённый роут
_TOKEN_TYPE_ACCESS = "access"


def hash_password(password: str) -> str:
    """bcrypt-хэш пароля. bcrypt использует максимум 72 байта — длину пароля валидирует схема."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Проверка пароля против хэша; битый хэш считаем несовпадением."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    """JWT с sub=str(user_id) и TTL из настроек (по умолчанию 15 минут)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": _TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """Валидация access-токена; возвращает id пользователя или бросает AppError(401)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise errors.AppError(401, errors.TOKEN_EXPIRED, "Срок действия токена истёк")
    except jwt.InvalidTokenError:
        raise errors.AppError(401, errors.INVALID_TOKEN, "Невалидный токен")

    if payload.get("type") != _TOKEN_TYPE_ACCESS:
        raise errors.AppError(401, errors.INVALID_TOKEN, "Невалидный тип токена")
    try:
        return int(payload["sub"])
    except (TypeError, ValueError):
        raise errors.AppError(401, errors.INVALID_TOKEN, "Невалидный токен")


def generate_refresh_token() -> tuple[str, str]:
    """Новый refresh-токен; возвращает (токен, sha256_hex). Сам токен в БД не пишем."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> str:
    """SHA-256 в hex — то, что хранится в refresh_tokens.token_hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
