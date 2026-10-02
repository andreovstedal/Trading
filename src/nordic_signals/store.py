"""SQLite storage: an append-only log of raw fetches plus parsed tables.

Two layers, so the advice formula can always be re-evaluated point-in-time:

* ``fetches`` and ``blobs`` keep every raw response exactly as received
  (content-addressed and zlib-compressed). Nothing in them is ever updated.
* The parsed tables hold one row per natural key. Each row records when it
  was first and last seen, so a backtest can ask "what did we know at time T"
  by filtering on ``first_seen_at``. Columns listed as ``mutable`` are
  refreshed when a row is seen again (for example a NewsWeb message that
  later gets a correction link); everything else keeps its first value.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .http import FetchedResponse


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[str, ...]
    key: tuple[str, ...]
    mutable: tuple[str, ...] = ()


def _spec(columns: str, key: str, mutable: str = "") -> TableSpec:
    return TableSpec(tuple(columns.split()), tuple(key.split()), tuple(mutable.split()))


TABLES: dict[str, TableSpec] = {
    # Euronext Oslo Børs NewsWeb
    "newsweb_categories": _spec("category_id name_no name_en", "category_id", "name_no name_en"),
    "newsweb_messages": _spec(
        "message_id news_id published_at issuer_id issuer_sign issuer_name title category_ids"
        " category_en markets instrument_id instrument_name correction_for_message_id"
        " corrected_by_message_id num_attachments is_test client_announcement_id",
        "message_id",
        "title category_ids category_en corrected_by_message_id num_attachments",
    ),
    "newsweb_bodies": _spec("message_id body attachments", "message_id", "body attachments"),
    "newsweb_attachments": _spec(
        "message_id attachment_id name sha256 content_type size",
        "message_id attachment_id",
        "name sha256 content_type size",
    ),
    # Finansinspektionen: insider register (marknadssok.fi.se) and short-selling register
    "se_insider_trades": _spec(
        "row_hash published_at issuer lei notifier pdmr position closely_associated is_correction"
        " correction_description is_first_report linked_to_share_program nature instrument_type"
        " instrument_name isin transaction_date volume volume_unit price currency venue status",
        "row_hash",
    ),
    "se_short_positions": _spec(
        "holder issuer isin position_pct position_date comment",
        "holder isin position_date",
        "issuer position_pct comment",
    ),
    "se_short_aggregate": _spec(
        "issuer lei total_pct position_date", "lei position_date", "issuer total_pct"
    ),
    # Finanstilsynet short-sale register (ssr.finanstilsynet.no)
    "no_short_totals": _spec(
        "isin date issuer_name short_pct short_shares", "isin date", "issuer_name short_pct short_shares"
    ),
    "no_short_positions": _spec(
        "isin date holder position_date short_pct short_shares",
        "isin date holder",
        "position_date short_pct short_shares",
    ),
    # MFN (Modular Finance News)
    "mfn_entities": _spec("slug entity_id name", "slug", "entity_id name"),
    "mfn_items": _spec(
        "news_id group_id entity_id issuer_name slug isins leis tickers lang type tags scopes"
        " title publish_date url html attachments",
        "news_id",
        "title tags html attachments",
    ),
    # Yahoo Finance chart API
    "price_bars": _spec(
        "symbol interval ts ts_utc currency open high low close adjclose volume",
        "symbol interval ts",
        "open high low close adjclose volume",
    ),
    "dividends": _spec("symbol ts ex_date amount currency", "symbol ts", "amount"),
    "splits": _spec("symbol ts ex_date numerator denominator", "symbol ts", "numerator denominator"),
    # Nordnet stock list (tradable universe plus daily observations)
    "instruments": _spec(
        "instrument_id isin symbol name long_name issuer_id issuer_name instrument_type currency"
        " exchange_country exchanges market_id identifier is_tradable is_shortable display_slug",
        "instrument_id",
        "isin symbol name long_name issuer_id issuer_name instrument_type currency exchange_country"
        " exchanges market_id identifier is_tradable is_shortable display_slug",
    ),
    "nordnet_observations": _spec(
        "instrument_id observed_at tick_at realtime last open high low close bid ask spread_pct"
        " diff_pct turnover turnover_volume market_cap pe pb ps eps dividend_per_share"
        " dividend_yield number_of_owners statistics_at report_date report_type ex_date"
        " dividend_date dividend_amount dividend_currency yield_1w yield_1m yield_3m yield_ytd"
        " yield_1y",
        "instrument_id observed_at",
    ),
}

BOOKKEEPING = ("first_seen_at", "last_seen_at", "first_fetch_id", "last_fetch_id")

_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    sha256 TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    body BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS fetches (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    status INTEGER NOT NULL,
    content_type TEXT,
    fetched_at TEXT NOT NULL,
    sha256 TEXT NOT NULL REFERENCES blobs(sha256),
    size INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS fetches_source_time ON fetches(source, fetched_at);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    summary TEXT,
    error TEXT
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0

    def __iadd__(self, other: UpsertResult) -> UpsertResult:
        self.inserted += other.inserted
        self.updated += other.updated
        return self


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _create_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_BASE_SCHEMA)
            for name, spec in TABLES.items():
                cols = ", ".join(spec.columns + BOOKKEEPING)
                key = ", ".join(spec.key)
                self.conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ({cols}, PRIMARY KEY ({key}))")
                self.conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {name}_first_seen ON {name}(first_seen_at)"
                )

    # Raw layer

    def record_fetch(self, source: str, resp: FetchedResponse) -> int:
        digest = hashlib.sha256(resp.body).hexdigest()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs (sha256, size, body) VALUES (?, ?, ?)",
                (digest, len(resp.body), zlib.compress(resp.body, 6)),
            )
            cur = self.conn.execute(
                "INSERT INTO fetches (source, method, url, status, content_type, fetched_at, sha256, size)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source, resp.method, resp.url, resp.status, resp.content_type,
                 iso(resp.fetched_at), digest, len(resp.body)),
            )
        return int(cur.lastrowid)

    def blob(self, sha256: str) -> bytes:
        row = self.conn.execute("SELECT body FROM blobs WHERE sha256 = ?", (sha256,)).fetchone()
        if row is None:
            raise KeyError(sha256)
        return zlib.decompress(row["body"])

    def fetch_time(self, fetch_id: int) -> str:
        return self.conn.execute("SELECT fetched_at FROM fetches WHERE id = ?", (fetch_id,)).fetchone()[0]

    # Parsed layer

    def upsert(self, table: str, rows: Iterable[Mapping[str, Any]], *, fetch_id: int) -> UpsertResult:
        spec = TABLES[table]
        seen_at = self.fetch_time(fetch_id)
        unique: dict[tuple, Mapping[str, Any]] = {}
        for row in rows:
            key = tuple(row.get(k) for k in spec.key)
            if any(v is None or v == "" for v in key):
                raise ValueError(f"{table}: row without key {spec.key}: {dict(row)}")
            unique[key] = row

        cols = spec.columns + BOOKKEEPING
        updates = ["last_seen_at = excluded.last_seen_at", "last_fetch_id = excluded.last_fetch_id"]
        updates += [f"{c} = excluded.{c}" for c in spec.mutable]
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
            f" ON CONFLICT ({', '.join(spec.key)}) DO UPDATE SET {', '.join(updates)}"
            " RETURNING first_fetch_id"
        )
        result = UpsertResult()
        with self.conn:
            for row in unique.values():
                values = [_to_sql(row.get(c)) for c in spec.columns]
                values += [seen_at, seen_at, fetch_id, fetch_id]
                (first_fetch_id,) = self.conn.execute(sql, values).fetchone()
                if first_fetch_id == fetch_id:
                    result.inserted += 1
                else:
                    result.updated += 1
        return result

    # Run log

    def start_run(self, source: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs (source, started_at) VALUES (?, ?)", (source, iso(utcnow()))
            )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, ok: bool, summary: Mapping[str, Any], error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at = ?, ok = ?, summary = ?, error = ? WHERE id = ?",
                (iso(utcnow()), int(ok), json.dumps(summary, ensure_ascii=False), error, run_id),
            )

    def table_counts(self) -> dict[str, int]:
        return {
            name: self.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in TABLES
        }

    def last_runs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT source, MAX(started_at) AS started_at, ok, summary, error FROM runs GROUP BY source"
            " ORDER BY source"
        ).fetchall()


def _to_sql(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return value
