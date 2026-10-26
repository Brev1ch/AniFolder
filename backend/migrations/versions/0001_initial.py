"""Начальная схема: пользователи, каталог, списки, отзывы, сообщество, рекомендации.

Схема описана в migrations/sql/0001_initial.up.sql: партиционирование, триггеры и функции
удобнее и надёжнее писать на SQL, чем через op.create_table.

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _run_sql_file(name: str) -> None:
    """Выполняет SQL-файл из нескольких команд внутри текущей транзакции миграции."""
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    bind = op.get_bind()
    raw = bind.connection.driver_connection  # соединение самого драйвера, в той же транзакции
    # Через SQLAlchemy файл не выполнить: asyncpg отправляет запросы как prepared statements
    # (в них нельзя несколько команд), а psycopg принимает '%' за плейсхолдер.
    # execute() самого драйвера без параметров выполняет текст как есть.
    if bind.dialect.is_async:  # env.py использует async-движок (asyncpg или psycopg async)
        await_only(raw.execute(sql))
    else:
        with raw.cursor() as cur:
            cur.execute(sql)


def upgrade() -> None:
    _run_sql_file("0001_initial.up.sql")


def downgrade() -> None:
    _run_sql_file("0001_initial.down.sql")
