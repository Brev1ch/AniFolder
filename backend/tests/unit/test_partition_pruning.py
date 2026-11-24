"""Cursor correctness and physical partition pruning on PostgreSQL.

Mixed insertion order deliberately makes ID order differ from timestamp order.
"""
from datetime import timedelta

import pytest
from sqlalchemy import event, text

from app.models.community import Comment, Topic
from app.models.enums import ActivityType
from app.models.library import UserActivity
from app.models.user import User
from app.services.cursor import decode_cursor, encode_cursor
from tests.api_context import ApiTestContext


@pytest.mark.parametrize("kind", ["activity", "comments"])
@pytest.mark.parametrize("limit", [1, 2, 3, 20])
async def test_cursor_ties_across_partitions_and_pruning(
    api: ApiTestContext, kind: str, limit: int
) -> None:
    user = User(username="cursor_probe", email="cursor_probe@example.com", password_hash="x")
    api.session.add(user)
    await api.session.flush()
    # In January–August the normal 3-month horizon may not include next year.
    # Extend partitions only in this isolated test transaction when necessary.
    if kind == "comments" and await api.session.scalar(text(
        "SELECT to_regclass('comments_p' || to_char(now() + interval '1 year', 'YYYY'))"
    )) is None:
        await api.session.execute(text("SELECT ensure_partitions(12)"))
    period = "month" if kind == "activity" else "year"
    boundary = await api.session.scalar(text(
        f"SELECT date_trunc('{period}', now()) + interval '1 {period}'"
    ))
    # All rows are in explicit partitions created by migration 0001/ensure_partitions.
    times = [boundary, boundary + timedelta(seconds=1), boundary - timedelta(microseconds=1)] * 3
    if kind == "activity":
        table = "user_activity"
        owner = user.id
        rows = [
            UserActivity(user_id=owner, type=ActivityType.SCORED, payload={"score": 5}, created_at=t)
            for t in times
        ]
        url = "/api/v1/users/cursor_probe/activity"
        owner_column = "user_id"
    else:
        topic = Topic(author_id=user.id, title="Cursor probe", body="Synthetic pagination data")
        api.session.add(topic)
        await api.session.flush()
        table = "comments"
        owner = topic.id
        rows = [
            Comment(topic_id=owner, author_id=None, body=f"Comment {i}", created_at=t)
            for i, t in enumerate(times)
        ]
        url = f"/api/v1/topics/{owner}/comments"
        owner_column = "topic_id"
    api.session.add_all(rows)
    await api.session.flush()
    physical_rows = (await api.session.execute(text(
        f"SELECT id, created_at, tableoid::regclass::text AS partition "
        f"FROM {table} WHERE {owner_column}=:owner"
    ), {"owner": owner})).all()
    assert len({r.partition for r in physical_rows}) == 2
    assert all(not r.partition.endswith("_default") for r in physical_rows)
    newest_partition = max(physical_rows, key=lambda r: r.created_at).partition
    expected = sorted(rows, key=lambda r: (r.created_at, r.id), reverse=True)
    cursor = None
    seen = []
    page_lengths = []
    for start in range(0, len(expected), limit):
        params = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = await api.client.get(url, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        expected_page = expected[start:start + limit]
        assert [item["id"] for item in page["items"]] == [r.id for r in expected_page]
        seen.extend(item["id"] for item in page["items"])
        page_lengths.append(len(page["items"]))
        cursor = page["next_cursor"]
        if start + limit < len(expected):
            assert cursor is not None
            assert decode_cursor(cursor) == (expected_page[-1].created_at, expected_page[-1].id)
        else:
            assert cursor is None
    assert seen == [r.id for r in expected]
    assert len(seen) == len(set(seen)) == 9
    assert page_lengths[0] == min(limit, 9)
    assert page_lengths[-1] == (9 % limit or limit)

    # A cursor after the oldest row must return an empty final page and prune
    # the newer physical partition. Capture the actual service query, not a replica.
    captured = []
    connection = await api.session.connection()
    def capture(conn, db_cursor, statement, parameters, context, executemany):
        if f"FROM {table} " in statement and statement.lstrip().startswith("SELECT"):
            captured.append((statement, parameters))
    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        response = await api.client.get(url, params={
            "limit": limit,
            "cursor": encode_cursor(expected[-1].created_at, expected[-1].id),
        })
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}
    assert len(captured) == 1
    sql, parameters = captured[0]
    raw = await connection.get_raw_connection()
    plan = await raw.driver_connection.fetchval("EXPLAIN (FORMAT JSON) " + sql, *parameters)
    def relations(node):
        names = {node["Relation Name"]} if "Relation Name" in node else set()
        for child in node.get("Plans", []):
            names.update(relations(child))
        return names
    assert newest_partition not in relations(plan[0]["Plan"])
