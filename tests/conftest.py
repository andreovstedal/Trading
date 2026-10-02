"""Shared helpers: fixtures on disk, a fake HTTP server, and a .ods builder."""

from __future__ import annotations

import io
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest

from nordic_signals.http import PoliteClient
from nordic_signals.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str):
    return json.loads(fixture_bytes(name))


class FakeServer:
    """Routes requests by (method, host, path) to handler functions."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.prefix_routes: list[tuple[str, str, str, Callable[[httpx.Request], httpx.Response]]] = []
        self.requests: list[httpx.Request] = []

    def add(self, method: str, url: str, handler: Callable[[httpx.Request], httpx.Response] | httpx.Response) -> None:
        u = httpx.URL(url)
        self.routes[(method, u.host, u.path)] = handler if callable(handler) else (lambda _r, h=handler: h)

    def add_prefix(self, method: str, url: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        """Route every path under ``url``, for APIs that put parameters in the path."""
        u = httpx.URL(url)
        self.prefix_routes.append((method, u.host, u.path, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.host, request.url.path))
        for method, host, prefix, prefix_handler in self.prefix_routes:
            if handler is None and (method, host) == (request.method, request.url.host) \
                    and request.url.path.startswith(prefix):
                handler = prefix_handler
        if handler is None:
            return httpx.Response(404, text=f"no route for {request.method} {request.url}")
        return handler(request)

    def client(self) -> PoliteClient:
        return PoliteClient(transport=httpx.MockTransport(self), sleep=lambda _s: None)


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


# Tests run on SQLite, and also on PostgreSQL when TEST_DATABASE_URL points at
# a scratch database (its tables are dropped and recreated for every test).
BACKENDS = ["sqlite"] + (["postgresql"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def db_url(request, tmp_path) -> str:
    if request.param == "sqlite":
        return str(tmp_path / "signals.sqlite")
    url = os.environ["TEST_DATABASE_URL"]
    with Store(url) as s:
        s.metadata.drop_all(s.engine)
    return url


@pytest.fixture
def store(db_url):
    with Store(db_url) as s:
        yield s


def make_ods(rows: list[list[str]]) -> bytes:
    """A minimal OpenDocument spreadsheet with one sheet holding ``rows``.

    Cells that look numeric are written as typed float cells, like FI's files,
    and every row ends with a large repeated empty cell, as spreadsheets do.
    """
    ns = (
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    )
    xml_rows = []
    for row in rows:
        cells = []
        for value in row:
            try:
                float(value)
                cells.append(f'<table:table-cell office:value-type="float" office:value="{value}">'
                             f"<text:p>{escape(value)}</text:p></table:table-cell>")
            except ValueError:
                paragraphs = "".join(f"<text:p>{escape(p)}</text:p>" for p in value.split("\n")) if value else ""
                cells.append(f'<table:table-cell office:value-type="string">{paragraphs}</table:table-cell>')
        cells.append('<table:table-cell table:number-columns-repeated="16378"/>')
        xml_rows.append(f"<table:table-row>{''.join(cells)}</table:table-row>")
    xml_rows.append('<table:table-row table:number-rows-repeated="1048000"><table:table-cell/></table:table-row>')
    content = (
        f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns}><office:body>'
        f'<office:spreadsheet><table:table table:name="Blad1">{"".join(xml_rows)}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", content)
    return buf.getvalue()


# Header rows exactly as FI's files have them (bilingual, with line breaks).
FI_POSITION_ROWS = [
    ["Aktuella positioner"],
    ["Betydande korta nettopositioner i aktier (blankning)", "", "", "fi.se/blankning"],
    ["", "", "", "rapportering@fi.se"],
    ["Innehavare av positionen\n(Position holder)", "Namn på emittent\n(Name of the issuer)", "ISIN",
     "Position i procent(Position in per cent)", "Datum för positionen\n(Position date)", "Kommentar(Comment)"],
    ["Two Sigma Investments, LP", "Sivers Semiconductors AB", "SE0003917798", "0.5", "2026-10-01"],
    ["Marshall Wace LLP", "Embracer Group AB", "SE0023615885", "1.23", "2026-09-30", "Revised"],
]
FI_AGGREGATE_ROWS = [
    ["Aggregerade positioner"],
    ["Aggregerade korta nettopositioner i aktier (blankning)", "", "", "fi.se/blankning"],
    ["", "", "", "rapportering@fi.se"],
    ["Namn på emittent\n(Name of the issuer)", "LEI", "Position i procent(Position in per cent)",
     "Positionsdatum senaste position\n(Position date, latest position)"],
    [" Svenska Handelsbanken AB", "NHBDILHZTYCNBV5UYZ31", "3.89", "2026-10-02"],
    [" Dynavox Group AB", "5493008X1XZR4R5R0P66", "9.28", "2026-10-01"],
]


# A small synthetic universe for the advisor and web tests.

def seed_universe(store, now=None):
    """Ten stocks covering each rule, plus FX, insider trades, announcements and short interest.

    Returns the ``now`` used, so tests can place later observations after it.
    """
    from datetime import datetime, timedelta, timezone

    from nordic_signals.http import FetchedResponse

    now = now or datetime.now(timezone.utc)

    def fetch(at):
        return store.record_fetch("test", FetchedResponse("GET", "https://example.test/", 200, "", b"", at))

    seed_fetch = fetch(now - timedelta(hours=2))
    stocks = [
        # id, symbol, country, type, issuer, isin, price, mcap, turnover, pe, pb, dy, y1y, y1m
        (1, "AAA", "NO", "ESH", 101, "NO0000000001", 100.0, 10e9, 50e6, 8.0, 1.5, 5.0, 40.0, 2.0),
        (2, "BBB", "NO", "ESH", 102, "NO0000000002", 50.0, 5e9, 20e6, 20.0, 3.0, 1.0, 5.0, 1.0),
        (3, "CCC", "NO", "ESH", 103, "NO0000000003", 3.0, 2e9, 20e6, 10.0, 1.0, 0.0, 10.0, 0.0),
        (4, "DDD", "NO", "ESH", 104, "NO0000000004", 80.0, 4e9, 20e6, None, 2.0, 0.0, 30.0, 3.0),
        (5, "EEE", "NO", "ESH", 105, "NO0000000005", 40.0, 1e9, 100e3, 9.0, 1.2, 3.0, 25.0, 1.0),
        (6, "GRW", "NO", "ESHMTF", 106, "NO0000000006", 60.0, 3e9, 30e6, 7.0, 1.1, 4.0, 60.0, 4.0),
        (7, "SEA A", "SE", "ESH", 201, "SE0000000007", 200.0, 50e9, 30e6, 12.0, 2.0, 3.0, 20.0, 1.0),
        (8, "SEA B", "SE", "ESH", 201, "SE0000000008", 199.0, 50e9, 60e6, 12.0, 2.0, 3.0, 20.0, 1.0),
        (9, "SEB", "SE", "ESH", 202, "SE0000000009", 150.0, 20e9, 40e6, 15.0, 2.5, 2.0, 10.0, -1.0),
        (10, "SEC", "SE", "ESH", 203, "SE0000000010", 120.0, 5e9, 25e6, 11.0, 1.8, 2.5, 15.0, 0.5),
    ]
    store.upsert("instruments", [{
        "instrument_id": i, "symbol": sym, "name": f"{sym} Corp", "isin": isin, "exchange_country": c,
        "instrument_type": t, "issuer_id": issuer, "issuer_name": f"Issuer {issuer}",
        "currency": "NOK" if c == "NO" else "SEK",
        "exchanges": (["Euronext Growth"] if t == "ESHMTF"
                      else ["Euronext Oslo" if c == "NO" else "Nasdaq Stockholm Large Cap"]),
        "is_tradable": True,
    } for i, sym, c, t, issuer, isin, *_ in stocks], fetch_id=seed_fetch)
    store.upsert("nordnet_observations", [{
        "instrument_id": i, "observed_at": now - timedelta(hours=1), "last": price, "market_cap": mcap,
        "turnover": turnover, "pe": pe, "pb": pb, "dividend_yield": dy, "yield_1y": y1y, "yield_1m": y1m,
        "number_of_owners": 1000 * i,
    } for i, _sym, _c, _t, _issuer, _isin, price, mcap, turnover, pe, pb, dy, y1y, y1m in stocks], fetch_id=seed_fetch)

    yesterday = now - timedelta(days=1)
    store.upsert("price_bars", [{"symbol": "SEKNOK=X", "interval": "1d", "ts": int(yesterday.timestamp()),
                                 "ts_utc": yesterday, "close": 0.95}], fetch_id=seed_fetch)

    # SEC: two insiders buy in the open market (a cluster); SEB: a share-programme award, which only maps LEI to ISIN.
    store.upsert("se_insider_trades", [
        {"row_hash": "t1", "published_at": now - timedelta(days=1), "isin": "SE0000000010", "lei": "LEI-SEC",
         "pdmr": "Person A", "position": "CEO", "nature": "Förvärv", "instrument_type": "Aktie", "volume": 20000.0,
         "price": 120.0, "currency": "SEK", "status": "Aktuell", "linked_to_share_program": None},
        {"row_hash": "t2", "published_at": now - timedelta(days=2), "isin": "SE0000000010", "lei": "LEI-SEC",
         "pdmr": "Person B", "position": "CFO", "nature": "Förvärv", "instrument_type": "Aktie", "volume": 30000.0,
         "price": 119.0, "currency": "SEK", "status": "Aktuell", "linked_to_share_program": None},
        {"row_hash": "t3", "published_at": now - timedelta(days=3), "isin": "SE0000000009", "lei": "LEI-SEB",
         "pdmr": "Person C", "position": "CEO", "nature": "Tilldelning", "instrument_type": "Aktie", "volume": 1000.0,
         "price": 0.0, "currency": "SEK", "status": "Aktuell", "linked_to_share_program": True},
    ], fetch_id=seed_fetch)

    # AAA: an insider purchase notice; BBB: a new buyback programme.
    store.upsert("newsweb_messages", [
        {"message_id": 1, "issuer_sign": "AAA", "title": "Mandatory notification of trade", "category_ids": [1102],
         "published_at": now - timedelta(days=1)},
        {"message_id": 2, "issuer_sign": "BBB", "title": "BBB ASA launches share buyback programme",
         "category_ids": [1007], "published_at": now - timedelta(days=1)},
    ], fetch_id=seed_fetch)
    store.upsert("newsweb_bodies", [{"message_id": 1, "body": "The CEO has today purchased 10,000 shares."}],
                 fetch_id=seed_fetch)

    # Norway: AAA's short interest jumped from 1.0% to 2.2%, with history going back 60 days.
    store.upsert("no_short_totals", [
        {"isin": "NO0000000001", "date": (now - timedelta(days=60)).date(), "short_pct": 1.0},
        {"isin": "NO0000000001", "date": (now - timedelta(days=2)).date(), "short_pct": 2.2},
    ], fetch_id=seed_fetch)
    # Sweden: SEB at 3%, but only one download so far, so it can't count as an increase.
    store.upsert("se_short_aggregate", [{"lei": "LEI-SEB", "issuer": "SEB Corp", "total_pct": 3.0,
                                         "position_date": (now - timedelta(days=1)).date()}], fetch_id=seed_fetch)
    return now
