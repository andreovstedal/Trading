"""Running collectors and named sets of them; shared by the CLI and the web app."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from .collectors import COLLECTORS, RunSummary
from .collectors.base import days_back, local_today
from .collectors.yahoo import universe_symbols
from .http import PoliteClient
from .store import Store

log = logging.getLogger("nordic_signals")

FX_SYMBOLS = ["SEKNOK=X"]  # NOK per SEK, to size Swedish positions in a NOK account

# Named sets of collector runs, in order.
# - intraday: light enough to run every 15 minutes in market hours.
# - daily: after both closes; its look-back covers a weekend.
# - refresh: what the web app's button runs before scoring (about 30 seconds).
# - backfill: one-off history load for a new database (one to two hours, mostly Yahoo).
# MFN and the universe-wide Yahoo run are slow, so they are scheduled separately.
SETS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "intraday": [
        ("newsweb", {"days": 1}),
        ("fi-insider", {"days": 1}),
    ],
    "daily": [
        ("nordnet", {"countries": ("NO", "SE")}),
        ("newsweb", {"days": 3}),
        ("fi-insider", {"days": 4}),
        ("fi-short", {}),
        ("no-short", {}),
        ("yahoo", {"symbols": FX_SYMBOLS, "range_": "1mo"}),
    ],
    "refresh": [
        ("nordnet", {"countries": ("NO", "SE")}),
        ("newsweb", {"days": 1}),
        ("fi-insider", {"days": 2}),
        ("yahoo", {"symbols": FX_SYMBOLS, "range_": "5d"}),
    ],
    "backfill": [
        ("nordnet", {"countries": ("NO", "SE")}),
        ("fi-insider", {"days": 150}),
        ("fi-short", {"history": True}),
        ("no-short", {}),
        ("newsweb", {"days": 120, "detail_categories": [1102, 1007]}),
        ("yahoo", {"symbols": FX_SYMBOLS, "range_": "1y"}),
        ("yahoo", {"universe": ["NO", "SE"], "range_": "1y"}),
    ],
}


def options_for(store: Store, source: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Turn CLI-style arguments into keyword arguments for one collector."""
    if source in ("newsweb", "fi-insider"):
        if raw.get("start"):
            start, end = raw["start"], raw.get("end") or local_today()
        else:
            start, end = days_back(raw.get("days", 1))
        opts: dict[str, Any] = {"start": start, "end": end}
        if source == "newsweb":
            if raw.get("detail_categories"):
                opts["detail_categories"] = raw["detail_categories"]
            opts["attachments"] = raw.get("attachments", False)
        return opts
    if source == "fi-short":
        return {"history": raw.get("history", False)}
    if source == "no-short":
        return {}
    if source == "nordnet":
        return {"countries": raw.get("countries") or ("NO", "SE")}
    if source == "mfn":
        names = universe_names(store, raw.get("universe", []), raw.get("limit"))
        since = datetime.now(timezone.utc) - timedelta(days=raw.get("days", 30))
        return {"slugs": raw.get("slugs", []), "company_names": names, "since": since,
                "max_pages": raw.get("max_pages", 5)}
    if source == "yahoo":
        symbols = list(raw.get("symbols", []))
        if raw.get("universe"):
            symbols += universe_symbols(store, raw["universe"], raw.get("limit"))
        return {"symbols": symbols, "range_": raw.get("range_", "5d"), "interval": raw.get("interval", "1d")}
    raise ValueError(f"unknown source {source}")


def universe_names(store: Store, countries: list[str], limit: int | None) -> list[str]:
    if not countries:
        return []
    t = store.table("instruments")
    name = func.coalesce(t.c.issuer_name, t.c.long_name, t.c.name).label("name")
    rows = store.query(
        select(name).distinct().where(t.c.is_tradable.is_(True), t.c.exchange_country.in_(countries))
    )
    names = sorted(r["name"] for r in rows if r["name"])
    return names[:limit] if limit else names


def run_source(store: Store, client: PoliteClient, source: str, **options: Any) -> RunSummary | None:
    """Run one collector and log it in ``runs``; returns None (after logging) if it failed."""
    collector = COLLECTORS[source](client, store)
    run_id = store.start_run(source)
    try:
        summary = collector.run(**options)
    except Exception as exc:  # record the failure and let other sources run
        store.finish_run(run_id, ok=False, summary=collector.summary.as_dict(),
                         error=f"{type(exc).__name__}: {exc}")
        log.error("%s failed: %s", source, exc, exc_info=log.isEnabledFor(logging.DEBUG))
        return None
    store.finish_run(run_id, ok=True, summary=summary.as_dict())
    return summary


def run_set(store: Store, client: PoliteClient, name: str) -> list[tuple[str, RunSummary | None]]:
    results = []
    for source, raw in SETS[name]:
        results.append((source, run_source(store, client, source, **options_for(store, source, raw))))
    return results


def format_summary(source: str, summary: RunSummary) -> str:
    tables = ", ".join(f"{table} +{r.inserted} new/{r.updated} seen" for table, r in summary.tables.items())
    line = f"{source}: {summary.fetches} requests; {tables or 'no rows'}"
    return line + "".join(f"\n  warning: {w}" for w in summary.warnings)
