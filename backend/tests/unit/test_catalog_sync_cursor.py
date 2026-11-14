"""Регрессионные тесты управления курсором catalog_sync (ревью N1/N2, PR #8).

Сеть, Redis и БД подменены фейками: проверяем только протокол курсора —
новый watermark сохраняется после доказанно полного обхода и не
сохраняется при ошибке импорта, остановке по --max-pages или ошибках GraphQL.
"""

import pytest

from app.workers import catalog_sync as worker


def _payload(updated_at: int, *, has_next: bool, media_id: int = 1) -> dict:
    return {
        "data": {
            "Page": {
                "media": [{"id": media_id, "updatedAt": updated_at}],
                "pageInfo": {"hasNextPage": has_next},
            }
        }
    }


@pytest.fixture
def fakes(monkeypatch):
    """Фейковый контур worker'а; возвращает (state, client) для настройки страниц."""
    state = {"saved": [], "cursor": "100", "calls": []}

    class FakeRedis:
        async def ping(self) -> None:
            return None

        async def get(self, key: str):
            return state["cursor"]

        async def set(self, key: str, value) -> None:
            state["saved"].append(int(value))

        async def close(self, **kwargs) -> None:
            return None

    redis = FakeRedis()

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            return None

    class FakeClient:
        def __init__(self) -> None:
            self.pages: dict = {}
            self.fail_media_ids: set[int] = set()

        async def fetch_page(self, page: int, updated_at_greater):
            state["calls"].append((page, updated_at_greater))
            payload = self.pages[page]
            if isinstance(payload, Exception):
                raise payload
            return payload

        async def close(self) -> None:
            return None

    client = FakeClient()

    async def fake_apply(session, medias):
        hit = client.fail_media_ids & {m["id"] for m in medias}
        if hit:
            raise RuntimeError("simulated import failure")
        return len(medias)

    redis_stub = type("RedisStub", (), {"from_url": staticmethod(lambda *a, **k: redis)})
    monkeypatch.setattr(worker, "Redis", redis_stub)
    monkeypatch.setattr(worker, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(worker, "AniListClient", lambda: client)
    monkeypatch.setattr(worker, "apply_media_batch", fake_apply)
    return state, client


async def test_cursor_saved_after_full_pass(fakes) -> None:
    state, client = fakes
    # страницы отсортированы по ID: max(updatedAt) успешного префикса (300)
    # больше updatedAt последней страницы (200) — курсор корректен только
    # потому, что обе страницы обработаны
    client.pages = {
        1: _payload(300, has_next=True, media_id=1),
        2: _payload(200, has_next=False, media_id=2),
    }
    total = await worker.run()
    assert total == 2
    assert state["saved"] == [300]


async def test_cursor_kept_after_failed_page(fakes) -> None:
    state, client = fakes
    client.pages = {
        1: _payload(300, has_next=True, media_id=1),
        2: _payload(200, has_next=False, media_id=2),
    }
    client.fail_media_ids = {2}

    with pytest.raises(RuntimeError, match="simulated import failure"):
        await worker.run()
    # страница 1 применена, но запись 200 не обработана: курсор 100 остаётся,
    # следующий прогон дочитает обе
    assert state["saved"] == []


async def test_cursor_kept_after_max_pages_stop(fakes) -> None:
    state, client = fakes
    client.pages = {
        1: _payload(300, has_next=True, media_id=1),
        2: _payload(200, has_next=False, media_id=2),
    }
    total = await worker.run(max_pages=1)
    assert total == 1
    assert state["saved"] == []


async def test_graphql_errors_are_not_an_empty_page(fakes) -> None:
    state, client = fakes
    client.pages = {1: {"errors": [{"message": "Internal error"}]}}

    with pytest.raises(RuntimeError, match="ошибки GraphQL"):
        await worker.run()
    assert state["saved"] == []


async def test_incremental_run_overlaps_cursor_by_one_second(fakes) -> None:
    state, client = fakes
    client.pages = {1: _payload(200, has_next=False, media_id=1)}

    await worker.run()
    # строгое сравнение в AniList: первый запрос идёт с updatedAt > 99
    assert state["calls"][0] == (1, 99)
    assert state["saved"] == [200]
