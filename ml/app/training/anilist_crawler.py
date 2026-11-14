"""Краулер публичных списков аниме пользователей AniList.

Собирает обучающие данные для рекомендательной модели: кто какие тайтлы
добавил в список, с каким статусом и оценкой. Пользователей находит по ленте
свежих активностей ANIME_LIST (так попадаются живые аккаунты с непустыми
списками), затем для каждого запрашивает MediaListCollection.

Сохраняет только числовые id, имена пользователей не храним.
Работу можно прервать и продолжить: прогресс лежит в state.json.

Запуск из папки ml/:
    .venv/bin/python -m app.training.anilist_crawler --users 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger("anilist_crawler")

API_URL = "https://graphql.anilist.co"
USER_AGENT = "AniFolder-ML/0.1 (course project recommender)"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "anilist"

# Листаем по времени, а не по номеру страницы: AniList не отдаёт страницы глубже
# 5000 записей («Page depth exceeds maximum allowed»), поэтому всегда берём
# первую страницу активностей, созданных раньше самой старой из уже увиденных.
ACTIVITIES_QUERY = """
query ($before: Int) {
  Page(page: 1, perPage: 50) {
    activities(type: ANIME_LIST, sort: ID_DESC, createdAt_lesser: $before) {
      ... on ListActivity { userId createdAt }
    }
  }
}
"""

LIST_QUERY = """
query ($userId: Int) {
  MediaListCollection(userId: $userId, type: ANIME, forceSingleCompletedList: true) {
    lists {
      isCustomList
      entries { mediaId status score(format: POINT_10) progress updatedAt }
    }
  }
}
"""

COLUMNS = ["user_id", "anime_id", "status", "score", "progress", "updated_at"]


class UserUnavailable(Exception):
    """Профиль закрыт или удалён: пользователя пропускаем."""


class GraphQLError(RuntimeError):
    """Ошибка запроса, которую нельзя автоматически считать закрытым профилем."""

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__("; ".join(e.get("message", "неизвестная ошибка") for e in errors))


def parse_entries(user_id: int, collection: dict) -> list[dict]:
    """Превращает ответ MediaListCollection в строки таблицы.

    Пользовательские списки (isCustomList) пропускаем: в них лежат копии
    записей из основных списков. Оценка 0 и updatedAt 0 у AniList означают
    «нет значения», пишем вместо них None.
    """
    rows: dict[int, dict] = {}
    for lst in collection.get("lists") or []:
        if lst.get("isCustomList"):
            continue
        for e in lst.get("entries") or []:
            rows[e["mediaId"]] = {
                "user_id": user_id,
                "anime_id": e["mediaId"],
                "status": e["status"],
                "score": e["score"] or None,
                "progress": e["progress"],
                "updated_at": e["updatedAt"] or None,
            }
    return list(rows.values())


@dataclass
class RateLimiter:
    """Держит паузу между запросами, чтобы не выйти за лимит API."""

    per_minute: int
    _last: float = 0.0

    def wait(self) -> None:
        interval = 60.0 / self.per_minute
        delay = self._last + interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


def retry_delay(attempt: int) -> float:
    """Пауза перед повтором: 5, 10, 20, 40… секунд, не больше 5 минут.
    10 попыток переживают обрыв сети примерно на 20 минут."""
    return min(5.0 * 2 ** (attempt - 1), 300.0)


class AniListClient:
    def __init__(self, per_minute: int = 28, max_retries: int = 10):
        self.limiter = RateLimiter(per_minute)
        self.max_retries = max_retries
        self.http = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def query(self, query: str, variables: dict) -> dict:
        for attempt in range(1, self.max_retries + 1):
            self.limiter.wait()
            try:
                resp = self.http.post(API_URL, json={"query": query, "variables": variables})
            except httpx.TransportError as exc:
                log.warning("сетевая ошибка (%s), попытка %d", exc, attempt)
                time.sleep(retry_delay(attempt))
                continue

            if resp.status_code == 429:
                pause = int(resp.headers.get("Retry-After", 60)) + 1
                log.warning("лимит запросов исчерпан, ждём %d с", pause)
                time.sleep(pause)
                continue
            if resp.status_code >= 500:
                log.warning("ошибка сервера %d, попытка %d", resp.status_code, attempt)
                time.sleep(retry_delay(attempt))
                continue

            try:
                body = resp.json()
            except ValueError:
                resp.raise_for_status()  # HTML с HTTP-ошибкой — не закрытый профиль
                log.warning("невалидный JSON, попытка %d", attempt)
                time.sleep(retry_delay(attempt))
                continue
            if not isinstance(body, dict):
                raise RuntimeError("AniList вернул неожиданный формат ответа")
            errors = body.get("errors")
            if errors:
                # Ошибки GraphQL возможны и при HTTP 200, и с частичными data.
                # Частичный список не сохраняем как полный.
                if all(e.get("status") in (429, 500, 502, 503, 504) for e in errors):
                    log.warning("временная ошибка GraphQL, попытка %d", attempt)
                    time.sleep(retry_delay(attempt))
                    continue
                if resp.status_code not in (200, 404):
                    resp.raise_for_status()
                raise GraphQLError(errors)
            resp.raise_for_status()
            if not isinstance(body.get("data"), dict):
                raise RuntimeError("AniList не вернул data")
            return body["data"]
        raise RuntimeError(f"AniList не ответил после {self.max_retries} попыток")

    def activity_user_ids(self, before: int | None) -> tuple[list[int], int | None]:
        """Возвращает id пользователей и время самой старой активности на странице
        (курсор для следующего запроса; None, если лента закончилась)."""
        # null в фильтре AniList не принимает, поэтому для первого запроса берём «сейчас»
        before = before or int(time.time()) + 60
        data = self.query(ACTIVITIES_QUERY, {"before": before})["Page"]
        activities = [a for a in data["activities"] if a and a.get("userId")]
        ids = [a["userId"] for a in activities]
        cursor = min((a["createdAt"] for a in activities), default=None)
        return ids, cursor

    def user_entries(self, user_id: int) -> list[dict]:
        try:
            data = self.query(LIST_QUERY, {"userId": user_id})
        except GraphQLError as exc:
            # Только явный Not Found при запросе конкретного списка.
            if all(e.get("status") == 404 for e in exc.errors):
                raise UserUnavailable(str(exc)) from exc
            raise
        collection = data.get("MediaListCollection")
        if not isinstance(collection, dict) or "lists" not in collection:
            raise RuntimeError("AniList не вернул MediaListCollection.lists")
        return parse_entries(user_id, collection)


@dataclass
class CrawlState:
    """Прогресс краулера; сохраняется после каждой записанной части."""

    activity_before: int | None = None
    pending: list[int] = field(default_factory=list)
    done: list[int] = field(default_factory=list)
    skipped: int = 0
    next_part: int = 0

    @classmethod
    def load(cls, path: Path) -> CrawlState:
        if path.exists():
            data = json.loads(path.read_text())
            # старый формат с номером страницы: ленту пройдём заново сверху,
            # уже известных пользователей отсеет проверка seen
            data.pop("activity_page", None)
            return cls(**data)
        return cls()

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__))
        os.replace(tmp, path)  # атомарно: при сбое не останется битого файла


def crawl(client: AniListClient, out_dir: Path, target_users: int, part_size: int = 100) -> CrawlState:
    """Докачивает данные, пока обработанных пользователей меньше target_users.

    Записи копятся в памяти и пишутся частями part-NNNNN.parquet. Состояние
    сохраняется только после записи части, поэтому при сбое теряется не больше
    одной части, а её номер переиспользуется, и дублей не будет.
    """
    parts_dir = out_dir / "lists"
    parts_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = CrawlState.load(state_path)
    seen = set(state.done) | set(state.pending)

    batch_rows: list[dict] = []
    batch_users: list[int] = []
    batch_skipped = 0

    def flush() -> None:
        nonlocal batch_skipped
        if not batch_users:
            return
        df = pd.DataFrame(batch_rows, columns=COLUMNS).astype(
            {"user_id": "int64", "anime_id": "int64", "score": "Int8",
             "progress": "Int32", "updated_at": "Int64"}
        )
        # пишем во временный файл и переименовываем, чтобы читатель папки не увидел
        # недописанную часть; файлы с точкой в начале pyarrow при чтении пропускает
        name = f"part-{state.next_part:05d}.parquet"
        tmp = parts_dir / f".{name}.tmp"
        df.to_parquet(tmp, index=False)
        os.replace(tmp, parts_dir / name)
        state.next_part += 1
        state.done.extend(batch_users)
        state.pending = state.pending[len(batch_users):]
        state.skipped += batch_skipped
        state.save(state_path)
        log.info("часть записана: пользователей %d, всего %d, пропущено %d",
                 len(batch_users), len(state.done), state.skipped)
        batch_rows.clear()
        batch_users.clear()
        batch_skipped = 0

    while len(state.done) + len(batch_users) < target_users:
        position = len(batch_users)
        if position >= len(state.pending):
            ids, cursor = client.activity_user_ids(state.activity_before)
            if cursor is None:
                log.warning("лента активностей закончилась")
                break
            state.activity_before = cursor
            new_ids = [i for i in dict.fromkeys(ids) if i not in seen]
            seen.update(new_ids)
            state.pending.extend(new_ids)
            continue

        user_id = state.pending[position]
        try:
            rows = client.user_entries(user_id)
        except UserUnavailable as exc:
            log.debug("пользователь %d пропущен: %s", user_id, exc)
            rows = []
            batch_skipped += 1
        batch_rows.extend(rows)
        batch_users.append(user_id)
        if len(batch_users) >= part_size:
            flush()

    flush()
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, required=True, help="сколько всего пользователей собрать")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="папка для данных")
    parser.add_argument("--per-minute", type=int, default=28, help="запросов в минуту (лимит AniList 30)")
    parser.add_argument("--part-size", type=int, default=100, help="пользователей в одном parquet-файле")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    crawl(AniListClient(per_minute=args.per_minute), args.out, args.users, args.part_size)


if __name__ == "__main__":
    main()
