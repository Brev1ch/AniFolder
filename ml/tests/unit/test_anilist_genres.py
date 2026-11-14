from unittest.mock import Mock

import pytest

from app.training.anilist_genres import fetch_genres, load_item_genres, read_cache


def page(items, has_next=False):
    return {"Page": {"media": items, "pageInfo": {"hasNextPage": has_next}}}


def test_cache_normalizes_genres_and_distinguishes_missing_from_empty(tmp_path):
    client = Mock()
    client.query.return_value = page([{"id": 1, "genres": ["Drama", "Action", "Drama"]},
                                     {"id": 2, "genres": []}])
    path = tmp_path / "genres.json"
    result = fetch_genres(client, [3, 2, 1, 1], path)
    assert result["items"]["1"]["genres"] == ["Action", "Drama"]
    assert result["items"]["2"]["genres"] == []
    assert result["items"]["3"]["genres"] is None
    assert result["items"]["1"]["fetched_at"]
    assert load_item_genres(path) == {1: {"Action", "Drama"}}
    fetch_genres(client, [1, 2, 3], path)
    assert client.query.call_count == 1
    client.query.return_value = page([{"id": 3, "genres": ["Comedy"]}])
    fetch_genres(client, [1, 2, 3], path, retry_missing=True)
    assert client.query.call_args.args[1] == {"ids": [3]}
    assert load_item_genres(path)[3] == {"Comedy"}


def test_resume_after_failed_batch_does_not_skip_ids(tmp_path):
    client = Mock()
    client.query.side_effect = [page([{"id": i, "genres": ["Drama"]} for i in range(1, 51)]),
                                RuntimeError("API unavailable")]
    path = tmp_path / "genres.json"
    with pytest.raises(RuntimeError):
        fetch_genres(client, range(1, 52), path)
    assert len(read_cache(path)["items"]) == 50
    client.query.side_effect = None
    client.query.return_value = page([{"id": 51, "genres": ["Comedy"]}])
    fetch_genres(client, range(1, 52), path)
    assert client.query.call_args.args[1] == {"ids": [51]}
    assert len(read_cache(path)["items"]) == 51


@pytest.mark.parametrize("reply", [
    {"Page": None},
    page([{"id": 99, "genres": []}]), page([{"id": 1, "genres": None}]),
    page([{"id": 1, "genres": []}, {"id": 1, "genres": []}]),
])
def test_invalid_response_does_not_checkpoint_batch(tmp_path, reply):
    client = Mock()
    client.query.return_value = reply
    path = tmp_path / "genres.json"
    with pytest.raises(RuntimeError):
        fetch_genres(client, [1], path)
    assert not path.exists()


def test_missing_cache_fails_explicitly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_item_genres(tmp_path / "absent.json")


def test_unreliable_page_info_does_not_reject_complete_response(tmp_path):
    client = Mock()
    client.query.return_value = page([{"id": 1, "genres": ["Drama"]}], has_next=True)
    path = tmp_path / "genres.json"
    fetch_genres(client, [1], path)
    assert load_item_genres(path) == {1: {"Drama"}}
