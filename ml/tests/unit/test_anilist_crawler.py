from unittest.mock import Mock

import httpx
import pandas as pd
import pytest

from app.training import anilist_crawler as crawler


@pytest.fixture
def client(monkeypatch):
    instance = crawler.AniListClient(max_retries=2)
    instance.http.close()
    responses = []

    def respond(request):
        return responses.pop(0)

    instance.http = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(instance.limiter, "wait", lambda: None)
    monkeypatch.setattr(crawler.time, "sleep", lambda seconds: None)
    yield instance, responses
    instance.http.close()


def response(status=200, *, errors=None, data=None):
    return httpx.Response(status, json={"errors": errors, "data": data})


@pytest.mark.parametrize("http_status", [200, 404])
def test_only_explicit_list_not_found_is_skipped(client, http_status):
    api, queue = client
    queue.append(response(http_status, errors=[{"status": 404, "message": "Not Found"}]))
    with pytest.raises(crawler.UserUnavailable):
        api.user_entries(1)


@pytest.mark.parametrize("status", [200, 403])
def test_api_disabled_is_not_a_private_user(client, status):
    api, queue = client
    queue.append(response(status, errors=[{"status": 403, "message": "API disabled"}]))
    with pytest.raises((crawler.GraphQLError, httpx.HTTPStatusError)):
        api.user_entries(1)


def test_partial_data_with_errors_is_not_saved_as_complete(client):
    api, queue = client
    queue.append(response(errors=[{"status": 400, "message": "Invalid field"}],
                          data={"MediaListCollection": {"lists": []}}))
    with pytest.raises(crawler.GraphQLError):
        api.user_entries(1)


@pytest.mark.parametrize("first", [
    response(errors=[{"status": 503, "message": "Unavailable"}]),
    httpx.Response(503, text="Unavailable"),
    httpx.Response(429, headers={"Retry-After": "0"}),
    httpx.Response(200, text="not JSON"),
])
def test_temporary_errors_are_retried(client, first):
    api, queue = client
    queue.extend([first, response(data={"MediaListCollection": {"lists": []}})])
    assert api.user_entries(1) == []
    assert not queue


def test_html_http_error_does_not_become_json_error_or_user_skip(client):
    api, queue = client
    queue.append(httpx.Response(403, text="<html>Forbidden</html>"))
    with pytest.raises(httpx.HTTPStatusError):
        api.user_entries(1)


def test_exhausted_retries_fail_instead_of_skipping_user(client):
    api, queue = client
    queue.extend([httpx.Response(503), httpx.Response(503)])
    with pytest.raises(RuntimeError, match="2 попыток"):
        api.user_entries(1)


def test_null_collection_is_not_an_empty_list(client):
    api, queue = client
    queue.append(response(data={"MediaListCollection": None}))
    with pytest.raises(RuntimeError, match="MediaListCollection"):
        api.user_entries(1)


def test_parse_entries_skips_custom_lists_and_deduplicates():
    entry = {"mediaId": 10, "status": "CURRENT", "score": 0, "progress": 3, "updatedAt": 0}
    rows = crawler.parse_entries(1, {"lists": [
        {"entries": [entry, entry]},
        {"isCustomList": True, "entries": [dict(entry, mediaId=99)]},
    ]})
    assert rows == [{"user_id": 1, "anime_id": 10, "status": "CURRENT", "score": None,
                     "progress": 3, "updated_at": None}]


def test_failed_request_remains_pending_on_resume(tmp_path):
    path = tmp_path / "state.json"
    crawler.CrawlState(pending=[1, 2], activity_before=100).save(path)
    api = Mock()
    api.user_entries.side_effect = [[], crawler.GraphQLError([{"status": 400, "message": "Bad query"}])]
    with pytest.raises(crawler.GraphQLError):
        crawler.crawl(api, tmp_path, target_users=2, part_size=1)
    state = crawler.CrawlState.load(path)
    assert state.done == [1]
    assert state.pending == [2]
    assert state.skipped == 0
    api.user_entries.side_effect = None
    api.user_entries.return_value = []
    resumed = crawler.crawl(api, tmp_path, target_users=2, part_size=1)
    assert resumed.done == [1, 2]
    assert pd.read_parquet(tmp_path / "lists").empty
