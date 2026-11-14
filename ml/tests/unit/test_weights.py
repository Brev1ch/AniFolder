import pandas as pd
import pytest

from app.training.weights import (
    interaction_weights,
    recency_decay,
    score_adjustment,
    weighted_interactions,
)

NOW = pd.Timestamp("2026-10-01", tz="UTC")


def interactions(rows):
    """rows: (user_id, anime_id, status, score, дней назад от NOW или None)."""
    df = pd.DataFrame(rows, columns=["user_id", "anime_id", "status", "score", "days_ago"])
    df["score"] = df["score"].astype("Int8")
    df["updated_at"] = NOW - pd.to_timedelta(df.pop("days_ago"), unit="D")
    return df


# Пример из объяснения: у Ани 12 оценок, личное среднее 8,0
# (кроме тайтлов ниже — ещё 9 записей completed: пять по 8 и четыре по 9).
ANYA = 1
MONSTER, NARUTO, MUSHISHI, CLANNAD, BLEACH, ONE_PIECE = 1, 2, 3, 4, 5, 6
ANYA_ROWS = [
    (ANYA, MONSTER, "completed", 10, 0),
    (ANYA, NARUTO, "completed", 7, 0),
    (ANYA, MUSHISHI, "watching", None, 0),
    (ANYA, CLANNAD, "planned", None, 0),
    (ANYA, BLEACH, "completed", 3, 0),
    (ANYA, ONE_PIECE, "dropped", None, 0),
] + [(ANYA, 100 + i, "completed", 8 if i < 5 else 9, 0) for i in range(9)]


def weight_of(df, weights, anime):
    return weights[df.index[df.anime_id == anime][0]]


def test_hand_example():
    df = interactions(ANYA_ROWS)
    assert df.score.mean() == pytest.approx(8.0)  # проверка самого примера
    weights = interaction_weights(df)

    assert weight_of(df, weights, MONSTER) == pytest.approx(1.4)  # 1 + 0,2 × (10 − 8)
    assert weight_of(df, weights, NARUTO) == pytest.approx(0.8)  # 1 + 0,2 × (7 − 8)
    assert weight_of(df, weights, MUSHISHI) == pytest.approx(1.0)  # без оценки — вес статуса
    assert weight_of(df, weights, CLANNAD) == pytest.approx(0.5)
    assert weight_of(df, weights, BLEACH) == 0.0  # оценка ниже 5
    assert weight_of(df, weights, ONE_PIECE) == 0.0  # брошено


def test_weighted_interactions_drops_zero_weights_only():
    df = interactions(ANYA_ROWS)
    out = weighted_interactions(df)
    assert BLEACH not in set(out.anime_id) and ONE_PIECE not in set(out.anime_id)
    assert len(out) == len(df) - 2
    assert (out.weight > 0).all()


def test_adjustment_is_clipped():
    # личное среднее 6: оценка 10 даст 1 + 0,2 × 4 = 1,8 → 1,5
    df = interactions([(1, i, "completed", 5, 0) for i in range(4)] + [(1, 9, "completed", 10, 0)])
    adjustment = score_adjustment(df)
    assert adjustment[-1] == pytest.approx(1.5)
    assert score_adjustment(df, coef=1.0)[0] == pytest.approx(0.5)  # 1 + (5 − 6) = 0 → 0,5


def test_few_scores_use_global_mean():
    # у пользователя 2 одна оценка: сравниваем с общим средним 7, а не с ней самой
    df = interactions([(1, i, "completed", 7, 0) for i in range(5)] + [(2, 10, "completed", 9, 0)])
    # общее среднее (7×5 + 9) / 6 = 7,33
    assert score_adjustment(df)[-1] == pytest.approx(1 + 0.2 * (9 - 44 / 6))
    # с личным средним было бы ровно 1
    assert score_adjustment(df, min_user_scores=1)[-1] == pytest.approx(1.0)


def test_low_scores_count_in_personal_mean():
    # оценки 2, 8, 8, 8, 8: среднее 6,8, а не 8
    df = interactions([(1, 0, "completed", 2, 0)] + [(1, i, "completed", 8, 0) for i in range(1, 5)])
    assert score_adjustment(df)[1] == pytest.approx(1 + 0.2 * (8 - 6.8))


def test_zero_coef_ignores_scores_except_low():
    df = interactions(ANYA_ROWS)
    weights = interaction_weights(df, score_coef=0)
    assert weight_of(df, weights, MONSTER) == weight_of(df, weights, NARUTO) == 1.0
    assert weight_of(df, weights, BLEACH) == 0.0


def test_no_scores_at_all():
    df = interactions([(1, i, "planned", None, 0) for i in range(3)])
    assert list(interaction_weights(df)) == [0.5, 0.5, 0.5]


def test_custom_status_weights():
    df = interactions(ANYA_ROWS)
    weights = interaction_weights(df, status_weights={"completed": 1.0, "watching": 1.0, "on_hold": 0.5,
                                                      "planned": 1.0, "dropped": 0.0})
    assert weight_of(df, weights, CLANNAD) == 1.0


def test_unknown_status_fails():
    df = interactions([(1, 1, "rewatching", None, 0)])
    with pytest.raises(ValueError, match="rewatching"):
        interaction_weights(df)


def test_recency_decay_halves_each_half_life():
    df = interactions([(1, 1, "completed", None, d) for d in [0, 180, 360, 3000]] + [(1, 2, "completed", None, None)])
    decay = recency_decay(df.updated_at, half_life_days=180, now=NOW)
    assert decay[:3] == pytest.approx([1.0, 0.5, 0.25])
    assert decay[3] == pytest.approx(0.25)  # очень старое — не меньше нижней границы
    assert decay[4] == pytest.approx(0.25)  # без даты — как самое старое


def test_recency_decay_now_defaults_to_latest_record():
    df = interactions([(1, 1, "completed", None, 10), (1, 2, "completed", None, 190)])
    assert recency_decay(df.updated_at, half_life_days=180) == pytest.approx([1.0, 0.5])


def test_decay_is_off_by_default_and_multiplies_when_on():
    df = interactions([(1, 1, "planned", None, 180), (1, 2, "completed", None, 0)])
    assert list(interaction_weights(df)) == [0.5, 1.0]
    assert interaction_weights(df, half_life_days=180, now=NOW).tolist() == pytest.approx([0.25, 1.0])


def test_bad_parameters_fail():
    df = interactions(ANYA_ROWS)
    with pytest.raises(ValueError):
        interaction_weights(df, score_coef=-0.1)
    with pytest.raises(ValueError):
        interaction_weights(df, clip=(1.2, 1.5))
    with pytest.raises(ValueError):
        interaction_weights(df, half_life_days=0)
    with pytest.raises(ValueError):
        interaction_weights(df, half_life_days=180, decay_floor=0)
    with pytest.raises(ValueError):
        interaction_weights(df, status_weights={**{s: 1.0 for s in df.status}, "dropped": -1.0})
