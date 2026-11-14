import math

import pandas as pd
import pytest

from app.training.evaluate import (
    chronological_split,
    cutoff_split,
    default_cutoff,
    evaluate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    relevant_items,
    time_split,
)
from app.training.datasets import filter_interactions


def interactions(rows):
    """rows: (user_id, anime_id, status, score, день)."""
    df = pd.DataFrame(rows, columns=["user_id", "anime_id", "status", "score", "day"])
    df["score"] = df["score"].astype("Int8")
    df["updated_at"] = pd.Timestamp("2026-01-01", tz="UTC") + pd.to_timedelta(df.pop("day"), unit="D")
    return df


def test_chronological_split_boundaries_undated_and_new_users():
    df = interactions([(1, 10, "completed", 8, 0), (1, 11, "completed", 8, 9),
                       (1, 12, "completed", 8, 10), (2, 13, "planned", None, 19),
                       (3, 14, "completed", 9, 20), (4, 15, "completed", 9, 21)])
    df.loc[df.anime_id == 10, "updated_at"] = pd.NaT
    start = pd.Timestamp("2026-01-01", tz="UTC")
    train, validation, test = chronological_split(
        df.sample(frac=1, random_state=0), validation_start=start + pd.Timedelta(days=10),
        test_start=start + pd.Timedelta(days=20))
    assert set(train.anime_id) == {10, 11}
    assert set(validation.anime_id) == {12, 13}
    assert set(test.anime_id) == {14, 15}
    assert sum(map(len, (train, validation, test))) == len(df)
    assert validation.updated_at.notna().all() and test.updated_at.notna().all()


def test_future_interactions_do_not_rescue_rare_training_items():
    df = interactions([(1, 10, "completed", 8, 0), (1, 20, "completed", 8, 0),
                       (2, 20, "completed", 8, 0), (2, 10, "completed", 8, 10),
                       (3, 30, "planned", None, 20)])
    history, validation, test = chronological_split(
        df, validation_start=pd.Timestamp("2026-01-11", tz="UTC"),
        test_start=pd.Timestamp("2026-01-21", tz="UTC"))
    training = filter_interactions(history, min_user_items=1, min_item_users=2)
    assert set(training.anime_id) == {20}
    assert set(history.anime_id) == {10, 20}
    assert relevant_items(validation) == {2: {10}}  # не удаляем недоступную модели цель
    assert relevant_items(test) == {3: {30}}  # новичок и новый тайтл сохраняются


@pytest.mark.parametrize("validation_start,test_start", [
    ("2026-02-01Z", "2026-01-01Z"),
    ("2026-01-01Z", "2026-01-01Z"),
    ("2026-01-01", "2026-02-01Z"),
    (None, "2026-02-01Z"),
])
def test_chronological_split_rejects_invalid_boundaries(validation_start, test_start):
    def timestamp(value):
        return pd.Timestamp(value.replace("Z", "T00:00:00Z")) if value else pd.NaT
    df = interactions([(1, 1, "completed", 8, 0)])
    with pytest.raises(ValueError):
        chronological_split(df, validation_start=timestamp(validation_start), test_start=timestamp(test_start))


def test_chronological_split_allows_empty_periods():
    df = interactions([(1, 1, "completed", 8, 0)])
    for source in (df, df.iloc[:0]):
        train, validation, test = chronological_split(
            source, validation_start=pd.Timestamp("2026-02-01", tz="UTC"),
            test_start=pd.Timestamp("2026-03-01", tz="UTC"))
        assert len(train) == len(source)
        assert validation.empty and test.empty


def test_chronological_split_compares_absolute_time_across_timezones():
    df = interactions([(1, 1, "completed", 8, 0)])
    train, validation, test = chronological_split(
        df, validation_start=pd.Timestamp("2026-01-01T03:00:00+03:00"),
        test_start=pd.Timestamp("2026-01-02T03:00:00+03:00"))
    assert train.empty and test.empty
    assert validation.anime_id.tolist() == [1]


