import pandas as pd
import pytest

from app.recsys.popularity import GenrePopularityRecommender, PopularityRecommender
from app.training.evaluate import evaluate

NOW = pd.Timestamp("2026-10-01", tz="UTC")


def interactions(rows):
    """rows: (user_id, anime_id, status, score, дней назад от NOW или None)."""
    df = pd.DataFrame(rows, columns=["user_id", "anime_id", "status", "score", "days_ago"])
    df["score"] = df["score"].astype("Int8")
    df["updated_at"] = NOW - pd.to_timedelta(df.pop("days_ago"), unit="D")
    return df


def crowd(anime, users, days_ago=1, status="completed", first_user=1000):
    """users разных пользователей добавили тайтл anime."""
    return [(first_user + u, anime, status, None, days_ago) for u in range(users)]


def test_recent_popularity_ranks_by_users_in_window():
    df = interactions(
        crowd(1, 3, days_ago=1)
        + crowd(2, 5, days_ago=1)
        + crowd(3, 10, days_ago=100)  # хит прошлого, в окно 28 дней не попадает
        + crowd(4, 20, days_ago=1, status="dropped")  # массово бросают — не популярность
    )
    model = PopularityRecommender(window_days=28).fit(df)
    assert model.recommend(user_id=1, k=10) == [2, 1]


def test_all_time_popularity_includes_old_and_undated():
    df = interactions(crowd(1, 3) + crowd(2, 5, days_ago=None) + crowd(3, 10, days_ago=1000))
    model = PopularityRecommender(window_days=None).fit(df)
    assert model.recommend(user_id=1) == [3, 2, 1]


def test_window_counts_back_from_given_now():
    df = interactions(crowd(1, 3, days_ago=1) + crowd(2, 5, days_ago=40))
    model = PopularityRecommender(window_days=28).fit(df, now=NOW - pd.Timedelta(days=30))
    assert model.recommend(user_id=1) == [2]  # окно — 30–58 дней назад


def test_ties_are_broken_by_anime_id():
    df = interactions(crowd(7, 2) + crowd(3, 2) + crowd(5, 2))
    assert PopularityRecommender().fit(df).recommend(user_id=1) == [3, 5, 7]


def test_recommend_excludes_users_list_including_dropped():
    df = interactions(
        crowd(1, 5) + crowd(2, 4) + crowd(3, 3) + crowd(4, 2)
        + [(1, 1, "completed", 9, 1), (1, 2, "dropped", None, 1)]
    )
    model = PopularityRecommender().fit(df)
    assert model.recommend(user_id=1, k=2) == [3, 4]
    assert model.recommend(user_id=999, k=2) == [1, 2]  # незнакомый пользователь получает топ


def test_recommend_many_feeds_evaluate():
    df = interactions(crowd(1, 5) + crowd(2, 4) + [(1, 1, "completed", None, 1)])
    recs = PopularityRecommender().fit(df).recommend_many([1, 2], k=1)
    assert recs == {1: [2], 2: [1]}
    assert evaluate(recs, {1: {2}, 2: {3}}, k=1)["precision@1"] == pytest.approx(0.5)


# Пример из объяснения: новичок Боря добавил 3 драмы, у двух ещё романтика.
DRAMA, ROMANCE, ACTION = 1, 2, 3
BORYA = 1
TITLE_A, TITLE_B = 100, 200  # A — экшен (26 человек), B — драма и романтика (18)
BORYA_GENRES = {
    TITLE_A: {ACTION},
    TITLE_B: {DRAMA, ROMANCE},
    11: {DRAMA, ROMANCE},
    12: {DRAMA, ROMANCE},
    13: {DRAMA},
}
BORYA_ROWS = (
    crowd(TITLE_A, 26)
    + crowd(TITLE_B, 18)
    + [(BORYA, 11, "completed", 9, 1), (BORYA, 12, "watching", None, 1), (BORYA, 13, "completed", 8, 1)]
)


def test_favourite_genres_lift_title_above_more_popular():
    df = interactions(BORYA_ROWS)
    model = GenrePopularityRecommender(BORYA_GENRES).fit(df)
    # A: 26 × (1 + 0) = 26; B: 18 × (1 + (1 + 2/3) / 2) = 33
    assert model.recommend(BORYA, k=2) == [TITLE_B, TITLE_A]
    assert model.preferences_[BORYA].tolist() == pytest.approx([1.0, 2 / 3, 0.0])  # драма, романтика, экшен


