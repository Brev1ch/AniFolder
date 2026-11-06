"""Тестовый контекст API: клиент, сессия и приложение одного теста.

Отдельный модуль, чтобы тесты не импортировали conftest повторно (pytest уже
загружает его как модуль conftest — двойной импорт дал бы вторую копию класса).
"""

from dataclasses import dataclass

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ApiTestContext:
    """Клиент и сессия одного теста: сессия живёт во внешней транзакции и видит всё."""

    client: AsyncClient
    session: AsyncSession
    app: FastAPI
