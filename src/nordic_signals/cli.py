"""Command-line entry point: run collectors and inspect what has been stored.

    nordic-signals collect nordnet                  # universe, owners, key ratios (NO + SE)
    nordic-signals collect newsweb --days 2         # Oslo announcements
    nordic-signals collect fi-insider --days 3      # Swedish insider trades
    nordic-signals collect fi-short                 # Swedish short positions
    nordic-signals collect no-short                 # Norwegian short positions
    nordic-signals collect mfn --slug nibe-industrier
    nordic-signals collect yahoo --symbol EQNR.OL --range 1y
    nordic-signals collect intraday                 # today's announcements and insider trades
    nordic-signals collect daily                    # the end-of-day set
    nordic-signals collect backfill                 # one-off history load for a new database
    nordic-signals nightly                          # the daily set, then evaluate past recommendations
    nordic-signals recommend --account-value 300000 # suggest a split from stored data
    nordic-signals evaluate                         # score past recommendations against prices
    nordic-signals web                              # run the web app
    nordic-signals status

The database is taken from --db, else the DATABASE_URL environment variable
(PostgreSQL on Railway), else a local SQLite file at data/signals.sqlite.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timezone
from typing import Any

from sqlalchemy import select

from . import text
from .advisor import Policy, recommend
from .advisor import evaluate as evaluation
from .http import PoliteClient
from .jobs import SETS, format_summary, options_for, run_source
from .store import Store

log = logging.getLogger("nordic_signals")

COUNTRIES = ["NO", "SE", "DK", "FI"]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.INFO if args.verbose else logging.WARNING)

    if not args.db and not os.environ.get("DATABASE_URL") and os.environ.get("RAILWAY_ENVIRONMENT_ID"):
        # A container's filesystem is thrown away after each run, so a local SQLite file would lose everything.
        log.error("DATABASE_URL is not set. Add a PostgreSQL database to the Railway project and set this"
                  " service's DATABASE_URL variable to ${{Postgres.DATABASE_URL}}.")
        return 2

    if args.command == "web":
        from .web.app import (
            serve,  # imported here so collector jobs don't need the web stack loaded
        )

        serve(db=args.db, host=args.host, port=args.port)
        return 0

    with Store(args.db) as store:
        if args.command == "status":
            _print_status(store)
            return 0
        if args.command == "recommend":
            return _recommend(store, args)
        if args.command == "evaluate":
            print(f"{evaluation.evaluate(store)} new outcomes")
            return 0
        if args.command == "nightly":
            with PoliteClient() as client:
                results = [_run(store, client, name, **options_for(store, name, raw)) for name, raw in SETS["daily"]]
            print(f"{evaluation.evaluate(store)} new outcomes")
            return 0 if all(results) else 1
        with PoliteClient() as client:
            runs = SETS[args.source] if args.source in SETS else [(args.source, vars(args))]
            results = [_run(store, client, name, **options_for(store, name, raw)) for name, raw in runs]
            return 0 if all(results) else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nordic-signals", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="database URL or SQLite file path"
                                     " (default: $DATABASE_URL, else data/signals.sqlite)")
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

    p = sources.add_parser("yahoo-sektor", help="Yahoo's sector and industry per share (monthly)")
    p.add_argument("--symbol", action="append", default=[], dest="symbols", help="a Yahoo symbol, e.g. FRO.OL")
    p.add_argument("--universe", action="append", choices=COUNTRIES, default=[],
                   help="all tradable shares in the stored Nordnet universe")
    p.add_argument("--limit", type=int, help="at most this many shares not looked up in the last 30 days")

    p = sources.add_parser("nordnet", help="Nordnet stock list: universe, owners, key ratios")
    p.add_argument("--country", action="append", choices=COUNTRIES, dest="countries")

    p = sources.add_parser("pumpfun", help="pump.fun launches for the pump-and-dump measurement (no trading)")
    p.add_argument("--sample", type=int, default=50,
                   help="new launches to score per run (default 50: every launch in pump.fun's list)")

    sources.add_parser("krypto", help="Firi order books and daily closes for the play-money crypto account")

    for set_name, runs in SETS.items():
        sources.add_parser(set_name, help=f"{set_name} set: " + ", ".join(name for name, _ in runs))

    p = commands.add_parser("recommend", help="score the universe and suggest a split from stored data")
    p.add_argument("--account-value", type=float, required=True, help="account value in NOK")
    p.add_argument("--long", type=float, default=90.0, help="percent in the long-term sleeve (default 90)")
    p.add_argument("--short", type=float, default=10.0, help="percent in the short-term sleeve (default 10)")
    p.add_argument("--max-positions", type=int, default=12)
    p.add_argument("--min-position", type=float, default=20_000.0, help="smallest position in NOK")
    p.add_argument("--ask", action="store_true", help="Norwegian ASK: regulated markets only")
    p.add_argument("--trade-short", action="store_true", help="give the short-term sleeve real money")
    p.add_argument("--refresh", action="store_true", help="run the refresh collectors first")

    commands.add_parser("evaluate", help="compute outcomes for past recommendations")
    commands.add_parser("nightly", help="the daily collector set, then evaluate past recommendations")

    p = commands.add_parser("web", help="run the web app")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    return parser


def _add_dates(p: argparse.ArgumentParser, *, default_days: int) -> None:
    p.add_argument("--days", type=int, default=default_days,
                   help="last N local calendar days, today included (default: %(default)s)")
    p.add_argument("--start", type=date.fromisoformat, help="first date, YYYY-MM-DD (overrides --days)")
    p.add_argument("--end", type=date.fromisoformat, help="last date, YYYY-MM-DD (default: today)")


def _run(store: Store, client: PoliteClient, source: str, **options: Any) -> bool:
    summary = run_source(store, client, source, **options)
    if summary is not None:
        print(format_summary(source, summary))
    return summary is not None


def _recommend(store: Store, args: argparse.Namespace) -> int:
    policy = Policy(account_value=args.account_value, long_pct=args.long, short_pct=args.short,
                    max_positions=args.max_positions, min_position=args.min_position,
                    ask_only=args.ask, short_paper_only=not args.trade_short)
    rec_id = recommend.create(store, policy)

    def refresh() -> dict[str, Any]:
        with PoliteClient() as client:
            return {name: _run(store, client, name, **options_for(store, name, raw)) for name, raw in SETS["refresh"]}

    recommend.run(store, rec_id, refresh=refresh if args.refresh else None)
    rec = store.get("recommendations", id=rec_id)
    if rec["status"] != "done":
        log.error("recommendation %s failed: %s", rec_id, rec["error"])
        return 1
    scores = store.table("scores")
    lines = store.query(select(scores).where(scores.c.recommendation_id == rec_id, scores.c.long_shares > 0)
                        .order_by(scores.c.rank))
    # The advice itself is in Norwegian, like the web app; the collectors' logs stay in English.
    print(f"Anbefaling {rec_id} (modell {rec['model_version']}): {len(lines)} posisjoner")
    for line in lines:
        print(f"  {line['rank']:>3}. {line['symbol']:<10} {line['name'][:28]:<28}"
              f" {text.number(line['long_shares']):>7} aksjer  {text.nok(line['long_amount']):>12}"
              f"  poeng {text.number(line['score'], 2)}  " + "; ".join(line["reasons"] or []))
    for note in rec["summary"]["notes"]:
        print(f"  Merk: {note}")
    print(f"  Kontanter: {text.nok(rec['summary']['cash'])}")
    return 0


def _print_status(store: Store) -> None:
    print("Rows per table:")
    for table, count in store.table_counts().items():
        print(f"  {table:<22} {count:>9}")
    print("Latest run per source:")
    for row in store.last_runs():
        state = "ok" if row["ok"] else ("running" if row["ok"] is None else f"FAILED ({row['error']})")
        started = row["started_at"]
        if started.tzinfo is not None:  # PostgreSQL returns aware datetimes in the session time zone
            started = started.astimezone(timezone.utc)
        print(f"  {row['source']:<12} {started:%Y-%m-%d %H:%M} UTC  {state}")


if __name__ == "__main__":
    sys.exit(main())
