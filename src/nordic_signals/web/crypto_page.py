"""The Krypto page: the play-money crypto account (``crypto``) beside its buy-and-hold yardstick, and its log."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any

from .. import crypto, pumpfun, text
from ..store import Store, utcnow
from . import charts, exports

TRADE_ROWS = 30
CHECK_ROWS = 10
CHART_POINTS = 400
ACCOUNTS = {"trend": "Trendregelen", "hold": "Kjøp og hold"}
KINDS = {"start": "Start", "week": "Ukesjekk", "month": "Månedsskifte"}
SIDES = {"buy": "Kjøp", "sell": "Salg"}


def context(store: Store, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    books = crypto.accounts(store, now)
    a = books["trend"]
    points = thin(a["history"], CHART_POINTS)
    return {
        "a": a, "hold": books["hold"], "now": now,
        "chart": charts.account_chart(points, crypto.START, money=text.nok), "history": points,
        "trades": a["trades"][::-1][:TRADE_ROWS], "checks": a["checks"][::-1][:CHECK_ROWS],
        "parts": crypto.PARTS, "kinds": KINDS, "sides": SIDES,
        "rules": {"trend_days": crypto.TREND_DAYS, "tolerance": crypto.TOLERANCE, "pumpfun": crypto.PUMPFUN},
        "fees": {"trade": crypto.FEE, "sol_withdrawal": crypto.SOL_WITHDRAWAL},
    }


def thin(points: list[tuple[datetime, float]], most: int) -> list[tuple[datetime, float]]:
    """At most ``most`` points, evenly spaced, keeping the latest."""
    if len(points) <= most:
        return points
    step = math.ceil(len(points) / most)
    return [*points[::step], points[-1]] if (len(points) - 1) % step else points[::step]


# The downloadable log

CSV_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], Any], int | None], ...] = (
    ("Konto", lambda t: ACCOUNTS[t["account"]], None),
    ("Tidspunkt (norsk tid)", lambda t: t["at"], None),
    ("Bestemt (norsk tid)", lambda t: t["decided_at"], None),
    ("Hva", lambda t: KINDS[t["kind"]], None),
    ("Kjøp eller salg", lambda t: SIDES[t["side"]], None),
    ("Mynt", lambda t: t["asset"], None),
    ("Navn", lambda t: t["name"], None),
    ("Del", lambda t: crypto.PARTS[t["part"]], None),
    ("Antall", lambda t: t["qty"], 8),
    ("Kurs (NOK)", lambda t: t["price"], 4),
    ("Midtkurs (NOK)", lambda t: t["mid"], 4),
    ("Verdi (NOK)", lambda t: t["value"], 2),
    ("Gebyr (NOK)", lambda t: t["fee"], 2),
    ("Spread (NOK)", lambda t: t["spread"], 2),
    ("Uttak av SOL (NOK)", lambda t: t["withdrawal"], 2),
    ("Beløp på kontoen (NOK)", lambda t: t["cash"], 2),
    ("Resultat (NOK)", lambda t: t["result"], 2),
    ("Resultat (%)", lambda t: None if t["result_pct"] is None else t["result_pct"] * 100, 2),
    ("Begrunnelse", lambda t: t["reason"], None),
)


def export_csv(store: Store, now: datetime | None = None) -> Iterator[str]:
    """Both accounts' trades, oldest first: semicolons, decimal commas and a byte-order mark, for Excel with
    Norwegian settings."""
    books = crypto.accounts(store, now or utcnow())
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([header for header, _, _ in CSV_COLUMNS])
    yield "﻿" + exports.drain(out)
    trades = sorted(({**t, "account": name} for name, a in books.items() for t in a["trades"]),
                    key=lambda t: (t["at"], t["account"] != "trend"))
    for trade in trades:
        writer.writerow([exports.cell(get(trade), digits) for _, get, digits in CSV_COLUMNS])
    yield exports.drain(out)


def export_json(store: Store, now: datetime | None = None) -> Iterator[str]:
    """Everything, for analysis in code: each account's trades, its checks with the trend rule's view of every coin,
    its holdings and its value at every price collection."""
    now = now or utcnow()
    books = crypto.accounts(store, now)
    yield '{"meta": ' + exports.to_json(_meta(now))
    for name, a in books.items():
        summary = {k: a[k] for k in ("started_at", "valued_at", "equity", "cash", "result", "fees", "spread",
                                     "withdrawals", "costs", "parts", "coins", "pumpfun", "pending")}
        yield f',\n"{name}": {{"summary": ' + exports.to_json(summary)
        yield ',\n"trades": [' + ",\n".join(exports.to_json(t) for t in a["trades"]) + "]"
        yield ',\n"checks": [' + ",\n".join(exports.to_json(c) for c in a["checks"]) + "]"
        yield ',\n"equity": [' + ",\n".join(exports.to_json({"at": at, "equity": v}) for at, v in a["history"]) + "]}"
    yield "}\n"


def _meta(now: datetime) -> dict[str, Any]:
    return {
        "exported_at": now,
        "account": crypto.ACCOUNT,
        "start_nok": crypto.START,
        "started_at": crypto.STARTED_AT,
        "exchange": "Firi",
        "coins": [{"symbol": c.symbol, "name": c.name, "part": c.part, "weight": c.weight, "market": c.market,
                   "daily_closes": c.yahoo} for c in crypto.COINS],
        "pumpfun": {"weight": crypto.PUMPFUN, "follows": pumpfun.MAIN_ACCOUNT,
                    "screen_version": pumpfun.SCREEN_VERSION},
        "rules": {"trend_days": crypto.TREND_DAYS, "tolerance": crypto.TOLERANCE,
                  "trend": "trend: a coin is held while its latest daily close is above its average over trend_days "
                           "days, checked on Mondays at 00:00 UTC; hold: always held",
                  "rebalance": "first of each month at 00:00 UTC, for every coin held and the pump.fun part, unless "
                               "within tolerance of its target"},
        "fees": {"trade": crypto.FEE, "sol_withdrawal_sol": crypto.SOL_WITHDRAWAL, "checked": "2026-10-05",
                 "source": "https://firi.com/no/priser"},
        "notes": {
            "trades": "Market orders at the first prices collected after the decision (at): bought at Firi's best "
                      "ask, sold at its best bid; mid is the middle of the two. value, fee, spread and withdrawal are "
                      "NOK; cash is what the trade did to the cash. qty is coins, or SOL for the pump.fun part, "
                      "whose SOL is sent to a wallet for sol_withdrawal_sol (withdrawal). A sale's result is against "
                      "the average cost, fees and spread included.",
            "checks": "Every decision: start, week (the trend rule's Monday check) or month (rebalancing, with the "
                      "trend rule's check). views: each coin's latest daily close before the decision (USD, from "
                      "Yahoo), its average over trend_days days and the gap; wanted: whether the account holds it.",
            "equity": "The account's value at each price collection (every 15 minutes; hourly after a week): coins "
                      "at the middle of Firi's best bid and ask, and the pump.fun part's SOL.",
            "pumpfun": "The pump.fun part moves with the pump.fun page's main fake account (follows), in SOL, and "
                       "with the price of SOL.",
        },
    }
