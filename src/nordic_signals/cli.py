"""Command-line entry point: run collectors and inspect what has been stored.

    nordic-signals collect nordnet                  # universe, owners, key ratios (NO + SE)
    nordic-signals collect newsweb --days 2         # Oslo announcements
    nordic-signals collect fi-insider --days 3      # Swedish insider trades
    nordic-signals collect fi-short                 # Swedish short positions
    nordic-signals collect no-short                 # Norwegian short positions
    nordic-signals collect mfn --slug nibe-industrier
    nordic-signals collect yahoo --symbol EQNR.OL --range 1y
    nordic-signals collect daily                    # the end-of-day set
    nordic-signals status
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .collectors import COLLECTORS, RunSummary
from .collectors.base import days_back, local_today
from .collectors.yahoo import universe_symbols
from .http import PoliteClient
from .store import Store

log = logging.getLogger("nordic_signals")

COUNTRIES = ["NO", "SE", "DK", "FI"]

# What "collect daily" runs, in order. MFN and Yahoo need a watchlist, so
# they are scheduled separately.
DAILY = [
    ("nordnet", {"countries": ("NO", "SE")}),
    ("newsweb", {"days": 2}),
    ("fi-insider", {"days": 3}),
    ("fi-short", {}),
    ("no-short", {}),
]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO if args.verbose else logging.WARNING)

    with Store(args.db) as store:
        if args.command == "status":
            _print_status(store)
            return 0
        with PoliteClient() as client:
            if args.source == "daily":
                results = [_run(store, client, name, **_options(store, name, opts)) for name, opts in DAILY]
                return 0 if all(results) else 1
            return 0 if _run(store, client, args.source, **_options(store, args.source, vars(args))) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nordic-signals", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="data/signals.sqlite", help="SQLite file (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="row counts and the latest run per source")

    collect = commands.add_parser("collect", help="fetch a source and store raw + parsed data")
    sources = collect.add_subparsers(dest="source", required=True)

    p = sources.add_parser("newsweb", help="Oslo Børs NewsWeb announcements")
    _add_dates(p, default_days=1)
    p.add_argument("--detail-category", type=int, action="append", dest="detail_categories",
                   help="category id whose full text to fetch (repeatable; default: insider trades,"
                        " inside information, flagging, buybacks, annual and half-year reports)")
    p.add_argument("--attachments", action="store_true", help="also download attachments of those messages")

    p = sources.add_parser("fi-insider", help="Finansinspektionen insider register (Sweden)")
    _add_dates(p, default_days=3)

    p = sources.add_parser("fi-short", help="Finansinspektionen short-selling register (Sweden)")
    p.add_argument("--history", action="store_true", help="also fetch the historical positions file")

    sources.add_parser("no-short", help="Finanstilsynet short-sale register (Norway)")

    p = sources.add_parser("mfn", help="MFN per-company press-release feeds")
    p.add_argument("--slug", action="append", default=[], dest="slugs",
                   help="company slug as in https://mfn.se/all/a/<slug> (repeatable)")
    p.add_argument("--universe", action="append", choices=COUNTRIES, default=[],
                   help="also match company names from the stored Nordnet universe")
    p.add_argument("--limit", type=int, help="at most this many universe companies")
    p.add_argument("--days", type=int, default=30, help="page back until items are older than this")
    p.add_argument("--max-pages", type=int, default=5)

    p = sources.add_parser("yahoo", help="Yahoo chart API prices, dividends and splits")
    p.add_argument("--symbol", action="append", default=[], dest="symbols",
                   help="Yahoo symbol, e.g. EQNR.OL or VOLV-B.ST (repeatable)")
    p.add_argument("--universe", action="append", choices=COUNTRIES, default=[],
                   help="all tradable shares in the stored Nordnet universe (slow: ~4 s per symbol)")
    p.add_argument("--limit", type=int, help="at most this many universe symbols")
    p.add_argument("--range", dest="range_", default="5d", help="e.g. 5d, 1mo, 1y, 10y, max")
    p.add_argument("--interval", default="1d", help="e.g. 1m, 5m, 1h, 1d")

    p = sources.add_parser("nordnet", help="Nordnet stock list: universe, owners, key ratios")
    p.add_argument("--country", action="append", choices=COUNTRIES, dest="countries")

    sources.add_parser("daily", help="end-of-day set: " + ", ".join(name for name, _ in DAILY))
    return parser


def _add_dates(p: argparse.ArgumentParser, *, default_days: int) -> None:
    p.add_argument("--days", type=int, default=default_days,
                   help="last N local calendar days, today included (default: %(default)s)")
    p.add_argument("--start", type=date.fromisoformat, help="first date, YYYY-MM-DD (overrides --days)")
    p.add_argument("--end", type=date.fromisoformat, help="last date, YYYY-MM-DD (default: today)")


def _options(store: Store, source: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Turn parsed CLI arguments into keyword arguments for one collector."""
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
        names = _universe_names(store, raw.get("universe", []), raw.get("limit"))
        since = datetime.now(timezone.utc) - timedelta(days=raw.get("days", 30))
        return {"slugs": raw.get("slugs", []), "company_names": names, "since": since,
                "max_pages": raw.get("max_pages", 5)}
    if source == "yahoo":
        symbols = list(raw.get("symbols", []))
        if raw.get("universe"):
            symbols += universe_symbols(store, raw["universe"], raw.get("limit"))
        return {"symbols": symbols, "range_": raw.get("range_", "5d"), "interval": raw.get("interval", "1d")}
    raise ValueError(f"unknown source {source}")


def _universe_names(store: Store, countries: list[str], limit: int | None) -> list[str]:
    if not countries:
        return []
    rows = store.conn.execute(
        "SELECT DISTINCT COALESCE(issuer_name, long_name, name) FROM instruments"
        f" WHERE is_tradable = 1 AND exchange_country IN ({', '.join('?' * len(countries))})",
        countries,
    ).fetchall()
    names = sorted(r[0] for r in rows if r[0])
    return names[:limit] if limit else names


def _run(store: Store, client: PoliteClient, source: str, **options: Any) -> bool:
    collector = COLLECTORS[source](client, store)
    run_id = store.start_run(source)
    try:
        summary = collector.run(**options)
    except Exception as exc:  # record the failure and let other sources run
        store.finish_run(run_id, ok=False, summary=collector.summary.as_dict(),
                         error=f"{type(exc).__name__}: {exc}")
        log.error("%s failed: %s", source, exc, exc_info=log.isEnabledFor(logging.DEBUG))
        return False
    store.finish_run(run_id, ok=True, summary=summary.as_dict())
    print(_format(source, summary))
    return True


def _format(source: str, summary: RunSummary) -> str:
    tables = ", ".join(
        f"{table} +{r.inserted} new/{r.updated} seen" for table, r in summary.tables.items()
    )
    line = f"{source}: {summary.fetches} requests; {tables or 'no rows'}"
    return line + "".join(f"\n  warning: {w}" for w in summary.warnings)


def _print_status(store: Store) -> None:
    print("Rows per table:")
    for table, count in store.table_counts().items():
        print(f"  {table:<22} {count:>9}")
    print("Latest run per source:")
    for row in store.last_runs():
        state = "ok" if row["ok"] else f"FAILED ({row['error']})"
        print(f"  {row['source']:<12} {row['started_at']}  {state}")


if __name__ == "__main__":
    sys.exit(main())
