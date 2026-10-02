from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select

from nordic_signals.http import FetchedResponse
from nordic_signals.store import database_url


def response(body: bytes, second: int = 0) -> FetchedResponse:
    return FetchedResponse("GET", "https://example.no/x", 200, "application/json", body,
                           datetime(2026, 10, 2, 8, 0, second, tzinfo=timezone.utc))


def utc(dt: datetime) -> datetime:
    """SQLite hands back naive UTC datetimes, PostgreSQL aware ones."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


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
    row = store.get("no_short_totals", isin="NO1", date=date(2026, 10, 1))
    assert row["short_pct"] == 1.5 and row["issuer_name"] == "New name"  # mutable columns
    assert utc(row["first_seen_at"]) == datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc)
    assert utc(row["last_seen_at"]) == datetime(2026, 10, 2, 8, 0, 30, tzinfo=timezone.utc)
    assert (row["first_fetch_id"], row["last_fetch_id"]) == (first, second)


def test_immutable_columns_keep_their_first_value(store):
    fetch = store.record_fetch("test", response(b"a"))
    store.upsert("newsweb_messages", [{"message_id": 1, "title": "v1", "published_at": "2026-10-01T10:00:00Z"}],
                 fetch_id=fetch)
    store.upsert("newsweb_messages", [{"message_id": 1, "title": "v2", "published_at": "2026-10-01T11:00:00Z"}],
                 fetch_id=fetch)

    row = store.get("newsweb_messages", message_id=1)
    assert row["title"] == "v2"  # title is mutable
    assert utc(row["published_at"]) == datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)  # publication time is not


def test_values_are_coerced_to_column_types(store):
    fetch = store.record_fetch("test", response(b"a"))
    store.upsert("se_insider_trades", [{
        "row_hash": "h1", "published_at": "2026-10-01T20:49:19+02:00", "transaction_date": "2026-09-30",
        "volume": 2000.0, "price": None, "isin": "", "is_first_report": True,
    }], fetch_id=fetch)

    row = store.get("se_insider_trades", row_hash="h1")
    assert utc(row["published_at"]) == datetime(2026, 10, 1, 18, 49, 19, tzinfo=timezone.utc)
    assert row["transaction_date"] == date(2026, 9, 30)
    assert row["is_first_report"] is True and row["price"] is None
    assert row["isin"] == ""  # empty text stays empty; only typed columns turn "" into NULL


def test_raw_bodies_are_stored_once_and_round_trip(store):
    a = store.record_fetch("test", response(b"same body"))
    b = store.record_fetch("test", response(b"same body"))

    assert a != b
    assert store.scalar(select(func.count()).select_from(store.table("blobs"))) == 1
    assert store.blob(store.get("fetches", id=a)["sha256"]) == b"same body"


def test_lists_are_stored_as_json(store):
    fetch = store.record_fetch("test", response(b"a"))
    store.upsert("newsweb_messages", [{"message_id": 1, "category_ids": [1102], "markets": ["XOSL"]}],
                 fetch_id=fetch)
    row = store.get("newsweb_messages", message_id=1)
    assert (row["category_ids"], row["markets"]) == ([1102], ["XOSL"])


def test_large_batches_are_split(store):
    fetch = store.record_fetch("test", response(b"a"))
    rows = [{"isin": f"NO{i}", "date": "2026-10-01", "short_pct": 0.5} for i in range(1234)]
    assert store.upsert("no_short_totals", rows, fetch_id=fetch).inserted == 1234
    assert store.table_counts()["no_short_totals"] == 1234


def test_rows_without_a_key_are_rejected(store):
    fetch = store.record_fetch("test", response(b"a"))
    with pytest.raises(ValueError):
        store.upsert("no_short_totals", [{"isin": "NO1", "date": None}], fetch_id=fetch)


def test_runs_are_logged(store):
    run = store.start_run("demo")
    store.finish_run(run, ok=True, summary={"fetches": 1})
    (latest,) = store.last_runs()
    assert latest["source"] == "demo" and latest["ok"] is True
    assert latest["summary"] == {"fetches": 1}


@pytest.mark.parametrize("value, expected", [
    ("postgresql://u:p@postgres.railway.internal:5432/railway",
     "postgresql+psycopg://u:p@postgres.railway.internal:5432/railway"),
    ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("data/x.sqlite", "sqlite:///data/x.sqlite"),
    ("sqlite://", "sqlite://"),
])
def test_database_url(value, expected):
    assert database_url(value) == expected


def test_database_url_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/db")
    assert database_url(None) == "postgresql+psycopg://u@h/db"
    monkeypatch.delenv("DATABASE_URL")
    assert database_url(None) == "sqlite:///data/signals.sqlite"
