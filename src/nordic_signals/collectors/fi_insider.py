"""Finansinspektionen's insider register (insynshandel / PDMR transactions).

The export behind FI's own search page (verified live 2026-10-02):

    GET https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search
        ?SearchFunctionType=Insyn&Publiceringsdatum.From=YYYY-MM-DD
        &Publiceringsdatum.To=YYYY-MM-DD&button=export

It returns UTF-16, semicolon-separated CSV with 22 columns (plus a trailing
empty one) and at most 1,000 rows, so busy windows are split in half until
each fits. The register starts on 2016-07-03 and rows appear as soon as the
insider files. FI's data is free to reuse with attribution.

Rows name the insiders. Keep the database private: storing public register
data for personal analysis is fine, republishing names is a GDPR question.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .base import Collector, RunSummary

EXPORT_URL = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"
ROW_CAP = 1000
STOCKHOLM = ZoneInfo("Europe/Stockholm")

COLUMNS = {
    "Publiceringsdatum": "published_at",
    "Emittent": "issuer",
    "LEI-kod": "lei",
    "Anmälningsskyldig": "notifier",
    "Person i ledande ställning": "pdmr",
    "Befattning": "position",
    "Närstående": "closely_associated",
    "Korrigering": "is_correction",
    "Beskrivning av korrigering": "correction_description",
    "Är förstagångsrapportering": "is_first_report",
    "Är kopplad till aktieprogram": "linked_to_share_program",
    "Karaktär": "nature",
    "Instrumenttyp": "instrument_type",
    "Instrumentnamn": "instrument_name",
    "ISIN": "isin",
    "Transaktionsdatum": "transaction_date",
    "Volym": "volume",
    "Volymsenhet": "volume_unit",
    "Pris": "price",
    "Valuta": "currency",
    "Handelsplats": "venue",
    "Status": "status",
}
_FLAGS = ("closely_associated", "is_correction", "is_first_report", "linked_to_share_program")
_NUMBERS = ("volume", "price")


def parse_export(body: bytes) -> list[dict[str, Any]]:
    # FI sends little-endian UTF-16 without a byte-order mark.
    has_bom = body[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
    text = body.decode("utf-16" if has_bom else "utf-16-le")
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = [_clean(h) for h in next(reader, [])]
    missing = set(COLUMNS) - set(header)
    if missing:
        raise ValueError(f"FI insider export is missing columns: {sorted(missing)}")
    index = {name: header.index(name) for name in COLUMNS}

    rows = []
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        values = {COLUMNS[name]: _clean(raw[i]) if i < len(raw) else "" for name, i in index.items()}
        row: dict[str, Any] = {"row_hash": _row_hash(values), **values}
        row["published_at"] = _local_iso(values["published_at"])
        row["transaction_date"] = values["transaction_date"][:10] or None
        for key in _FLAGS:
            row[key] = _flag(values[key])
        for key in _NUMBERS:
            row[key] = _number(values[key])
        rows.append(row)
    return rows


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _row_hash(values: dict[str, str]) -> str:
    joined = "\x1f".join(values[c] for c in COLUMNS.values())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _local_iso(value: str) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=STOCKHOLM).isoformat()


def _flag(value: str) -> bool | None:
    lowered = value.lower()
    if lowered == "ja":
        return True
    if lowered == "nej":
        return False
    return None


def _number(value: str) -> float | None:
    if not value:
        return None
    return float(value.replace(" ", "").replace(",", "."))


class FiInsiderCollector(Collector):
    source = "fi-insider"

    def run(self, *, start: date, end: date) -> RunSummary:
        self._window(start, end)
        return self.summary

    def _window(self, start: date, end: date) -> None:
        params = {
            "SearchFunctionType": "Insyn",
            "Publiceringsdatum.From": start.isoformat(),
            "Publiceringsdatum.To": end.isoformat(),
            "button": "export",
        }
        resp, fetch_id = self.fetch("GET", EXPORT_URL, params=params)
        rows = parse_export(resp.body)
        if len(rows) >= ROW_CAP:
            if start < end:
                middle = start + (end - start) // 2
                self._window(start, middle)
                self._window(middle + timedelta(days=1), end)
                return
            self.warn(f"{start}: export hit the {ROW_CAP}-row cap; some rows may be missing")
        self.save("se_insider_trades", rows, fetch_id)