def test_chronological_split_rejects_dates_without_timezone():
    df = interactions([(1, 1, "completed", 8, 0)])
    df["updated_at"] = df.updated_at.dt.tz_localize(None)
    with pytest.raises(ValueError, match="updated_at"):
        chronological_split(df, validation_start=pd.Timestamp("2026-02-01", tz="UTC"),
                            test_start=pd.Timestamp("2026-03-01", tz="UTC"))


# Пример из объяснения: в тесте у Ани {Clannad, Mushishi, Monster},
# модель советует Monster, Naruto, Mushishi, Bleach, One Piece.
CLANNAD, MUSHISHI, MONSTER, NARUTO, BLEACH, ONE_PIECE = 1, 2, 3, 4, 5, 6
ANYA_RELEVANT = {CLANNAD, MUSHISHI, MONSTER}
ANYA_RECS = [MONSTER, NARUTO, MUSHISHI, BLEACH, ONE_PIECE]


def test_metrics_on_hand_example():
    assert precision_at_k(ANYA_RECS, ANYA_RELEVANT, 5) == pytest.approx(2 / 5)
    assert recall_at_k(ANYA_RECS, ANYA_RELEVANT, 5) == pytest.approx(2 / 3)
    # DCG = 1/log2(2) + 1/log2(4) = 1.5; идеал: три попадания в начале
    ideal = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(ANYA_RECS, ANYA_RELEVANT, 5) == pytest.approx(1.5 / ideal)
    assert ndcg_at_k(ANYA_RECS, ANYA_RELEVANT, 5) == pytest.approx(0.704, abs=1e-3)


def test_ndcg_rewards_hits_higher_in_list():
    top = ndcg_at_k([MONSTER, NARUTO, BLEACH], {MONSTER}, 3)
    bottom = ndcg_at_k([NARUTO, BLEACH, MONSTER], {MONSTER}, 3)
    assert top == pytest.approx(1.0)
    assert bottom == pytest.approx(0.5)


def test_perfect_and_empty_recommendations():
    assert precision_at_k([1, 2], {1, 2}, 2) == 1.0
    assert recall_at_k([1, 2], {1, 2}, 2) == 1.0
    assert ndcg_at_k([1, 2], {1, 2}, 2) == pytest.approx(1.0)
    assert precision_at_k([3, 4], {1, 2}, 2) == 0.0
    assert ndcg_at_k([], {1, 2}, 2) == 0.0


def test_only_first_k_recommendations_count():
    assert precision_at_k([NARUTO, MONSTER], {MONSTER}, 1) == 0.0
    assert recall_at_k([NARUTO, MONSTER], {MONSTER}, 1) == 0.0


def test_ndcg_is_one_when_fewer_relevant_than_k_all_found():
    # Идеальный список для одного релевантного тайтла — одно попадание на 1-м месте
    assert ndcg_at_k([MONSTER, NARUTO, BLEACH], {MONSTER}, 3) == pytest.approx(1.0)


def test_short_recommendation_list_is_penalized_in_precision():
    # Модель вернула 1 тайтл вместо 5: пустые места считаются промахами
    assert precision_at_k([MONSTER], {MONSTER}, 5) == pytest.approx(1 / 5)


@pytest.mark.parametrize("metric", [precision_at_k, recall_at_k, ndcg_at_k])
@pytest.mark.parametrize("k", [0, -1, 1.5, True])
def test_metrics_reject_invalid_k(metric, k):
    with pytest.raises(ValueError, match="k"):
        metric([], set(), k)


@pytest.mark.parametrize("metric", [precision_at_k, recall_at_k, ndcg_at_k])
@pytest.mark.parametrize("relevant", [{7}, set()])
def test_metrics_reject_duplicate_recommendations(metric, relevant):
    with pytest.raises(ValueError, match="повтор"):
        metric([7, 7], relevant, 2)


def test_metrics_ignore_duplicates_outside_top_k():
    assert evaluate({1: [7, 8, 7]}, {1: {7}}, k=2)["recall@2"] == 1.0


