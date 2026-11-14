import numpy as np
import pandas as pd
import pytest

from app.recsys import als


def data():
    weighted = pd.DataFrame([(-10, 100, 1.0), (7, 200, 0.5), (7, 300, 1.5),
                             (900, 400, 1.0), (-10, 999, 0.0)],
                            columns=["user_id", "anime_id", "weight"])
    # 200 и 300 отсутствуют в положительных взаимодействиях -10, но уже
    # присутствуют в полном списке (например, низкая оценка и dropped).
    history = pd.concat([weighted[["user_id", "anime_id"]],
                         pd.DataFrame([(-10, 200), (-10, 300)], columns=["user_id", "anime_id"])])
    return weighted, history


def test_matrix_orientation_id_mapping_and_confidence(monkeypatch):
    captured = {}

    class FakeALS:
        def __init__(self, **params):
            captured["params"] = params

        def fit(self, matrix, show_progress):
            captured["matrix"] = matrix.toarray()
            self.user_factors = np.ones((matrix.shape[0], 2), dtype=np.float32)
            self.item_factors = np.ones((matrix.shape[1], 2), dtype=np.float32)

    monkeypatch.setattr(als, "AlternatingLeastSquares", FakeALS)
    weighted, history = data()
    model = als.ALSRecommender(factors=2, alpha=20).fit(weighted, history=history)
    assert model.user_ids_.tolist() == [-10, 7, 900]
    assert model.item_ids_.tolist() == [100, 200, 300, 400]
    assert captured["params"]["alpha"] == 1.0  # не умножаем confidence дважды
    np.testing.assert_array_equal(captured["matrix"], [[21, 0, 0, 0], [0, 11, 31, 0], [0, 0, 0, 21]])
    assert model.recommend(-10, 10) == [400]  # полная история, включая удалённые веса
    assert model.recommend(900, 2) == [100, 200]  # ничьи по внешнему ID
    assert model.recommend(123456) == []


def test_real_fit_and_artifact_roundtrip(tmp_path):
    weighted, history = data()
    model = als.ALSRecommender(factors=3, iterations=4).fit(weighted, history=history)
    assert np.isfinite(model.user_factors_).all()
    assert np.any(model.item_factors_ != 0)
    expected = model.recommend_many([-10, 7, 900, 42], 10)
    assert expected[-10] == [400]
    path = tmp_path / "model.npz"
    model.save(path, metadata={"cutoff": "2026-09-02T00:34:23Z"})
    loaded = als.ALSRecommender.load(path)
    assert loaded.recommend_many([-10, 7, 900, 42], 10) == expected
    np.testing.assert_array_equal(model.user_factors_, loaded.user_factors_)
    assert loaded.params == model.params
    assert loaded.metadata_ == {"cutoff": "2026-09-02T00:34:23Z"}
    assert not path.with_name(path.name + ".tmp").exists()


def test_als_learns_cooccurrence_between_titles():
    # У двух групп непересекающиеся вкусы. У пользователя 1 известен только
    # первый тайтл группы A; второй должен опередить тайтлы группы B.
    rows = [(1, 10, 1.0)]
    rows += [(u, a, 1.0) for u in range(2, 12) for a in (10, 20)]
    rows += [(u, a, 1.0) for u in range(12, 22) for a in (30, 40)]
    df = pd.DataFrame(rows, columns=["user_id", "anime_id", "weight"])
    model = als.ALSRecommender(factors=2, iterations=20).fit(df, history=df)
    assert model.recommend(1, 1) == [20]


def test_all_candidates_seen_and_unknown_user_return_empty():
    weighted, history = data()
    history = pd.concat([history, pd.DataFrame([(-10, 400)], columns=["user_id", "anime_id"])])
    model = als.ALSRecommender(factors=2, iterations=2).fit(weighted, history=history)
    assert model.recommend(-10) == []
    assert model.recommend(999999) == []


@pytest.mark.parametrize("weight", [-1, np.nan, np.inf])
def test_bad_weights_fail(weight):
    weighted, history = data()
    weighted.loc[0, "weight"] = weight
    with pytest.raises(ValueError, match="weight"):
        als.ALSRecommender().fit(weighted, history=history)


def test_empty_and_duplicate_training_fail():
    weighted, history = data()
    with pytest.raises(ValueError, match="положительных"):
        als.ALSRecommender().fit(weighted.assign(weight=0.0), history=history)
    with pytest.raises(ValueError, match="повтор"):
        als.ALSRecommender().fit(pd.concat([weighted, weighted]), history=history)


@pytest.mark.parametrize("k", [0, -1, 1.5, True])
def test_invalid_k_fails(k):
    model = als.ALSRecommender()
    with pytest.raises(ValueError, match="k"):
        model.recommend(1, k)
    with pytest.raises(ValueError, match="k"):
        model.recommend_many([], k)


def test_untrained_model_fails_explicitly(tmp_path):
    model = als.ALSRecommender()
    with pytest.raises(RuntimeError, match="обучите"):
        model.recommend(1)
    with pytest.raises(RuntimeError, match="обучите"):
        model.save(tmp_path / "model.npz")
