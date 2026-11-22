"""Отзывы удалённых пользователей сохраняются: reviews.user_id NULL + SET NULL.

Как topics.author_id и comments.author_id: контент сообщества остаётся, автор
помечается NULL, API показывает его как deleted_user. До 0002 отзывы удалялись
каскадом вместе с пользователем.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op
from sqlalchemy.util import await_only

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def _run_sql_file(name: str) -> None:
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    bind = op.get_bind()
    raw = bind.connection.driver_connection
    if bind.dialect.is_async:
        await_only(raw.execute(sql))
    else:
        with raw.cursor() as cur:
            cur.execute(sql)


def upgrade() -> None:
    _run_sql_file("0002_reviews_author_set_null.up.sql")


def downgrade() -> None:
    _run_sql_file("0002_reviews_author_set_null.down.sql")
