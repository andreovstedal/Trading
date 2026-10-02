"""Shared plumbing for collectors: fetch + log raw, parse, upsert, summarise."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..http import FetchedResponse, PoliteClient
from ..store import Store, UpsertResult

log = logging.getLogger(__name__)

# Oslo and Stockholm share a time zone; exchange "dates" in these feeds are local.
NORDIC_TZ = ZoneInfo("Europe/Oslo")


@dataclass
class RunSummary:
    fetches: int = 0
    tables: dict[str, UpsertResult] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def add(self, table: str, result: UpsertResult) -> None:
        self.tables.setdefault(table, UpsertResult())
        self.tables[table] += result

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetches": self.fetches,
            "tables": {t: {"inserted": r.inserted, "updated": r.updated} for t, r in self.tables.items()},
            "warnings": self.warnings,
        }


class Collector:
    source: str

    def __init__(self, client: PoliteClient, store: Store):
        self.client = client
        self.store = store
        self.summary = RunSummary()

    def run(self, **options: Any) -> RunSummary:
        raise NotImplementedError

    def fetch(self, method: str, url: str, **kwargs: Any) -> tuple[FetchedResponse, int]:
        resp = self.client.request(method, url, **kwargs)
        fetch_id = self.store.record_fetch(self.source, resp)
        self.summary.fetches += 1
        return resp, fetch_id

    def save(self, table: str, rows: Iterable[Mapping[str, Any]], fetch_id: int) -> None:
        self.summary.add(table, self.store.upsert(table, rows, fetch_id=fetch_id))

    def warn(self, message: str) -> None:
        log.warning("%s: %s", self.source, message)
        self.summary.warnings.append(message)


def local_today() -> date:
    return datetime.now(NORDIC_TZ).date()


def days_back(days: int) -> tuple[date, date]:
    """The last ``days`` local calendar days, today included."""
    end = local_today()
    return end - timedelta(days=max(days, 1) - 1), end


def date_range(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def ms_to_iso(ms: int | float | None) -> str | None:
    if not ms:
        return None
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ms_to_local_date(ms: int | float | None) -> str | None:
    """Nordnet sends calendar dates as local-midnight epoch milliseconds."""
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=NORDIC_TZ).date().isoformat()
