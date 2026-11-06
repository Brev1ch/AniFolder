"""In-memory rate limiting: скользящее окно по IP для чувствительных эндпоинтов.

Подходит для одного-двух инстансов API. При горизонтальном масштабировании
переносим счётчики в Redis (app.state.redis уже подключён в lifespan).

За reverse proxy request.client.host будет адресом nginx — тогда клиентский IP
нужно брать из X-Forwarded-For на уровне прокси (заголовок извне не доверяем).
"""

import asyncio
import json
import time
from collections import defaultdict, deque

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import RATE_LIMITED, error_body

# Путь -> (максимум запросов, окно в секундах)
LIMITS: dict[str, tuple[int, float]] = {
    "/api/v1/auth/login": (5, 60.0),
    "/api/v1/auth/register": (3, 60.0),
}


class RateLimitMiddleware:
    """Чистый ASGI-middleware: 429, если с одного IP пришло больше лимита за окно."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # (путь, ip) -> времена обращений; asyncio single-thread, лок на всякий случай
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        rule = LIMITS.get(path)
        if rule is None:
            await self.app(scope, receive, send)
            return

        limit, window = rule
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        key = (path, ip)
        now = time.monotonic()

        async with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                await self._reject(scope, receive, send, window)
                return
            hits.append(now)
            if not hits:
                del self._hits[key]

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, window: float) -> None:
        body = error_body(RATE_LIMITED, "Слишком много запросов, попробуйте позже")
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"retry-after", str(int(window)).encode("ascii")),
        ]
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": payload})
