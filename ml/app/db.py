"""Синхронный доступ к общей БД. Схему создают миграции backend."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import make_url


def make_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.drivername in {"postgresql", "postgresql+asyncpg"}:
        url = url.set(drivername="postgresql+psycopg")
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def get_connection(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.connect() as connection:
        yield connection