def test_evaluate_rejects_duplicate_recommendations():
    with pytest.raises(ValueError, match="повтор"):
        evaluate({1: [7, 7]}, {1: {7}}, k=2)


@pytest.mark.parametrize("k", [0, -1, 1.5, True])
def test_evaluate_rejects_invalid_k_even_without_users(k):
    with pytest.raises(ValueError, match="k"):
        evaluate({}, {}, k=k)


def test_time_split_moves_latest_records_to_test():
    df = interactions(
        [(1, anime, "completed", 8, day) for anime, day in zip(range(10, 20), range(10))]
        + [(2, anime, "completed", 8, day) for anime, day in zip(range(10, 15), [4, 3, 2, 1, 0])]
    )
    train, test = time_split(df, test_fraction=0.2)

    assert sorted(test[test.user_id == 1].anime_id) == [18, 19]  # 2 из 10, самые поздние
    assert sorted(test[test.user_id == 2].anime_id) == [10]  # 1 из 5; у пользователя 2 даты в обратном порядке
    assert len(train) + len(test) == len(df)
    assert not set(zip(train.user_id, train.anime_id)) & set(zip(test.user_id, test.anime_id))


def test_time_split_test_is_never_older_than_train():
    df = interactions([(1, anime, "completed", 8, (anime * 7) % 11) for anime in range(11)])
    train, test = time_split(df, test_fraction=0.3)
    assert len(test) == 3
    assert test.updated_at.min() >= train.updated_at.max()


def test_time_split_breaks_ties_by_anime_id():
    df = interactions([(1, anime, "completed", 8, 0) for anime in [5, 3, 9, 1, 7]])
    first = time_split(df)[1]
    second = time_split(df.sample(frac=1, random_state=0))[1]
    assert list(first.anime_id) == list(second.anime_id) == [9]


def test_time_split_keeps_records_without_time_in_train():
    df = interactions([(1, anime, "completed", 8, anime) for anime in range(5)])
    df.loc[df.anime_id == 4, "updated_at"] = pd.NaT  # без времени самая «поздняя» по anime_id
    train, test = time_split(df)
    assert list(test.anime_id) == [3]
    assert 4 in set(train.anime_id)


def test_time_split_handles_float_rounding():
    # 100 * 0.29 = 28.999… в float, должно получиться 29
    df = interactions([(1, anime, "completed", 8, anime) for anime in range(100)])
    assert len(time_split(df, test_fraction=0.29)[1]) == 29


@pytest.mark.parametrize("dated_count", [0, 1])
def test_time_split_does_not_fill_test_with_undated_records(dated_count):
    df = interactions([(1, anime, "completed", 8, anime) for anime in range(10)])
    df.loc[df.anime_id >= dated_count, "updated_at"] = pd.NaT
    train, test = time_split(df)
    assert len(test) == dated_count  # целевые 2 записи ограничены числом известных дат
    assert test.updated_at.notna().all()
    assert len(train) + len(test) == len(df)
    assert set(train.anime_id).isdisjoint(test.anime_id)
    assert train.updated_at.isna().sum() == 10 - dated_count


def test_time_split_rejects_bad_fraction():
    df = interactions([(1, 1, "completed", 8, 0)])
    with pytest.raises(ValueError):
        time_split(df, test_fraction=1.0)


def test_default_cutoff_counts_days_back_from_latest_record():
    df = interactions([(1, 1, "completed", 8, 0), (1, 2, "completed", 8, 100)])
    assert default_cutoff(df, days=28) == pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=72)


def test_cutoff_split_uses_one_date_for_everyone():
    # Записи до 90-го дня — прошлое, с 90-го (включительно) — будущее
    df = interactions(
        [(1, anime, "completed", 8, day) for anime, day in zip(range(10, 17), [0, 10, 20, 30, 40, 90, 95])]
        + [(2, anime, "completed", 8, day) for anime, day in zip(range(20, 27), [50, 60, 70, 80, 85, 89, 100])]
    )
    train, test = cutoff_split(df, days=10)  # последняя запись — день 100, отсечение — день 90

    assert sorted(test[test.user_id == 1].anime_id) == [15, 16]  # день 90 уже тест
    assert sorted(test[test.user_id == 2].anime_id) == [26]
    assert test.updated_at.min() >= train.updated_at.max()
    assert len(train) + len(test) == len(df)


