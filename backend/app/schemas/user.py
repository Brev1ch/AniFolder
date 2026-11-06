"""Схемы auth-эндпоинтов: запросы регистрации/входа/обновления и ответ с парой токенов."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Совпадает с CHECK users_username_format в БД: латиница, цифры и подчёркивание, 3–32 символа
USERNAME_PATTERN = r"^[A-Za-z0-9_]{3,32}$"

# bcrypt молча обрезает пароль после 72 байт — ограничиваем схемой, чтобы не было сюрпризов
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 72


class UserRegisterRequest(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserResponse(BaseModel):
    """Публичное представление пользователя в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr


class AuthResponse(BaseModel):
    """Пара токенов + пользователь. Формат зеркалит frontend/src/api/auth.ts."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse
