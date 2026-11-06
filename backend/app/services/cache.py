"""Redis-кэш каталога. Redis необязателен: при недоступности API работает без кэша."""

import json
import logging
from typing import Any

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


async def get_redis(request: Request) -> Redis | None:
    """Зависимость: клиент Redis из lifespan; None, если Redis не поднят (в т.ч. в тестах)."""
    return getattr(request.app.state, "redis", None)


async def cache_get_json(redis: Redis | None, key: str) -> Any | None:
    """GET + JSON-decode; любая ошибка Redis трактуется как промах кэша."""
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
    except RedisError:
        logger.warning("Redis недоступен при чтении ключа %s", key)
        return None
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set_json(redis: Redis | None, key: str, value: Any, ttl: int) -> None:
    """SET с TTL; ошибки Redis не роняют запрос — просто живём без кэша."""
    if redis is None:
        return
    try:
        await redis.set(key, json.dumps(value, ensure_ascii=False, default=str), ex=ttl)
    except RedisError:
        logger.warning("Redis недоступен при записи ключа %s", key)