def test_cutoff_split_test_only_for_users_with_enough_history():
    df = interactions(
        [(1, anime, "completed", 8, day) for anime, day in zip(range(10, 16), [0, 1, 2, 3, 4, 50])]
        + [(2, anime, "completed", 8, day) for anime, day in zip(range(20, 26), [0, 1, 2, 3, 50, 50])]
        + [(3, 30, "completed", 8, 50)]  # новичок: только записи после отсечения
    )
    train, test = cutoff_split(df, cutoff=pd.Timestamp("2026-02-01", tz="UTC"), min_train=5)

    assert set(test.user_id) == {1}  # у пользователя 2 до отсечения 4 записи
    # будущие записи пользователей 2 и 3 не попадают и в train
    assert not (train.updated_at >= pd.Timestamp("2026-02-01", tz="UTC")).any()
    assert set(train[train.user_id == 2].anime_id) == {20, 21, 22, 23}  # прошлое остаётся для обучения
    assert 3 not in set(train.user_id)


def test_cutoff_split_keeps_records_without_time_in_train():
    df = interactions([(1, anime, "completed", 8, day) for anime, day in zip(range(6), [0, 1, 2, 3, 4, 50])])
    df.loc[df.anime_id == 0, "updated_at"] = pd.NaT
    train, test = cutoff_split(df, days=28)
    assert 0 in set(train.anime_id)
    assert list(test.anime_id) == [5]


def test_cutoff_split_rejects_bad_arguments():
    df = interactions([(1, 1, "completed", 8, 0)])
    with pytest.raises(ValueError):
        cutoff_split(df, days=0)
    with pytest.raises(ValueError):
        cutoff_split(df, min_train=0)


def test_relevant_items_excludes_dropped_and_low_scores():
    test = interactions(
        [
            (1, 10, "completed", 9, 0),
            (1, 11, "completed", None, 0),  # без оценки — считается
            (1, 12, "planned", None, 0),  # в планах — считается
            (1, 13, "dropped", None, 0),  # брошено
            (1, 14, "completed", 4, 0),  # низкая оценка
            (1, 15, "watching", 5, 0),  # ровно порог — считается
            (2, 20, "dropped", 9, 0),  # брошено даже с высокой оценкой
        ]
    )
    assert relevant_items(test) == {1: {10, 11, 12, 15}}


def test_evaluate_averages_over_users_and_penalizes_missing():
    relevant = {1: ANYA_RELEVANT, 2: {MONSTER}, 3: set()}
    recommendations = {1: ANYA_RECS, 3: [MONSTER]}  # пользователю 2 модель ничего не дала

    result = evaluate(recommendations, relevant, k=5)

    assert result["users"] == 2  # у пользователя 3 нечего угадывать, он не считается
    assert result["precision@5"] == pytest.approx((2 / 5 + 0) / 2)
    assert result["recall@5"] == pytest.approx((2 / 3 + 0) / 2)
    assert result["ndcg@5"] == pytest.approx(ndcg_at_k(ANYA_RECS, ANYA_RELEVANT, 5) / 2)


def test_evaluate_coverage_counts_distinct_titles_in_top_k():
    relevant = {1: {1}, 2: {2}, 3: {3}, 4: set()}
    recommendations = {
        1: [1, 2, 9],  # 9 за пределами топ-2 — не считается
        2: [2, 1],
        3: [3, 4],
        4: [7, 8],  # пользователь без релевантных в метриках не участвует
    }
    assert evaluate(recommendations, relevant, k=2)["coverage@2"] == 4  # {1, 2, 3, 4}


def test_evaluate_without_relevant_users_fails():
    with pytest.raises(ValueError):
        evaluate({1: [1]}, {1: set()}, k=5)
