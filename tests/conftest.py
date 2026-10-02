"""Shared helpers: fixtures on disk, a fake HTTP server, and a .ods builder."""

from __future__ import annotations

import io
import json
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
        self.requests: list[httpx.Request] = []

    def add(self, method: str, url: str, handler: Callable[[httpx.Request], httpx.Response] | httpx.Response) -> None:
        u = httpx.URL(url)
        self.routes[(method, u.host, u.path)] = handler if callable(handler) else (lambda _r, h=handler: h)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get((request.method, request.url.host, request.url.path))
        if handler is None:
            return httpx.Response(404, text=f"no route for {request.method} {request.url}")
        return handler(request)

    def client(self) -> PoliteClient:
        return PoliteClient(transport=httpx.MockTransport(self), sleep=lambda _s: None)


@pytest.fixture
def server() -> FakeServer:
    return FakeServer()


@pytest.fixture
def store():
    with Store(":memory:") as s:
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
