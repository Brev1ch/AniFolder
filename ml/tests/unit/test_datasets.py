import pandas as pd

from app.training import datasets


def test_normalize_statuses_dates_and_unknown_status():
    raw = pd.DataFrame({
        "user_id": [1] * 7, "anime_id": range(7),
        "status": ["COMPLETED", "REPEATING", "CURRENT", "PLANNING", "PAUSED", "DROPPED", "UNKNOWN"],
        "score": pd.array([8, None, None, None, None, 2, None], dtype="Int8"),
        "updated_at": pd.array([1, None, 1, 1, 1, 1, 1], dtype="Int64"),
    })
    result = datasets.normalize_anilist(raw)
    assert result.status.tolist() == ["completed", "completed", "watching", "planned", "on_hold", "dropped"]
    assert result.updated_at.iloc[0] == pd.Timestamp("1970-01-01T00:00:01Z")
    assert pd.isna(result.updated_at.iloc[1])
    assert list(result.columns) == datasets.INTERACTION_COLUMNS


def test_catalog_mapping_separates_users_and_drops_unknown_titles():
    original = pd.DataFrame({"user_id": [1, 2], "anime_id": [100, 200]})
    result = datasets.to_catalog_ids(original, pd.Series({100: 10}))
    assert result.to_dict("records") == [{"user_id": -1, "anime_id": 10}]
    assert str(result.anime_id.dtype) == "int64"
    assert original.user_id.tolist() == [1, 2]


def test_filter_repeats_until_remaining_users_and_items_meet_thresholds():
    df = pd.DataFrame([(1, 1), (1, 2), (2, 2), (2, 3), (3, 3)], columns=["user_id", "anime_id"])
    assert datasets.filter_interactions(df, 2, 2).empty


def test_full_loader_keeps_newcomers_and_dropped(monkeypatch, tmp_path):
    site = pd.DataFrame({"user_id": [1], "anime_id": [10], "status": ["dropped"],
                         "score": pd.array([None], dtype="Int8"),
                         "updated_at": pd.to_datetime(["2026-01-01"], utc=True)})
    external = site.assign(anime_id=100, status="completed")
    monkeypatch.setattr(datasets, "load_site", lambda engine: site)
    monkeypatch.setattr(datasets, "load_anilist", lambda path: external)
    monkeypatch.setattr(datasets, "load_catalog_mapping", lambda engine: pd.Series({100: 10}))
    full = datasets.load_interactions(None, tmp_path)
    assert full.user_id.tolist() == [1, -1]
    assert full.status.tolist() == ["dropped", "completed"]
    assert full.anime_id.tolist() == [10, 10]
    assert datasets.load_training_data(None, tmp_path).empty
    pd.testing.assert_frame_equal(datasets.load_interactions(None, None), site)
