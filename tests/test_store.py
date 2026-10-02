from datetime import datetime, timezone

import pytest

from nordic_signals.http import FetchedResponse


def response(body: bytes, second: int = 0) -> FetchedResponse:
    return FetchedResponse("GET", "https://example.no/x", 200, "application/json", body,
                           datetime(2026, 10, 2, 8, 0, second, tzinfo=timezone.utc))


def test_upsert_keeps_first_seen_and_refreshes_only_mutable_columns(store):
    first = store.record_fetch("test", response(b"a", 0))
    store.upsert("no_short_totals", [
        {"isin": "NO1", "date": "2026-10-01", "issuer_name": "Old name", "short_pct": 1.0, "short_shares": 10},
    ], fetch_id=first)

    second = store.record_fetch("test", response(b"b", 30))
    result = store.upsert("no_short_totals", [
        {"isin": "NO1", "date": "2026-10-01", "issuer_name": "New name", "short_pct": 1.5, "short_shares": 15},
        {"isin": "NO2", "date": "2026-10-01", "issuer_name": "Other", "short_pct": 0.6, "short_shares": 5},
    ], fetch_id=second)

    assert (result.inserted, result.updated) == (1, 1)
    row = store.conn.execute("SELECT * FROM no_short_totals WHERE isin = 'NO1'").fetchone()
    assert row["short_pct"] == 1.5 and row["issuer_name"] == "New name"  # mutable columns
    assert row["first_seen_at"] == "2026-10-02T08:00:00.000Z"
    assert row["last_seen_at"] == "2026-10-02T08:00:30.000Z"
    assert (row["first_fetch_id"], row["last_fetch_id"]) == (first, second)


def test_immutable_columns_keep_their_first_value(store):
    fetch = store.record_fetch("test", response(b"a"))
    store.upsert("newsweb_messages", [{"message_id": 1, "title": "v1", "published_at": "t1"}], fetch_id=fetch)
    store.upsert("newsweb_messages", [{"message_id": 1, "title": "v2", "published_at": "t2"}], fetch_id=fetch)

    row = store.conn.execute("SELECT title, published_at FROM newsweb_messages").fetchone()
    assert row["title"] == "v2"  # title is mutable
    assert row["published_at"] == "t1"  # publication time is not


def test_raw_bodies_are_stored_once_and_round_trip(store):
    a = store.record_fetch("test", response(b"same body"))
    b = store.record_fetch("test", response(b"same body"))

    assert a != b
    assert store.conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 1
    sha = store.conn.execute("SELECT sha256 FROM fetches WHERE id = ?", (a,)).fetchone()[0]
    assert store.blob(sha) == b"same body"


def test_lists_are_stored_as_json(store):
    fetch = store.record_fetch("test", response(b"a"))
    store.upsert("newsweb_messages", [{"message_id": 1, "category_ids": [1102], "markets": ["XOSL"]}],
                 fetch_id=fetch)
    row = store.conn.execute("SELECT category_ids, markets FROM newsweb_messages").fetchone()
    assert (row["category_ids"], row["markets"]) == ("[1102]", '["XOSL"]')


def test_rows_without_a_key_are_rejected(store):
    fetch = store.record_fetch("test", response(b"a"))
    with pytest.raises(ValueError):
        store.upsert("no_short_totals", [{"isin": "NO1", "date": None}], fetch_id=fetch)


def test_runs_are_logged(store):
    run = store.start_run("demo")
    store.finish_run(run, ok=True, summary={"fetches": 1})
    (latest,) = store.last_runs()
    assert latest["source"] == "demo" and latest["ok"] == 1
