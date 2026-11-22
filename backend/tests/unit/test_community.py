"""Тесты этапа 4: отзывы, темы, комментарии и их события в ленте активности."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.community import Comment, Topic
from app.models.enums import ActivityType
from app.models.library import Review, UserActivity
from app.models.user import User
from tests.api_context import ApiTestContext

REGISTER_URL = "/api/v1/auth/register"
PASSWORD = "password123"


async def _register(api: ApiTestContext, username: str) -> str:
    response = await api.client.post(
        REGISTER_URL,
        json={"username": username, "email": f"{username}@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_anime(api: ApiTestContext) -> list[Anime]:
    titles = [
        Anime(anilist_id=1, mal_id=101, title_ru="Наруто", title_en="Naruto",
              kind="tv", status="released", episodes=220, aired_on=date(2002, 10, 3)),
        Anime(anilist_id=2, mal_id=None, title_ru=None, title_en="Boruto",
              kind="tv", status="ongoing", episodes=12, aired_on=date(2023, 4, 5)),
    ]
    api.session.add_all(titles)
    await api.session.flush()
    return titles


async def _activities(api: ApiTestContext, user_id: int) -> list[UserActivity]:
    return list((await api.session.scalars(
        select(UserActivity).where(UserActivity.user_id == user_id)
        .order_by(UserActivity.created_at, UserActivity.id)
    )).all())


# ---------- отзывы ----------

async def test_post_review(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    anime = (await _seed_anime(api))[0]

    response = await api.client.post(
        f"/api/v1/anime/{anime.id}/reviews",
        json={"score": 9, "text": "Классика жанра"},
        headers=_auth(token),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["score"] == 9 and data["text"] == "Классика жанра"
    assert data["username"] == "author"
    review_id = data["id"]

    # событие reviewed в ленте с реальным review_id
    user_id = (await api.session.scalar(select(User).where(User.username == "author"))).id
    events = await _activities(api, user_id)
    assert [(e.type, e.payload, e.anime_id) for e in events] == [
        (ActivityType.REVIEWED, {"review_id": review_id}, anime.id)
    ]


async def test_post_review_duplicate(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    anime = (await _seed_anime(api))[0]
    body = {"score": 9, "text": "Первый"}

    first = await api.client.post(f"/api/v1/anime/{anime.id}/reviews", json=body, headers=_auth(token))
    assert first.status_code == 201
    second = await api.client.post(f"/api/v1/anime/{anime.id}/reviews", json=body, headers=_auth(token))
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "REVIEW_EXISTS"


async def test_post_review_errors(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    anime = (await _seed_anime(api))[0]

    unauth = await api.client.post(f"/api/v1/anime/{anime.id}/reviews", json={"score": 9, "text": "x"})
    assert unauth.status_code == 401

    ghost = await api.client.post(
        "/api/v1/anime/999999/reviews", json={"score": 9, "text": "x"}, headers=_auth(token)
    )
    assert ghost.status_code == 404
    assert ghost.json()["error"]["code"] == "ANIME_NOT_FOUND"

    for bad in ({"score": 0, "text": "x"}, {"score": 11, "text": "x"}, {"score": 9, "text": ""}):
        invalid = await api.client.post(
            f"/api/v1/anime/{anime.id}/reviews", json=bad, headers=_auth(token)
        )
        assert invalid.status_code == 422, bad


async def test_list_reviews(api: ApiTestContext) -> None:
    token1 = await _register(api, "first")
    token2 = await _register(api, "second")
    anime = (await _seed_anime(api))[0]
    await api.client.post(f"/api/v1/anime/{anime.id}/reviews",
                          json={"score": 7, "text": "Первый отзыв"}, headers=_auth(token1))
    await api.client.post(f"/api/v1/anime/{anime.id}/reviews",
                          json={"score": 9, "text": "Второй отзыв"}, headers=_auth(token2))

    response = await api.client.get(f"/api/v1/anime/{anime.id}/reviews")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2 and len(data["items"]) == 2
    assert [i["text"] for i in data["items"]] == ["Второй отзыв", "Первый отзыв"]  # новые первыми
    assert {i["username"] for i in data["items"]} == {"first", "second"}

    ghost = await api.client.get("/api/v1/anime/999999/reviews")
    assert ghost.status_code == 404


async def test_patch_review_author_only(api: ApiTestContext) -> None:
    author = await _register(api, "author")
    other = await _register(api, "other")
    anime = (await _seed_anime(api))[0]
    created = await api.client.post(f"/api/v1/anime/{anime.id}/reviews",
                                    json={"score": 5, "text": "Было скучно"}, headers=_auth(author))
    review_id = created.json()["id"]

    forbidden = await api.client.patch(
        f"/api/v1/reviews/{review_id}", json={"score": 9}, headers=_auth(other)
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN"

    missing = await api.client.patch("/api/v1/reviews/999999",
                                     json={"score": 9}, headers=_auth(author))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "REVIEW_NOT_FOUND"

    empty = await api.client.patch(f"/api/v1/reviews/{review_id}", json={}, headers=_auth(author))
    assert empty.status_code == 422

    null_field = await api.client.patch(
        f"/api/v1/reviews/{review_id}", json={"text": None}, headers=_auth(author)
    )
    assert null_field.status_code == 422
    assert "text" in null_field.json()["error"]["message"]

    patched = await api.client.patch(
        f"/api/v1/reviews/{review_id}", json={"score": 8}, headers=_auth(author)
    )
    assert patched.status_code == 200, patched.text
    data = patched.json()
    assert data["score"] == 8 and data["text"] == "Было скучно"  # text сохранился

    stored = await api.session.get(Review, review_id)
    assert stored.score == 8 and stored.text == "Было скучно"


async def test_delete_review_author_only(api: ApiTestContext) -> None:
    author = await _register(api, "author")
    other = await _register(api, "other")
    anime = (await _seed_anime(api))[0]
    created = await api.client.post(f"/api/v1/anime/{anime.id}/reviews",
                                    json={"score": 5, "text": "x"}, headers=_auth(author))
    review_id = created.json()["id"]

    forbidden = await api.client.delete(f"/api/v1/reviews/{review_id}", headers=_auth(other))
    assert forbidden.status_code == 403

    deleted = await api.client.delete(f"/api/v1/reviews/{review_id}", headers=_auth(author))
    assert deleted.status_code == 200 and deleted.json() == {"ok": True}
    assert await api.session.get(Review, review_id) is None

    again = await api.client.delete(f"/api/v1/reviews/{review_id}", headers=_auth(author))
    assert again.status_code == 404


# ---------- темы ----------

async def test_create_topic_with_and_without_anime(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    anime = (await _seed_anime(api))[0]

    linked = await api.client.post(
        "/api/v1/topics", json={"title": "Сюжет финала", "body": "Как вам концовка?", "anime_id": anime.id},
        headers=_auth(token),
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["anime_id"] == anime.id
    assert linked.json()["comments_count"] == 0

    general = await api.client.post(
        "/api/v1/topics", json={"title": "Оффтоп", "body": "Что смотрите весной?"},
        headers=_auth(token),
    )
    assert general.status_code == 201
    assert general.json()["anime_id"] is None

    ghost = await api.client.post(
        "/api/v1/topics", json={"title": "x", "body": "y", "anime_id": 999999}, headers=_auth(token)
    )
    assert ghost.status_code == 404

    user_id = (await api.session.scalar(select(User).where(User.username == "author"))).id
    events = await _activities(api, user_id)
    topic_events = [e for e in events if e.type == ActivityType.TOPIC_CREATED]
    assert [e.payload for e in topic_events] == [
        {"topic_id": linked.json()["id"]}, {"topic_id": general.json()["id"]}
    ]
    assert topic_events[1].anime_id is None  # общая тема — без тайтла


async def test_list_topics_sorted_by_last_comment(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    anime = (await _seed_anime(api))[0]

    old = await api.client.post("/api/v1/topics",
                                json={"title": "Старая тема", "body": "..."}, headers=_auth(token))
    fresh = await api.client.post(
        "/api/v1/topics", json={"title": "Свежая тема", "body": "...", "anime_id": anime.id},
        headers=_auth(token),
    )
    # комментарий с явным created_at в будущем поднимает тему наверх.
    # (через API нельзя: now() = время начала транзакции теста, у обеих тем он одинаковый)
    api.session.add(Comment(
        topic_id=old.json()["id"], author_id=None, body="ап!",
        created_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    ))
    await api.session.flush()

    response = await api.client.get("/api/v1/topics")
    data = response.json()
    assert [t["title"] for t in data["items"]] == ["Старая тема", "Свежая тема"]
    bumped = data["items"][0]
    assert bumped["comments_count"] == 1
    assert bumped["last_comment_at"] > bumped["created_at"]

    filtered = await api.client.get(f"/api/v1/topics?anime_id={anime.id}")
    assert [t["title"] for t in filtered.json()["items"]] == ["Свежая тема"]


# ---------- комментарии ----------

async def _make_topic(api: ApiTestContext, token: str, title: str = "Тема") -> int:
    response = await api.client.post("/api/v1/topics", json={"title": title, "body": "..."},
                                     headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_post_comment_and_counters(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    topic_id = await _make_topic(api, token)

    response = await api.client.post(
        f"/api/v1/topics/{topic_id}/comments", json={"body": "Первый!"}, headers=_auth(token)
    )

    assert response.status_code == 201, response.text
    comment = response.json()
    assert comment["topic_id"] == topic_id
    assert comment["parent_id"] is None
    assert comment["username"] == "author"

    # счётчики темы ведёт триггер
    topic = await api.session.get(Topic, topic_id)
    assert topic.comments_count == 1

    # событие commented: anime_id темы общей — null
    user_id = (await api.session.scalar(select(User).where(User.username == "author"))).id
    events = await _activities(api, user_id)
    assert events[-1].type == ActivityType.COMMENTED
    assert events[-1].payload == {"topic_id": topic_id, "comment_id": comment["id"]}
    assert events[-1].anime_id is None

    ghost = await api.client.post("/api/v1/topics/999999/comments",
                                  json={"body": "x"}, headers=_auth(token))
    assert ghost.status_code == 404
    assert ghost.json()["error"]["code"] == "TOPIC_NOT_FOUND"


async def test_comment_parent_must_be_in_same_topic(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    topic_a = await _make_topic(api, token, "Тема A")
    topic_b = await _make_topic(api, token, "Тема B")

    parent = await api.client.post(f"/api/v1/topics/{topic_a}/comments",
                                   json={"body": "родитель"}, headers=_auth(token))
    parent_id = parent.json()["id"]

    reply = await api.client.post(f"/api/v1/topics/{topic_a}/comments",
                                  json={"body": "ответ", "parent_id": parent_id},
                                  headers=_auth(token))
    assert reply.status_code == 201
    assert reply.json()["parent_id"] == parent_id

    # родитель из другой темы — триггер БД, 422
    cross = await api.client.post(f"/api/v1/topics/{topic_b}/comments",
                                  json={"body": "чужой", "parent_id": parent_id},
                                  headers=_auth(token))
    assert cross.status_code == 422
    assert cross.json()["error"]["code"] == "VALIDATION_ERROR"

    missing_parent = await api.client.post(f"/api/v1/topics/{topic_a}/comments",
                                           json={"body": "в никуда", "parent_id": 999999},
                                           headers=_auth(token))
    assert missing_parent.status_code == 422


async def test_comments_pagination_newest_first(api: ApiTestContext) -> None:
    token = await _register(api, "author")
    topic_id = await _make_topic(api, token)
    # детерминированные таймстампы в обход now() транзакции
    base = datetime.now(timezone.utc) - timedelta(minutes=10)
    api.session.add_all([
        Comment(topic_id=topic_id, author_id=None, body=f"комментарий {i}",
                created_at=base + timedelta(minutes=i))
        for i in range(5)
    ])
    await api.session.flush()

    seen: list[int] = []
    cursor = None
    for expected_len in (2, 2, 1):
        url = f"/api/v1/topics/{topic_id}/comments?limit=2"
        if cursor:
            url += f"&cursor={cursor}"
        response = await api.client.get(url)
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == expected_len
        seen.extend(c["id"] for c in data["items"])
        cursor = data["next_cursor"]
    assert cursor is None
    assert len(seen) == len(set(seen)) == 5

    all_response = await api.client.get(f"/api/v1/topics/{topic_id}/comments?limit=50")
    bodies = [c["body"] for c in all_response.json()["items"]]
    assert bodies == [f"комментарий {i}" for i in range(4, -1, -1)]  # новые первыми


async def test_deleted_author_behavior(api: ApiTestContext) -> None:
    """Удаление автора: отзывы/темы/комментарии остаются, автор помечается deleted_user."""
    token = await _register(api, "gone")
    anime = (await _seed_anime(api))[0]
    await api.client.post(f"/api/v1/anime/{anime.id}/reviews",
                          json={"score": 9, "text": "отзыв останется"}, headers=_auth(token))
    topic_id = await _make_topic(api, token, "Тема останется")
    await api.client.post(f"/api/v1/topics/{topic_id}/comments",
                          json={"body": "комментарий останется"}, headers=_auth(token))

    user_id = (await api.session.scalar(select(User).where(User.username == "gone"))).id
    await api.session.delete(await api.session.get(User, user_id))  # ON DELETE SET NULL
    await api.session.flush()

    reviews = await api.client.get(f"/api/v1/anime/{anime.id}/reviews")
    item = reviews.json()["items"][0]
    assert item["user_id"] is None and item["username"] == "deleted_user"
    assert item["text"] == "отзыв останется"

    topics = await api.client.get("/api/v1/topics")
    assert topics.json()["items"][0]["author_id"] is None
    assert topics.json()["items"][0]["username"] == "deleted_user"

    comments = await api.client.get(f"/api/v1/topics/{topic_id}/comments")
    assert comments.json()["items"][0]["author_id"] is None
    assert comments.json()["items"][0]["username"] == "deleted_user"
