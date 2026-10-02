"""Storage: an append-only log of raw fetches plus parsed tables.

Runs on PostgreSQL in production (Railway provides ``DATABASE_URL``) and on
SQLite for local development and tests; SQLAlchemy Core hides the dialect
differences.

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
import os
import zlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import Select
from sqlalchemy.types import TypeEngine

from .http import FetchedResponse

DEFAULT_URL = "sqlite:///data/signals.sqlite"

_TYPES: dict[str, Callable[[], TypeEngine]] = {
    "text": Text,
    "int": BigInteger,
    "float": Float,
    "bool": Boolean,
    "date": Date,
    "ts": lambda: DateTime(timezone=True),
    "json": lambda: JSON().with_variant(postgresql.JSONB(), "postgresql"),
}
# SQLite only auto-increments a plain INTEGER primary key.
_SERIAL = BigInteger().with_variant(Integer(), "sqlite")


@dataclass(frozen=True)
class TableSpec:
    columns: dict[str, str]  # column name -> type key in _TYPES
    key: tuple[str, ...]
    mutable: tuple[str, ...] = ()


def _spec(columns: str, key: str, mutable: str = "") -> TableSpec:
    """Columns as "name:type" words, type defaulting to text."""
    parsed = {}
    for word in columns.split():
        name, _, kind = word.partition(":")
        parsed[name] = kind or "text"
    return TableSpec(parsed, tuple(key.split()), tuple(mutable.split()))


TABLES: dict[str, TableSpec] = {
    # Euronext Oslo Børs NewsWeb
    "newsweb_categories": _spec("category_id:int name_no name_en", "category_id", "name_no name_en"),
    "newsweb_messages": _spec(
        "message_id:int news_id:int published_at:ts issuer_id:int issuer_sign issuer_name title"
        " category_ids:json category_en markets:json instrument_id:int instrument_name"
        " correction_for_message_id:int corrected_by_message_id:int num_attachments:int is_test:bool"
        " client_announcement_id",
        "message_id",
        "title category_ids category_en corrected_by_message_id num_attachments",
    ),
    "newsweb_bodies": _spec("message_id:int body attachments:json", "message_id", "body attachments"),
    "newsweb_attachments": _spec(
        "message_id:int attachment_id:int name sha256 content_type size:int",
        "message_id attachment_id",
        "name sha256 content_type size",
    ),
    # Finansinspektionen: insider register (marknadssok.fi.se) and short-selling register
    "se_insider_trades": _spec(
        "row_hash published_at:ts issuer lei notifier pdmr position closely_associated:bool"
        " is_correction:bool correction_description is_first_report:bool linked_to_share_program:bool"
        " nature instrument_type instrument_name isin transaction_date:date volume:float volume_unit"
        " price:float currency venue status",
        "row_hash",
    ),
    "se_short_positions": _spec(
        "holder issuer isin position_pct:float position_date:date comment",
        "holder isin position_date",
        "issuer position_pct comment",
    ),
    "se_short_aggregate": _spec(
        "issuer lei total_pct:float position_date:date", "lei position_date", "issuer total_pct"
    ),
    # Finanstilsynet short-sale register (ssr.finanstilsynet.no)
    "no_short_totals": _spec(
        "isin date:date issuer_name short_pct:float short_shares:int",
        "isin date",
        "issuer_name short_pct short_shares",
    ),
    "no_short_positions": _spec(
        "isin date:date holder position_date:date short_pct:float short_shares:int",
        "isin date holder",
        "position_date short_pct short_shares",
    ),
    # MFN (Modular Finance News)
    "mfn_entities": _spec("slug entity_id name", "slug", "entity_id name"),
    "mfn_items": _spec(
        "news_id group_id entity_id issuer_name slug isins:json leis:json tickers:json lang type"
        " tags:json scopes:json title publish_date:ts url html attachments:json",
        "news_id",
        "title tags html attachments",
    ),
    # Yahoo Finance chart API
    "price_bars": _spec(
        "symbol interval ts:int ts_utc:ts currency open:float high:float low:float close:float"
        " adjclose:float volume:int",
        "symbol interval ts",
        "open high low close adjclose volume",
    ),
    "dividends": _spec("symbol ts:int ex_date:date amount:float currency", "symbol ts", "amount"),
    "splits": _spec(
        "symbol ts:int ex_date:date numerator:float denominator:float", "symbol ts", "numerator denominator"
    ),
    # Nordnet stock list (tradable universe plus daily observations)
    "instruments": _spec(
        "instrument_id:int isin symbol name long_name issuer_id:int issuer_name instrument_type currency"
        " exchange_country exchanges:json market_id:int identifier is_tradable:bool is_shortable:bool"
        " display_slug",
        "instrument_id",
        "isin symbol name long_name issuer_id issuer_name instrument_type currency exchange_country"
        " exchanges market_id identifier is_tradable is_shortable display_slug",
    ),
    "nordnet_observations": _spec(
        "instrument_id:int observed_at:ts tick_at:ts realtime:bool last:float open:float high:float"
        " low:float close:float bid:float ask:float spread_pct:float diff_pct:float turnover:float"
        " turnover_volume:float market_cap:float pe:float pb:float ps:float eps:float"
        " dividend_per_share:float dividend_yield:float number_of_owners:int statistics_at:ts"
        " report_date:date report_type ex_date:date dividend_date:date dividend_amount:float"
        " dividend_currency yield_1w:float yield_1m:float yield_3m:float yield_ytd:float yield_1y:float",
        "instrument_id observed_at",
    ),
}

_BOOKKEEPING = {"first_seen_at": "ts", "last_seen_at": "ts", "first_fetch_id": "int", "last_fetch_id": "int"}

# Rows per INSERT statement; keeps every dialect well under its bind-parameter limit.
_BATCH = 500


def _build_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        "blobs", metadata,
        Column("sha256", Text, primary_key=True),
        Column("size", BigInteger, nullable=False),
        Column("body", LargeBinary, nullable=False),
    )
    Table(
        "fetches", metadata,
        Column("id", _SERIAL, primary_key=True, autoincrement=True),
        Column("source", Text, nullable=False, index=True),
        Column("method", Text, nullable=False),
        Column("url", Text, nullable=False),
        Column("status", Integer, nullable=False),
        Column("content_type", Text),
        Column("fetched_at", DateTime(timezone=True), nullable=False, index=True),
        Column("sha256", Text, nullable=False),
        Column("size", BigInteger, nullable=False),
    )
    Table(
        "runs", metadata,
        Column("id", _SERIAL, primary_key=True, autoincrement=True),
        Column("source", Text, nullable=False),
        Column("started_at", DateTime(timezone=True), nullable=False),
        Column("finished_at", DateTime(timezone=True)),
        Column("ok", Boolean),
        Column("summary", _TYPES["json"]()),
        Column("error", Text),
    )
    # The web service's collection schedule (see ``scheduler``): its latest attempt at each job.
    Table(
        "schedule", metadata,
        Column("job", Text, primary_key=True),
        Column("started_at", DateTime(timezone=True)),
        Column("finished_at", DateTime(timezone=True)),
        Column("ok", Boolean),
        Column("error", Text),
    )
    _advice_tables(metadata)
    _pumpfun_tables(metadata)
    for name, spec in TABLES.items():
        columns = {**spec.columns, **_BOOKKEEPING}
        Table(
            name, metadata,
            *(
                Column(col, _TYPES[kind](), primary_key=col in spec.key, index=col == "first_seen_at")
                for col, kind in columns.items()
            ),
        )
    return metadata


def _advice_tables(metadata: MetaData) -> None:
    """The prediction log: every recommendation, the score of every stock it considered, and outcomes."""
    json = _TYPES["json"]
    Table(
        "recommendations", metadata,
        Column("id", _SERIAL, primary_key=True, autoincrement=True),
        Column("created_at", DateTime(timezone=True), nullable=False, index=True),
        Column("finished_at", DateTime(timezone=True)),
        Column("status", Text, nullable=False),  # queued, running, done, failed
        Column("model_version", Text, nullable=False),
        Column("account_value", Float, nullable=False),
        Column("currency", Text, nullable=False),
        Column("policy", json()),
        Column("params", json()),  # model parameters in force
        Column("data_cutoff", json()),  # freshness of each source when scored
        Column("refresh", json()),  # collector results if data was refreshed first
        Column("summary", json()),
        Column("error", Text),
    )
    # One row per stock in the universe, chosen or not, so the ranking itself can be scored later.
    Table(
        "scores", metadata,
        Column("recommendation_id", BigInteger, primary_key=True),
        Column("instrument_id", BigInteger, primary_key=True),
        Column("isin", Text),
        Column("symbol", Text),
        Column("name", Text),
        Column("country", Text),
        Column("segments", json()),
        Column("currency", Text),
        Column("eligible", Boolean, nullable=False),
        Column("exclusion", Text),
        Column("score", Float),
        Column("rank", Integer),
        Column("themes", json()),
        Column("overlays", json()),
        Column("features", json()),
        Column("events", json()),
        Column("reasons", json()),
        Column("ref_price", Float),
        Column("fx_rate", Float),
        Column("long_amount", Float),
        Column("long_shares", Integer),
        Column("long_weight", Float),
    )
    Table(
        "short_signals", metadata,
        Column("recommendation_id", BigInteger, primary_key=True),
        Column("instrument_id", BigInteger, primary_key=True),
        Column("signal_type", Text, primary_key=True),
        Column("direction", Integer, nullable=False),
        Column("description", Text),
        Column("paper", Boolean),
        Column("amount", Float),
        Column("shares", Integer),
        Column("ref_price", Float),
        Column("fx_rate", Float),
        Column("horizon_days", Integer),
    )
    Table(
        "outcomes", metadata,
        Column("recommendation_id", BigInteger, primary_key=True),
        Column("instrument_id", BigInteger, primary_key=True),
        Column("horizon_days", Integer, primary_key=True),
        Column("start_date", Date),
        Column("end_date", Date),
        Column("start_price", Float),
        Column("end_price", Float),
        Column("ret", Float),
        Column("computed_at", DateTime(timezone=True)),
    )


def _pumpfun_tables(metadata: MetaData) -> None:
    """The pump.fun measurement (see ``collectors.pumpfun``): every launch seen, and for a random sample,
    the warning signs when it was scored and its price for the next 24 hours. Prices are SOL per token."""
    json = _TYPES["json"]
    Table(
        "pf_tokens", metadata,
        Column("mint", Text, primary_key=True),
        Column("name", Text),
        Column("symbol", Text),
        Column("creator", Text, index=True),
        Column("created_at", DateTime(timezone=True), nullable=False, index=True),
        Column("discovered_at", DateTime(timezone=True), nullable=False),
        Column("sampled", Boolean, nullable=False),  # scored and followed, or kept only to spot serial creators
        Column("status", Text, nullable=False, index=True),  # new, tracking, done, missing, skipped
        Column("launch", json()),  # pump.fun's fields when discovered
        Column("scored_at", DateTime(timezone=True)),
        Column("screen_version", Text),
        Column("features", json()),
        Column("warnings", json()),
        Column("active", Boolean),  # traded in the 5 minutes before scoring
        Column("complete", Boolean),  # every check could be made (no RPC failure)
        Column("passed", Boolean),
        Column("peak_before", Float),  # highest price seen before scoring
        Column("price_t", Float),  # price when scored
        Column("peak_after", Float),  # highest and lowest price seen from scoring on
        Column("low_after", Float),
        Column("price_1h", Float),
        Column("price_6h", Float),
        Column("price_24h", Float),
        Column("peak_1h", Float),  # highest price from scoring until the 1-hour and 6-hour prices
        Column("peak_6h", Float),
        Column("last_price", Float),
        Column("last_checked_at", DateTime(timezone=True)),
        Column("misses", Integer, nullable=False, default=0),  # price lookups that found nothing
        Column("graduated", Boolean),
        Column("collapsed", Boolean),
    )
    # The fake-money portfolio's value after each collector run, for the chart.
    Table(
        "pf_equity", metadata,
        Column("at", DateTime(timezone=True), primary_key=True),
        Column("cash", Float, nullable=False),
        Column("positions", Float, nullable=False),
        Column("equity", Float, nullable=False),
        Column("open_positions", Integer, nullable=False),
    )


def database_url(value: str | None = None) -> str:
    """Normalise ``--db``/``DATABASE_URL`` into an SQLAlchemy URL.

    Accepts a plain file path (SQLite), ``sqlite:///...``, and the
    ``postgres://`` / ``postgresql://`` URLs that Railway and Heroku hand out,
    which are pointed at the psycopg 3 driver.
    """
    value = value or os.environ.get("DATABASE_URL") or DEFAULT_URL
    if "://" not in value:
        return f"sqlite:///{value}"
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0

    def __iadd__(self, other: UpsertResult) -> UpsertResult:
        self.inserted += other.inserted
        self.updated += other.updated
        return self


class Store:
    def __init__(self, url: str | None = None):
        self.url = database_url(url)
        self.engine = _create_engine(self.url)
        self.metadata = _build_metadata()
        self.metadata.create_all(self.engine)
        self._add_missing_columns()
        self._fetch_times: dict[int, datetime] = {}

    def _add_missing_columns(self) -> None:
        """Columns added to a table after it was first created. There are no migrations otherwise, so only
        additive changes to nullable columns are possible; anything else needs Alembic or a manual ALTER."""
        inspector = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in self.metadata.sorted_tables:
                existing = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in existing and column.nullable and not column.primary_key:
                        kind = column.type.compile(dialect=self.engine.dialect)
                        conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def table(self, name: str) -> Table:
        return self.metadata.tables[name]

    # Raw layer

    def record_fetch(self, source: str, resp: FetchedResponse) -> int:
        digest = hashlib.sha256(resp.body).hexdigest()
        blobs, fetches = self.table("blobs"), self.table("fetches")
        with self.engine.begin() as conn:
            conn.execute(
                self._insert(blobs)
                .values(sha256=digest, size=len(resp.body), body=zlib.compress(resp.body, 6))
                .on_conflict_do_nothing(index_elements=["sha256"])
            )
            fetch_id = conn.execute(
                insert(fetches)
                .values(source=source, method=resp.method, url=resp.url, status=resp.status,
                        content_type=resp.content_type, fetched_at=_utc(resp.fetched_at),
                        sha256=digest, size=len(resp.body))
                .returning(fetches.c.id)
            ).scalar_one()
        self._fetch_times[fetch_id] = _utc(resp.fetched_at)
        return fetch_id

    def blob(self, sha256: str) -> bytes:
        body = self.scalar(select(self.table("blobs").c.body).where(self.table("blobs").c.sha256 == sha256))
        if body is None:
            raise KeyError(sha256)
        return zlib.decompress(body)

    # Parsed layer

    def upsert(self, table: str, rows: Iterable[Mapping[str, Any]], *, fetch_id: int) -> UpsertResult:
        spec, target = TABLES[table], self.table(table)
        seen_at = self._fetch_time(fetch_id)
        unique: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            values = {col: _convert(kind, row.get(col)) for col, kind in spec.columns.items()}
            key = tuple(values[k] for k in spec.key)
            if any(v is None or v == "" for v in key):
                raise ValueError(f"{table}: row without key {spec.key}: {dict(row)}")
            values.update(first_seen_at=seen_at, last_seen_at=seen_at,
                          first_fetch_id=fetch_id, last_fetch_id=fetch_id)
            unique[key] = values

        stmt = self._insert(target)
        updates = {c: stmt.excluded[c] for c in (*spec.mutable, "last_seen_at", "last_fetch_id")}
        stmt = stmt.on_conflict_do_update(index_elements=list(spec.key), set_=updates)
        stmt = stmt.returning(target.c.first_fetch_id)

        result = UpsertResult()
        batch = list(unique.values())
        with self.engine.begin() as conn:
            for start in range(0, len(batch), _BATCH):
                for first_fetch_id in conn.execute(stmt.values(batch[start:start + _BATCH])).scalars():
                    if first_fetch_id == fetch_id:
                        result.inserted += 1
                    else:
                        result.updated += 1
        return result

    # Queries

    def query(self, stmt: Select) -> list[RowMapping]:
        with self.engine.connect() as conn:
            return list(conn.execute(stmt).mappings())

    def scalar(self, stmt: Select) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(stmt).scalar()

    def get(self, table: str, **key: Any) -> RowMapping | None:
        t = self.table(table)
        rows = self.query(select(t).where(*(t.c[k] == v for k, v in key.items())).limit(1))
        return rows[0] if rows else None

    # Run log

    def start_run(self, source: str) -> int:
        runs = self.table("runs")
        with self.engine.begin() as conn:
            return conn.execute(
                insert(runs).values(source=source, started_at=utcnow()).returning(runs.c.id)
            ).scalar_one()

    def finish_run(self, run_id: int, *, ok: bool, summary: Mapping[str, Any], error: str | None = None) -> None:
        runs = self.table("runs")
        with self.engine.begin() as conn:
            conn.execute(
                runs.update().where(runs.c.id == run_id)
                .values(finished_at=utcnow(), ok=ok, summary=dict(summary), error=error)
            )

    def table_counts(self) -> dict[str, int]:
        return {name: self.scalar(select(func.count()).select_from(self.table(name)))
                for name in (*TABLES, "pf_tokens")}

    def last_runs(self) -> list[RowMapping]:
        runs = self.table("runs")
        latest = select(func.max(runs.c.id).label("id")).group_by(runs.c.source).subquery()
        return self.query(select(runs).join(latest, runs.c.id == latest.c.id).order_by(runs.c.source))

    # Helpers

    def _insert(self, table: Table):
        dialect = self.engine.dialect.name
        if dialect == "postgresql":
            return postgresql.insert(table)
        if dialect == "sqlite":
            return sqlite.insert(table)
        raise NotImplementedError(f"unsupported database: {dialect}")

    def _fetch_time(self, fetch_id: int) -> datetime:
        if fetch_id not in self._fetch_times:
            fetches = self.table("fetches")
            fetched_at = self.scalar(select(fetches.c.fetched_at).where(fetches.c.id == fetch_id))
            self._fetch_times[fetch_id] = _utc(fetched_at)
        return self._fetch_times[fetch_id]


def _create_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    if url in ("sqlite://", "sqlite:///:memory:"):
        # One shared connection, or every pooled connection gets its own empty database.
        engine = create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    else:
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return engine


def _utc(dt: datetime) -> datetime:
    """Aware UTC datetime; naive values (as SQLite returns them) are taken to be UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _convert(kind: str, value: Any) -> Any:
    """Coerce a parsed value to its column type (ISO strings to dates/datetimes, etc.)."""
    if value is None or (value == "" and kind != "text"):
        return None
    if kind == "ts":
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        return _utc(value)
    if kind == "date":
        if isinstance(value, datetime):
            return value.date()
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "bool":
        return bool(value)
    return value
