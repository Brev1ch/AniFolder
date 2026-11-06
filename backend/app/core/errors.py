"""Единый формат ошибок API: {"error": {"code": ..., "message": ...}} (см. README)."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Доменная ошибка API: клиенту уходит status_code и код из перечисления ниже."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


# --- Коды ошибок ---
VALIDATION_ERROR = "VALIDATION_ERROR"
USERNAME_TAKEN = "USERNAME_TAKEN"
EMAIL_TAKEN = "EMAIL_TAKEN"
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
INVALID_TOKEN = "INVALID_TOKEN"
INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"
REFRESH_TOKEN_EXPIRED = "REFRESH_TOKEN_EXPIRED"
REFRESH_TOKEN_REUSED = "REFRESH_TOKEN_REUSED"
RATE_LIMITED = "RATE_LIMITED"
INTERNAL_ERROR = "INTERNAL_ERROR"


def error_body(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    """Тело ответа с ошибкой; details — опциональные детали (например, ошибки полей)."""
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Только type/loc/msg: значения полей (input) не возвращаем — там бывают пароли
    details = [
        {"type": e["type"], "loc": e["loc"], "msg": e["msg"]} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_body(VALIDATION_ERROR, "Ошибка валидации данных", details=details),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Необработанная ошибка при %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body(INTERNAL_ERROR, "Внутренняя ошибка сервера"),
    )


def register_error_handlers(app: FastAPI) -> None:
    """Вешает обработчики на приложение; AppError — в первую очередь."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