def test_zero_beta_is_plain_popularity():
    df = interactions(BORYA_ROWS)
    model = GenrePopularityRecommender(BORYA_GENRES, beta=0).fit(df)
    assert model.recommend(BORYA, k=2) == [TITLE_A, TITLE_B]


def test_disliked_titles_do_not_shape_taste():
    # драмы Боря бросил или оценил низко — жанр не любимый, остаётся экшен
    df = interactions(
        crowd(TITLE_A, 18)
        + crowd(TITLE_B, 26)
        + [(BORYA, 11, "dropped", None, 1), (BORYA, 12, "completed", 3, 1), (BORYA, 14, "completed", 9, 1)]
    )
    genres = {**BORYA_GENRES, 14: {ACTION}}
    model = GenrePopularityRecommender(genres).fit(df)
    assert model.preferences_[BORYA].tolist() == pytest.approx([0.0, 0.0, 1.0])
    assert model.recommend(BORYA, k=2) == [TITLE_A, TITLE_B]  # 18 × 2 = 36 > 26


def test_without_known_genres_falls_back_to_popularity():
    df = interactions(BORYA_ROWS + [(2, 999, "completed", None, 1)])  # у тайтла 999 жанров нет
    model = GenrePopularityRecommender(BORYA_GENRES).fit(df)
    assert 2 not in model.preferences_
    assert model.recommend(2, k=2) == [TITLE_A, TITLE_B]
    assert model.recommend(12345, k=2) == [TITLE_A, TITLE_B]  # совсем новый пользователь


def test_bad_parameters_fail():
    with pytest.raises(ValueError):
        PopularityRecommender(window_days=0)
    with pytest.raises(ValueError):
        GenrePopularityRecommender({}, beta=-1)


@pytest.mark.parametrize("k", [0, -1, 1.5, True])
@pytest.mark.parametrize("genre_based", [False, True])
def test_recommend_rejects_invalid_k(k, genre_based):
    model = GenrePopularityRecommender({}) if genre_based else PopularityRecommender()
    model.fit(interactions(crowd(1, 3)))
    with pytest.raises(ValueError, match="k"):
        model.recommend(1, k=k)
    with pytest.raises(ValueError, match="k"):
        model.recommend_many([1], k=k)
    with pytest.raises(ValueError, match="k"):
        model.recommend_many([], k=k)


def test_full_history_preserves_cold_start_taste_and_exclusions():
    training = interactions(crowd(TITLE_A, 26) + crowd(TITLE_B, 18))
    history = interactions(BORYA_ROWS + [(2, TITLE_A, "dropped", None, 1),
                                        (2, TITLE_B, "completed", 2, 1)])
    model = GenrePopularityRecommender(BORYA_GENRES).fit(training, history=history)
    assert model.recommend(BORYA, 2) == [TITLE_B, TITLE_A]
    assert model.recommend(2, 2) == []
    # История не добавляет голоса к популярности обучающей выборки.
    assert model.popularity_.tolist() == [26, 18]


def test_empty_genres_do_not_dilute_known_preferences():
    df = interactions(BORYA_ROWS + [(BORYA, 99, "completed", 9, 1)])
    model = GenrePopularityRecommender({**BORYA_GENRES, 99: set()}).fit(df)
    assert model.preferences_[BORYA].tolist() == pytest.approx([1, 2 / 3, 0])


def test_string_genres_work_and_users_without_positive_history_keep_plain_ranking():
    df = interactions(BORYA_ROWS + [(2, 11, "dropped", None, 1),
                                  (2, 12, "completed", 2, 1)])
    names = {DRAMA: "Drama", ROMANCE: "Romance", ACTION: "Action"}
    genres = {item: {names[g] for g in gs} for item, gs in BORYA_GENRES.items()}
    model = GenrePopularityRecommender(genres).fit(df)
    plain = PopularityRecommender().fit(df)
    assert model.recommend(BORYA, 2) == [TITLE_B, TITLE_A]
    for user in [2, 99999]:
        assert model.recommend(user) == plain.recommend(user)
