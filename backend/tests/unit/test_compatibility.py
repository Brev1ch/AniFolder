"""Тесты этапа 6: совместимость вкусов (GET /users/{username}/compatibility)."""

from sqlalchemy import select

from app.models.anime import Anime
from app.models.enums import ListStatus
from app.models.library import UserAnime
from app.models.user import User
from tests.api_context import ApiTestContext

REGISTER_URL = "/api/v1/auth/register"
COMPAT_URL = "/api/v1/users/{username}/compatibility"
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


async def _seed_anime(api: ApiTestContext, n: int) -> list[Anime]:
    titles = [
        Anime(anilist_id=100 + i, mal_id=None, title_ru=None, title_en=f"Title {i}",
              kind="tv", status="released", episodes=12, aired_on=None)
        for i in range(n)
    ]
    api.session.add_all(titles)
    await api.session.flush()
    return titles


async def _rate(api: ApiTestContext, username: str, scores: dict[int, int | None]) -> None:
    """Оценки напрямую в БД: {anime_id: score}. Тайтлы без оценки тоже можно посадить."""
    user_id = (await api.session.scalar(select(User).where(User.username == username))).id
    api.session.add_all([
        UserAnime(user_id=user_id, anime_id=anime_id, status=ListStatus.COMPLETED, score=score)
        for anime_id, score in scores.items()
    ])
    await api.session.flush()


async def test_compatibility_requires_auth_and_user(api: ApiTestContext) -> None:
    await _register(api, "viewer")
    unauth = await api.client.get(COMPAT_URL.format(username="viewer"))
    assert unauth.status_code == 401

    login = await api.client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": PASSWORD}
    )
    assert login.status_code == 200
    ghost = await api.client.get(
        COMPAT_URL.format(username="ghost"), headers=_auth(login.json()["access_token"])
    )
    assert ghost.status_code == 404
    assert ghost.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_compatibility_below_threshold(api: ApiTestContext) -> None:
    me = await _register(api, "viewer")
    await _register(api, "other")
    anime = await _seed_anime(api, 4)
    # обе выборки с ненулевой дисперсией: null может дать только порог, а не статистика
    await _rate(api, "viewer", {a.id: [5, 6, 7, 8][i] for i, a in enumerate(anime)})
    await _rate(api, "other", {a.id: [8, 7, 6, 5][i] for i, a in enumerate(anime)})

    response = await api.client.get(COMPAT_URL.format(username="other"), headers=_auth(me))

    assert response.status_code == 200, response.text
    # 4 общих оценки < порога 5 — compatibility не считаем
    assert response.json() == {"common_titles": 4, "compatibility": None}


async def test_compatibility_perfect_match_and_mismatch(api: ApiTestContext) -> None:
    me = await _register(api, "viewer")
    twin = await _register(api, "twin")
    foe = await _register(api, "foe")
    anime = await _seed_anime(api, 5)  # ровно порог: 5 общих — значение считается

    # twin: те же оценки — корреляция +1 (линейная зависимость y = x)
    await _rate(api, "viewer", {a.id: [5, 6, 7, 8, 9][i] for i, a in enumerate(anime)})
    await _rate(api, "twin", {a.id: [5, 6, 7, 8, 9][i] for i, a in enumerate(anime)})
    # foe: зеркально — корреляция -1 (y = 14 - x)
    await _rate(api, "foe", {a.id: [9, 8, 7, 6, 5][i] for i, a in enumerate(anime)})

    same = await api.client.get(COMPAT_URL.format(username="twin"), headers=_auth(me))
    assert same.json() == {"common_titles": 5, "compatibility": 1.0}

    opposite = await api.client.get(COMPAT_URL.format(username="foe"), headers=_auth(me))
    assert opposite.json() == {"common_titles": 5, "compatibility": -1.0}


async def test_compatibility_ignores_unilateral_titles(api: ApiTestContext) -> None:
    """Безвкусные тайтлы (оценил только один) не входят ни в common_titles, ни в r."""
    me = await _register(api, "viewer")
    await _register(api, "other")
    anime = await _seed_anime(api, 7)
    common6 = anime[:6]
    only_mine = anime[6]

    await _rate(api, "viewer", {a.id: i + 5 for i, a in enumerate(common6)})
    await _rate(api, "viewer", {only_mine.id: None})  # в списке у меня, но без оценки
    await _rate(api, "other", {a.id: 10 for a in common6})
    await _rate(api, "other", {only_mine.id: 10})  # оценил только он

    response = await api.client.get(COMPAT_URL.format(username="other"), headers=_auth(me))

    data = response.json()
    assert data["common_titles"] == 6


async def test_compatibility_zero_variance_is_null(api: ApiTestContext) -> None:
    """Все оценки одного из двух одинаковые — корреляция не определена, null."""
    me = await _register(api, "viewer")
    await _register(api, "flat")
    anime = await _seed_anime(api, 5)
    await _rate(api, "viewer", {a.id: i + 3 for i, a in enumerate(anime)})
    await _rate(api, "flat", {a.id: 7 for a in anime})

    response = await api.client.get(COMPAT_URL.format(username="flat"), headers=_auth(me))

    assert response.json() == {"common_titles": 5, "compatibility": None}


async def test_compatibility_partial_scores_use_only_rated(api: ApiTestContext) -> None:
    """У одного тайтл в списке без оценки — в корреляции не участвует."""
    me = await _register(api, "viewer")
    await _register(api, "other")
    anime = await _seed_anime(api, 6)
    scores_me = [5, 6, 7, 8, 9, None]
    await _rate(api, "viewer", {a.id: scores_me[i] for i, a in enumerate(anime)})
    await _rate(api, "other", {a.id: 9 for a in anime})

    response = await api.client.get(COMPAT_URL.format(username="other"), headers=_auth(me))

    assert response.json()["common_titles"] == 5
