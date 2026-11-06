"""Тесты каталога: жанры, список с фильтрами/поиском, карточка, кэш, readiness."""

from datetime import date

from sqlalchemy import delete, select

from app.models.anime import Anime, AnimeStats, Genre
from tests.api_context import ApiTestContext

GENRES_URL = "/api/v1/genres"
ANIME_URL = "/api/v1/anime"


async def _seed_catalog(api: ApiTestContext) -> tuple[Genre, list[Anime]]:
    """Тайтлы со статистикой. Жанры берём из словаря миграции (Action, Drama)
    плюс один новый без перевода (Isekai, name_ru=NULL), как бывает у новых жанров."""
    action = await api.session.scalar(select(Genre).where(Genre.name_en == "Action"))
    drama = await api.session.scalar(select(Genre).where(Genre.name_en == "Drama"))
    isekai = Genre(name_en="Isekai", name_ru=None)
    api.session.add(isekai)
    await api.session.flush()
    assert action is not None and drama is not None

    titles = [
        Anime(anilist_id=1, mal_id=101, title_ru="Наруто", title_en="Naruto",
              kind="tv", status="released", episodes=220, aired_on=date(2002, 10, 3),
              description="Ниндзя", poster_url="https://img/naruto.jpg"),
        Anime(anilist_id=2, mal_id=None, title_ru=None, title_en="Naruto Movie",
              kind="movie", status="released", episodes=1, aired_on=date(2004, 8, 21),
              description=None, poster_url=None),
        Anime(anilist_id=3, mal_id=103, title_ru="Саске", title_en="Sasuke Future",
              kind="ona", status="ongoing", episodes=12, aired_on=date(2024, 1, 15),
              description=None, poster_url=None),
        Anime(anilist_id=4, mal_id=104, title_ru="Анонс", title_en="Announced Title",
              kind="tv", status="announced", episodes=None, aired_on=None,
              description=None, poster_url=None),
        Anime(anilist_id=5, mal_id=105, title_ru="Отложено", title_en="On Hold Title",
              kind="ova", status="hiatus", episodes=3, aired_on=date(1999, 5, 1),
              description=None, poster_url=None),
    ]
    titles[0].genres = [action, drama]
    titles[1].genres = [action]
    titles[2].genres = [isekai]
    api.session.add_all(titles)
    await api.session.flush()

    api.session.add_all([
        AnimeStats(anime_id=titles[0].id, scores_count=10, avg_score=8.5, in_lists_count=100),
        AnimeStats(anime_id=titles[1].id, scores_count=0, avg_score=None, in_lists_count=5),
        AnimeStats(anime_id=titles[2].id, scores_count=3, avg_score=7.0, in_lists_count=50),
    ])
    await api.session.flush()
    return action, titles


async def test_genres(api: ApiTestContext) -> None:
    await _seed_catalog(api)
    response = await api.client.get(GENRES_URL)
    assert response.status_code == 200
    data = response.json()
    # 18 из словаря миграции + Isekai
    assert len(data) == 19
    by_name = {g["name_en"]: g for g in data}
    assert by_name["Action"]["name_ru"] == "Экшен"
    assert by_name["Isekai"]["name_ru"] is None


async def test_anime_list_pagination(api: ApiTestContext) -> None:
    _, titles = await _seed_catalog(api)
    response = await api.client.get(ANIME_URL, params={"page": 2, "limit": 2, "sort": "title"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["page"] == 2
    assert data["limit"] == 2
    assert len(data["items"]) == 2
    # title-сортировка по title_en
    assert [i["title_en"] for i in data["items"]] == ["Naruto", "Naruto Movie"]


async def test_anime_list_limit_validation(api: ApiTestContext) -> None:
    response = await api.client.get(ANIME_URL, params={"limit": 51})
    assert response.status_code == 422
    response = await api.client.get(ANIME_URL, params={"page": 0})
    assert response.status_code == 422
    response = await api.client.get(ANIME_URL, params={"status": "not-a-status"})
    assert response.status_code == 422


async def test_anime_list_filters(api: ApiTestContext) -> None:
    action, titles = await _seed_catalog(api)

    response = await api.client.get(ANIME_URL, params={"status": "released", "sort": "title"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {i["status"] for i in data["items"]} == {"released"}

    response = await api.client.get(ANIME_URL, params={"kind": "movie"})
    assert response.json()["total"] == 1

    response = await api.client.get(ANIME_URL, params={"genre_id": action.id})
    assert response.json()["total"] == 2

    response = await api.client.get(ANIME_URL, params={"year_from": 2000, "year_to": 2010})
    assert response.json()["total"] == 2  # 2002 и 2004


async def test_anime_list_search(api: ApiTestContext) -> None:
    await _seed_catalog(api)
    response = await api.client.get(ANIME_URL, params={"search": "naruto"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {i["title_en"] for i in data["items"]} == {"Naruto", "Naruto Movie"}

    # поиск по русскому названию
    response = await api.client.get(ANIME_URL, params={"search": "саске"})
    assert response.json()["total"] == 1


async def test_anime_detail(api: ApiTestContext) -> None:
    _, titles = await _seed_catalog(api)
    naruto = titles[0]

    response = await api.client.get(f"{ANIME_URL}/{naruto.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title_en"] == "Naruto"
    assert data["title_ru"] == "Наруто"
    assert data["anilist_id"] == 1
    assert data["mal_id"] == 101
    assert data["aired_on"] == "2002-10-03"
    assert {g["name_en"] for g in data["genres"]} == {"Action", "Drama"}
    assert data["stats"] == {"scores_count": 10, "avg_score": "8.50", "in_lists_count": 100}

    # тайтл без статистики
    response = await api.client.get(f"{ANIME_URL}/{titles[4].id}")
    assert response.json()["stats"] is None


async def test_anime_detail_not_found(api: ApiTestContext) -> None:
    await _seed_catalog(api)
    response = await api.client.get(f"{ANIME_URL}/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANIME_NOT_FOUND"


class _FakeRedis:
    """Минимальный in-memory фейк: только get/set, как redis.asyncio.Redis."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value


async def test_genres_cached(api: ApiTestContext) -> None:
    await _seed_catalog(api)
    api.app.state.redis = _FakeRedis()

    first = await api.client.get(GENRES_URL)
    assert first.status_code == 200

    # данные исчезают из БД, но второй ответ приходит из кэша
    await api.session.execute(delete(Genre))
    second = await api.client.get(GENRES_URL)
    assert second.status_code == 200
    assert len(second.json()) == len(first.json())


async def test_readiness(api: ApiTestContext) -> None:
    response = await api.client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
