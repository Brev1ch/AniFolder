"""Фоновые задачи API-процесса на чистом asyncio (без Celery).

Периодические функции из docs/database.md:
- refresh_anime_stats() раз в 10 минут — пересчёт агрегатов тайтлов;
- ensure_partitions() раз в сутки — партиции user_activity/comments вперёд;
плюс гигиена: удаление протухших refresh-токенов.

Все функции идемпотентны — при запуске нескольких инстансов API вред не критичен,
но штатно scheduler живёт в одном экземпляре (пока инстанс один).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

STATS_INTERVAL = 600.0          # 10 минут
PARTITIONS_INTERVAL = 86_400.0  # сутки
TOKENS_INTERVAL = 86_400.0      # сутки
STARTUP_DELAY = 60.0            # не долбим БД сразу после старта


async def _run_periodic(
    name: str,
    interval: float,
    job: Callable[[], Awaitable[None]],
) -> None:
    """Цикл: пауза → job → пауза. Исключения job не роняют цикл, а логируются."""
    await asyncio.sleep(STARTUP_DELAY)
    while True:
        try:
            await job()
        except Exception:
            logger.exception("Фоновая задача %s завершилась с ошибкой", name)
        await asyncio.sleep(interval)


async def _refresh_anime_stats() -> None:
    async with SessionLocal() as session:
        await session.execute(text("SELECT refresh_anime_stats()"))
        await session.commit()
    logger.info("refresh_anime_stats() выполнен")


async def _ensure_partitions() -> None:
    async with SessionLocal() as session:
        await session.execute(text("SELECT ensure_partitions()"))
        await session.commit()
    logger.info("ensure_partitions() выполнен")


async def _cleanup_refresh_tokens() -> None:
    """Мёртвые токены не нужны: протухшие и отозванные старше суток удаляем."""
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "DELETE FROM refresh_tokens "
                "WHERE expires_at < now() - interval '1 day' "
                "   OR (revoked AND created_at < now() - interval '1 day')"
            )
        )
        await session.commit()
    logger.info("refresh_tokens очищены, удалено строк: %s", result.rowcount)


async def start() -> asyncio.Task[None]:
    """Запускает фоновые циклы; возвращает объединённую задачу для отмены в shutdown."""
    tasks = [
        asyncio.create_task(_run_periodic("refresh_anime_stats", STATS_INTERVAL, _refresh_anime_stats)),
        asyncio.create_task(_run_periodic("ensure_partitions", PARTITIONS_INTERVAL, _ensure_partitions)),
        asyncio.create_task(_run_periodic("cleanup_refresh_tokens", TOKENS_INTERVAL, _cleanup_refresh_tokens)),
    ]

    async def _gather() -> None:
        await asyncio.gather(*tasks)

    return asyncio.create_task(_gather())
