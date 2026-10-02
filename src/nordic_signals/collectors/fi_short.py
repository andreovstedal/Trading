"""Finansinspektionen's short-selling register (blankningsregistret).

Three OpenDocument (.ods) downloads on www.fi.se (verified live 2026-10-02):

* ``GetAktuellFile``: current named positions of at least 0.5%.
* ``GetHistFile``: older and closed named positions.
* ``GetBlankningsregisterAggregat``: per issuer, the sum of every position
  reported to FI (from 0.1%), not only the public ones. Usually the more
  informative series.

The files only show the latest state and FI updates them around 15:30 on
trading days, so collect once a day after that to build a history.
"""

from __future__ import annotations

from typing import Any

from ..ods import read_rows
from .base import Collector, RunSummary

BASE = "https://www.fi.se/BlankningsRegister"

# Header cells are bilingual, e.g. "Datum för positionen\n(Position date)";
# match on the English label.
_POSITION_HEADERS = {
    "position holder": "holder",
    "name of the issuer": "issuer",
    "isin": "isin",
    "position in per cent": "position_pct",
    "position date": "position_date",
    "comment": "comment",
}
_AGGREGATE_HEADERS = {
    "name of the issuer": "issuer",
    "lei": "lei",
    "position in per cent": "total_pct",
    "position date": "position_date",
}


def parse_positions(rows: list[list[str]]) -> list[dict[str, Any]]:
    return [
        {**r, "position_pct": _pct(r["position_pct"]), "position_date": r["position_date"][:10]}
        for r in _records(rows, _POSITION_HEADERS, required=("holder", "isin", "position_date"))
    ]


def parse_aggregate(rows: list[list[str]]) -> list[dict[str, Any]]:
    return [
        {**r, "total_pct": _pct(r["total_pct"]), "position_date": r["position_date"][:10]}
        for r in _records(rows, _AGGREGATE_HEADERS, required=("lei", "position_date"))
    ]


def _records(
    rows: list[list[str]], headers: dict[str, str], *, required: tuple[str, ...]
) -> list[dict[str, str]]:
    header = next(
        ((i, columns) for i, row in enumerate(rows) if (columns := _match_header(row, headers)) is not None),
        None,
    )
    if header is None:
        raise ValueError(f"no header row with columns {sorted(headers.values())}")
    header_index, columns = header

    records = []
    for row in rows[header_index + 1:]:
        record = {field: (row[j].strip() if j < len(row) else "") for field, j in columns.items()}
        if all(record[field] for field in required):
            records.append(record)
    return records


def _match_header(row: list[str], headers: dict[str, str]) -> dict[str, int] | None:
    labels = [_english_label(cell) for cell in row]
    columns = {}
    for label, field in headers.items():
        # Prefix match: the aggregate file labels its date column
        # "position date, latest position".
        j = next((j for j, cell in enumerate(labels) if cell.startswith(label)), None)
        if j is None:
            return None
        columns[field] = j
    return columns


def _english_label(cell: str) -> str:
    cell = cell.lower()
    if "(" in cell:
        cell = cell[cell.rindex("(") + 1:].rstrip(")")
    return cell.strip()


def _pct(value: str) -> float | None:
    return float(value.replace(",", ".")) if value else None


class FiShortCollector(Collector):
    source = "fi-short"

    def run(self, *, history: bool = False) -> RunSummary:
        # History first: a position in both files then ends up attributed to the current file, which is how the
        # stock page tells open positions (last seen in the latest current file) from closed ones.
        if history:
            resp, fetch_id = self.fetch("GET", f"{BASE}/GetHistFile")
            self.save("se_short_positions", parse_positions(read_rows(resp.body)), fetch_id)

        resp, fetch_id = self.fetch("GET", f"{BASE}/GetAktuellFile")
        self.save("se_short_positions", parse_positions(read_rows(resp.body)), fetch_id)

        resp, fetch_id = self.fetch("GET", f"{BASE}/GetBlankningsregisterAggregat")
        self.save("se_short_aggregate", parse_aggregate(read_rows(resp.body)), fetch_id)
        return self.summary
