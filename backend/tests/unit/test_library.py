"""Тесты этапа 3: списки пользователя (PUT/DELETE /me/list), профили, лента активности."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.anime import Anime
from app.models.enums import ActivityType
from app.models.library import UserActivity, UserAnime
from app.models.user import User
from tests.api_context import ApiTestContext

REGISTER_URL = "/api/v1/auth/register"
ME_LIST_URL = "/api/v1/me/list"
USERS_URL = "/api/v1/users"
PASSWORD = "password123"


async def _register(api: ApiTestContext, username: str = "user1") -> dict:
    response = await api.client.post(
        REGISTER_URL,
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _seed_anime(api: ApiTestContext) -> list[Anime]:
    """Три тайтла разных лет — достаточно для списков и ленты."""
    titles = [
        Anime(anilist_id=1, mal_id=101, title_ru="Наруто", title_en="Naruto",
              kind="tv", status="released", episodes=220, aired_on=date(2002, 10, 3)),
        Anime(anilist_id=2, mal_id=None, title_ru=None, title_en="Naruto Movie",
              kind="movie", status="released", episodes=1, aired_on=date(2004, 8, 21)),
        Anime(anilist_id=3, mal_id=103, title_ru="Боруто", title_en="Boruto",
              kind="tv", status="ongoing", episodes=12, aired_on=date(2023, 4, 5)),
    ]
    api.session.add_all(titles)
    await api.session.flush()
    return titles


async def _put(api: ApiTestContext, token: str, anime_id: int, **body: object):
    return await api.client.put(
        f"{ME_LIST_URL}/{anime_id}", json=body, headers=_auth(token)
    )


async def _activities(api: ApiTestContext, user_id: int) -> list[UserActivity]:
    return list((await api.session.scalars(
        select(UserActivity).where(UserActivity.user_id == user_id)
        .order_by(UserActivity.created_at, UserActivity.id)
    )).all())


# ---------- PUT /me/list ----------

async def test_put_creates_entry(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    response = await _put(api, token, anime.id, status="watching", score=9, episodes_watched=12)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["anime_id"] == anime.id
    assert data["status"] == "watching"
    assert data["score"] == 9
    assert data["episodes_watched"] == 12
    assert data["updated_at"]
    assert data["anime"]["id"] == anime.id
    assert data["anime"]["title_en"] == "Naruto"

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    row = await api.session.scalar(select(UserAnime).where(UserAnime.anime_id == anime.id))
    assert row is not None and row.user_id == user_id


async def test_put_requires_auth(api: ApiTestContext) -> None:
    anime = (await _seed_anime(api))[0]
    response = await api.client.put(f"{ME_LIST_URL}/{anime.id}", json={"status": "watching"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_put_anime_not_found(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    response = await _put(api, token, 999999, status="watching")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANIME_NOT_FOUND"


@pytest.mark.parametrize("body", [
    {"status": "watching", "score": 0},
    {"status": "watching", "score": 11},
    {"status": "watching", "episodes_watched": -1},
    {"status": "watching", "episodes_watched": 221},  # у Наруто 220 эпизодов
    {"status": "unknown_status"},
])
async def test_put_validation(api: ApiTestContext, body: dict) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]
    response = await _put(api, token, anime.id, **body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_put_upsert_updates_single_row(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    first = await _put(api, token, anime.id, status="planned")
    assert first.status_code == 200
    second = await _put(api, token, anime.id, status="watching")
    assert second.status_code == 200
    assert second.json()["status"] == "watching"

    count = await api.session.scalar(select(func.count()).select_from(UserAnime))
    assert count == 1  # upsert, а не вторая строка


async def test_put_omitted_fields_keep_previous_values(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=8, episodes_watched=5)
    response = await _put(api, token, anime.id, status="completed")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["score"] == 8
    assert data["episodes_watched"] == 5


async def test_put_full_payload_overwrites(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=8, episodes_watched=5)
    response = await _put(api, token, anime.id, status="completed", score=10, episodes_watched=220)

    data = response.json()
    assert (data["status"], data["score"], data["episodes_watched"]) == ("completed", 10, 220)


async def test_put_explicit_null_clears_score(api: ApiTestContext) -> None:
    """Явный "score": null снимает оценку; пропущенное поле её сохраняет."""
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=8)
    cleared = await _put(api, token, anime.id, status="watching", score=None)
    assert cleared.status_code == 200
    assert cleared.json()["score"] is None

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    assert events[-1].type == ActivityType.SCORED
    assert events[-1].payload == {"score": None}


async def test_put_score_change_after_clear_emits_again(api: ApiTestContext) -> None:
    """После снятия новая оценка снова эмитит scored."""
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=8)
    await _put(api, token, anime.id, status="watching", score=None)
    await _put(api, token, anime.id, status="watching", score=6)

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    scored = [e for e in await _activities(api, user_id) if e.type == ActivityType.SCORED]
    assert [e.payload for e in scored] == [{"score": 8}, {"score": None}, {"score": 6}]


async def test_put_progress_reset_to_zero(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", episodes_watched=7)
    response = await _put(api, token, anime.id, status="watching", episodes_watched=0)

    assert response.json()["episodes_watched"] == 0


# ---------- события ленты при PUT ----------

async def test_activity_list_added(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching")

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    assert [(e.type, e.payload) for e in events] == [
        (ActivityType.LIST_ADDED, {"status": "watching"})
    ]
    assert events[0].anime_id == anime.id


async def test_activity_list_added_with_score_emits_both(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=9)

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    assert [(e.type, e.payload) for e in events] == [
        (ActivityType.LIST_ADDED, {"status": "watching"}),
        (ActivityType.SCORED, {"score": 9}),
    ]


async def test_activity_status_changed(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="planned")
    await _put(api, token, anime.id, status="watching")

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    assert [(e.type, e.payload) for e in events][-1] == (
        ActivityType.STATUS_CHANGED, {"from": "planned", "to": "watching"}
    )


async def test_activity_progress_updated(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", episodes_watched=5)
    await _put(api, token, anime.id, status="watching", episodes_watched=7)

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    assert [(e.type, e.payload) for e in events][-1] == (
        ActivityType.PROGRESS_UPDATED, {"episodes_watched": 7}
    )


async def test_activity_status_change_suppresses_progress_event(api: ApiTestContext) -> None:
    """Смена статуса и прогресса одним запросом: по контракту только status_changed."""
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", episodes_watched=1)
    await _put(api, token, anime.id, status="completed", episodes_watched=220)

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    types = [e.type for e in events]
    assert ActivityType.STATUS_CHANGED in types
    assert ActivityType.PROGRESS_UPDATED not in types


async def test_activity_no_events_on_identical_put(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]

    await _put(api, token, anime.id, status="watching", score=7)
    await _put(api, token, anime.id, status="watching", score=7)

    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    events = await _activities(api, user_id)
    scored = [e for e in events if e.type == ActivityType.SCORED]
    assert len(scored) == 1  # повторный идентичный PUT не плодит scored


# ---------- DELETE /me/list ----------

async def test_delete_removes_entry(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]
    await _put(api, token, anime.id, status="watching")

    response = await api.client.delete(f"{ME_LIST_URL}/{anime.id}", headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    remaining = await api.session.scalar(select(func.count()).select_from(UserAnime))
    assert remaining == 0


async def test_delete_requires_auth(api: ApiTestContext) -> None:
    anime = (await _seed_anime(api))[0]
    response = await api.client.delete(f"{ME_LIST_URL}/{anime.id}")
    assert response.status_code == 401


async def test_delete_not_in_list(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = (await _seed_anime(api))[0]
    response = await api.client.delete(f"{ME_LIST_URL}/{anime.id}", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LIST_ENTRY_NOT_FOUND"


async def test_delete_unknown_anime(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    response = await api.client.delete(f"{ME_LIST_URL}/999999", headers=_auth(token))
    assert response.status_code == 404


# ---------- GET /users/{username} ----------

async def _put_all(api: ApiTestContext, token: str, anime: list[Anime]) -> None:
    await _put(api, token, anime[0].id, status="completed", score=9)
    await _put(api, token, anime[1].id, status="completed", score=6)
    await _put(api, token, anime[2].id, status="watching", episodes_watched=3)


async def test_profile_stats(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = await _seed_anime(api)
    await _put_all(api, token, anime)

    response = await api.client.get(f"{USERS_URL}/user1")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["username"] == "user1"
    # mean_score — Decimal, в JSON уходит строкой (та же конвенция, что у stats.avg_score)
    assert data["stats"] == {
        "planned": 0, "watching": 1, "completed": 2, "on_hold": 0, "dropped": 0,
        "scores_count": 2, "mean_score": "7.5",
    }


async def test_profile_empty_user(api: ApiTestContext) -> None:
    await _register(api)
    response = await api.client.get(f"{USERS_URL}/user1")
    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["scores_count"] == 0
    assert stats["mean_score"] is None
    assert stats["completed"] == 0


async def test_profile_user_not_found(api: ApiTestContext) -> None:
    response = await api.client.get(f"{USERS_URL}/ghost")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize("username", ["ab", "bad name", "кириллица", "x" * 33, "-bad"])
async def test_profile_invalid_username_format(api: ApiTestContext, username: str) -> None:
    """Формат username из контракта ^[A-Za-z0-9_]{3,32}$: мусор отсекается 422 до БД."""
    response = await api.client.get(f"{USERS_URL}/{username}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_profile_lookup_case_insensitive(api: ApiTestContext) -> None:
    await _register(api, username="MiXeD")
    response = await api.client.get(f"{USERS_URL}/mixed")
    assert response.status_code == 200
    assert response.json()["username"] == "MiXeD"


# ---------- GET /users/{username}/list ----------

async def test_user_list_pagination(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = await _seed_anime(api)
    await _put_all(api, token, anime)

    page1 = await api.client.get(f"{USERS_URL}/user1/list?page=1&limit=2")
    assert page1.status_code == 200
    data = page1.json()
    assert data["total"] == 3 and data["page"] == 1 and data["limit"] == 2
    assert len(data["items"]) == 2

    page2 = await api.client.get(f"{USERS_URL}/user1/list?page=2&limit=2")
    data2 = page2.json()
    assert len(data2["items"]) == 1
    assert {i["id"] for i in data["items"]} & {i["id"] for i in data2["items"]} == set()

    item = data["items"][0]
    assert item["status"] in {"watching", "completed"}
    assert "score" in item and "episodes_watched" in item and "updated_at" in item


async def test_user_list_filter_by_status(api: ApiTestContext) -> None:
    token = (await _register(api))["access_token"]
    anime = await _seed_anime(api)
    await _put_all(api, token, anime)

    response = await api.client.get(f"{USERS_URL}/user1/list?status=completed")
    data = response.json()
    assert data["total"] == 2
    assert all(i["status"] == "completed" for i in data["items"])


async def test_user_list_empty_and_unknown_user(api: ApiTestContext) -> None:
    await _register(api)
    empty = await api.client.get(f"{USERS_URL}/user1/list")
    assert empty.json() == {"items": [], "total": 0, "page": 1, "limit": 20}

    ghost = await api.client.get(f"{USERS_URL}/ghost/list")
    assert ghost.status_code == 404
    assert ghost.json()["error"]["code"] == "USER_NOT_FOUND"


# ---------- GET /users/{username}/activity ----------

async def _seed_activity(api: ApiTestContext, user_id: int, anime: Anime | None, n: int) -> None:
    base = datetime.now(timezone.utc) - timedelta(minutes=n)
    api.session.add_all([
        UserActivity(
            user_id=user_id, anime_id=anime.id if anime else None,
            type=ActivityType.SCORED, payload={"score": i}, created_at=base + timedelta(minutes=i),
        )
        for i in range(n)
    ])
    await api.session.flush()


async def test_activity_feed_order_and_cards(api: ApiTestContext) -> None:
    await _register(api, username="viewer")
    token = (await _register(api, username="actor"))["access_token"]
    anime = (await _seed_anime(api))[0]
    await _put(api, token, anime.id, status="watching", score=9)
    actor_id = (await api.session.scalar(select(User).where(User.username == "actor"))).id

    response = await api.client.get(f"{USERS_URL}/actor/activity")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["next_cursor"] is None
    assert [i["type"] for i in data["items"]] == ["scored", "list_added"]  # новые первыми
    scored = data["items"][0]
    assert scored["payload"] == {"score": 9}
    assert scored["anime_id"] == anime.id
    assert scored["anime"]["title_en"] == "Naruto"
    assert scored["created_at"]
    assert {i["id"] for i in data["items"]} == {i.id for i in await _activities(api, actor_id)}


async def test_activity_cursor_pagination(api: ApiTestContext) -> None:
    await _register(api)
    anime = (await _seed_anime(api))[0]
    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    await _seed_activity(api, user_id, anime, n=5)

    seen: list[int] = []
    cursor: str | None = None
    for expected_len in (2, 2, 1):
        url = f"{USERS_URL}/user1/activity?limit=2"
        if cursor is not None:
            url += f"&cursor={cursor}"
        response = await api.client.get(url)
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == expected_len
        seen.extend(i["id"] for i in data["items"])
        cursor = data["next_cursor"]
    assert cursor is None  # записи кончились
    assert len(seen) == len(set(seen)) == 5  # без дублей и пропусков


async def test_activity_invalid_cursor(api: ApiTestContext) -> None:
    await _register(api)
    response = await api.client.get(f"{USERS_URL}/user1/activity?cursor=!!!not-base64")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_activity_user_not_found(api: ApiTestContext) -> None:
    response = await api.client.get(f"{USERS_URL}/ghost/activity")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_activity_event_without_anime(api: ApiTestContext) -> None:
    """События этапов 4–5 без тайтла (anime_id=null): читалка отдаёт anime: null."""
    await _register(api)
    user_id = (await api.session.scalar(select(User).where(User.username == "user1"))).id
    api.session.add(UserActivity(
        user_id=user_id, anime_id=None, type=ActivityType.TOPIC_CREATED,
        payload={"topic_id": 5}, created_at=datetime.now(timezone.utc),
    ))
    await api.session.flush()

    response = await api.client.get(f"{USERS_URL}/user1/activity")

    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["type"] == "topic_created"
    assert data["items"][0]["anime_id"] is None
    assert data["items"][0]["anime"] is None
