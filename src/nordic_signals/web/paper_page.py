"""The Lekepenger page: the play-money stock account (``advisor.paper``), and its downloadable log."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from datetime import datetime, time
from typing import Any

from .. import text
from ..advisor import paper
from ..advisor.scoring import MODEL_VERSION
from ..collectors.base import NORDIC_TZ
from ..store import Store, utcnow
from . import charts, exports

TRADE_ROWS = 30
DAY_ROWS = 10
SLEEVES = {"long": "Langsiktig", "short": "Kortsiktig"}
SIDES = {"buy": "Kjøp", "sell": "Salg"}
VALUED_AT = time(17, 30)  # a day's value is at the close: Stockholm's, the later of the two


def context(store: Store, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    account = paper.account(store, now)
    points = [(datetime.combine(day, VALUED_AT, NORDIC_TZ), equity) for day, equity, _ in account["history"]]
    if points and account["started_on"]:  # from the start: the evening of the first decision, all in cash
        points.insert(0, (datetime.combine(account["started_on"], VALUED_AT, NORDIC_TZ), account["start"]))
    pending = []
    for o in account["pending"]:
        opening = paper.next_opening(o["country"], o["decided_on"])
        pending.append({**o, "opening": opening, "opened": opening is not None and opening <= now})
    markets = [paper.market_status(c, now) for c in paper.MARKETS]
    return {
        "a": account, "now": now, "markets": markets,
        "today": now.astimezone(NORDIC_TZ).date(), "open_now": any(m["open"] for m in markets),
        "chart": charts.account_chart(points, account["start"], money=text.nok, daily=True),
        "history": points, "pending": pending, "trades": account["trades"][::-1][:TRADE_ROWS],
        "days": paper.days(store, DAY_ROWS), "sleeves": SLEEVES, "sides": SIDES, "policy": paper.POLICY,
        "fees": {"courtage": paper.COURTAGE, "minimum": paper.COURTAGE_MIN, "exchange": paper.FX_SPREAD,
                 "dividend_tax": paper.SE_DIVIDEND_TAX},
        "rules": {"hold_rank": paper.HOLD_RANK * paper.POLICY["max_positions"], "short_hold": paper.SHORT_HOLD,
                  "max_new_short": paper.MAX_NEW_SHORT, "order_days": paper.ORDER_DAYS},
        "first_evening": paper.next_evening(now) if not account["orders"] else None,
    }


# The downloadable log

CSV_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], Any], int | None], ...] = (
    ("Handelsdag", lambda t: t["day"].isoformat(), None),
    ("Tidspunkt (norsk tid)", lambda t: t["at"], None),
    ("Kjøp eller salg", lambda t: SIDES[t["side"]], None),
    ("Del", lambda t: SLEEVES[t["sleeve"]], None),
    ("Ticker", lambda t: t["symbol"], None),
    ("Navn", lambda t: t["name"], None),
    ("Børs", lambda t: paper.MARKETS[t["country"]].name if t["country"] in paper.MARKETS else t["country"], None),
    ("Valuta", lambda t: t["currency"], None),
    ("Antall", lambda t: t["shares"], 0),
    ("Kurs", lambda t: t["price"], 4),
    ("Valutakurs (NOK)", lambda t: t["fx_rate"], 4),
    ("Verdi (NOK)", lambda t: t["value"], 2),
    ("Kurtasje (NOK)", lambda t: t["courtage"], 2),
    ("Valutaveksling (NOK)", lambda t: t["exchange"], 2),
    ("Beløp på kontoen (NOK)", lambda t: t["cash"], 2),
    ("Resultat (NOK)", lambda t: t["result"], 2),
    ("Resultat (%)", lambda t: None if t["result_pct"] is None else t["result_pct"] * 100, 2),
    ("Til sluttkurs (mangler åpningskurs)", lambda t: t["at_close"], None),
    ("Begrunnelse", lambda t: t["reason"], None),
    ("Signal", lambda t: t["signal_type"], None),
    ("Ordre", lambda t: t["order_id"], 0),
)


def export_csv(store: Store) -> Iterator[str]:
    """Every trade, oldest first: semicolons, decimal commas and a byte-order mark, for Excel with Norwegian
    settings."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([header for header, _, _ in CSV_COLUMNS])
    yield "﻿" + exports.drain(out)
    for trade in paper.account(store)["trades"]:
        writer.writerow([exports.cell(get(trade), digits) for _, get, digits in CSV_COLUMNS])
    yield exports.drain(out)


def export_json(store: Store, now: datetime | None = None) -> Iterator[str]:
    """Everything, for analysis in code: the evenings' decisions, the orders and what became of them, the trades,
    the holdings, the dividends and the value day by day."""
    now = now or utcnow()
    account = paper.account(store, now)
    filled = {t["order_id"]: t["shares"] for t in account["trades"]}
    waiting = {o["id"] for o in account["pending"]}
    lapsed = {o["id"]: o["status"] for o in account["lapsed"]}
    orders = [{**o, "status": _status(o, filled, waiting), "note": lapsed.get(o["id"]) or _cut(o, filled)}
              for o in account["orders"]]
    positions = [{k: p[k] for k in ("instrument_id", "symbol", "name", "country", "currency", "sleeve", "shares",
                                    "opened_on", "cost", "price", "rate", "value", "result", "result_pct",
                                    "held_days", "reason", "signal_type")} for p in account["positions"]]
    yield '{"meta": ' + exports.to_json(_meta(account, now))
    yield ',\n"days": [' + ",\n".join(exports.to_json(d) for d in paper.days(store, None)) + "]"
    yield ',\n"orders": [' + ",\n".join(exports.to_json(o) for o in orders) + "]"
    yield ',\n"trades": [' + ",\n".join(exports.to_json(t) for t in account["trades"]) + "]"
    yield ',\n"positions": [' + ",\n".join(exports.to_json(p) for p in positions) + "]"
    yield ',\n"dividends": [' + ",\n".join(exports.to_json(d) for d in account["dividends"]) + "]"
    yield ',\n"equity": [' + ",\n".join(exports.to_json({"day": day, "equity": equity, "cash": cash})
                                        for day, equity, cash in account["history"]) + "]}\n"


def _status(o: dict[str, Any], filled: dict[int, int], waiting: set[int]) -> str:
    if o["id"] in filled:
        return "delvis utført" if filled[o["id"]] < o["shares"] else "utført"
    return "venter" if o["id"] in waiting else "bortfalt"


def _cut(o: dict[str, Any], filled: dict[int, int]) -> str | None:
    shares = filled.get(o["id"])
    if shares is not None and shares < o["shares"]:
        return f"{shares} av {o['shares']} aksjer: ikke nok penger ved åpningen"
    return None


def _meta(account: dict[str, Any], now: datetime) -> dict[str, Any]:
    return {
        "exported_at": now,
        "account": paper.ACCOUNT,
        "model_version": MODEL_VERSION,
        "start_nok": paper.START,
        "equity_nok": account["equity"],
        "cash_nok": account["cash"],
        "valued_on": account["valued_on"],
        "policy": paper.POLICY,
        "fees": {"broker": "Nordnet Norge", "class": "Mini", "courtage_rate": paper.COURTAGE,
                 "courtage_min_nok": paper.COURTAGE_MIN, "currency_exchange": paper.FX_SPREAD,
                 "swedish_dividend_tax": paper.SE_DIVIDEND_TAX, "checked": "2026-10-04",
                 "source": "https://www.nordnet.no/kundeservice/prisliste"},
        "rules": {"rebalance": "long-term part, first trading evening of each month",
                  "hold_rank": paper.HOLD_RANK * paper.POLICY["max_positions"],
                  "short_hold_trading_days": paper.SHORT_HOLD, "max_new_short_per_evening": paper.MAX_NEW_SHORT,
                  "order_lapses_after_trading_days": paper.ORDER_DAYS},
        "markets": {c: {"name": m.name, "opens": m.opens.isoformat("minutes"), "closes": m.closes.isoformat("minutes")}
                    for c, m in paper.MARKETS.items()},
        "notes": {
            "days": "One row per evening the account decided, after both markets had closed: whether it was the "
                    "monthly rebalance, the recommendation it followed then, its value and cash at that close, "
                    "and notes.",
            "orders": "What it decided, for the next opening: shares planned, the closing price it saw (ref_price, "
                      "in the stock's currency; fx_rate is NOK per unit), the rank and score that evening. status: "
                      "utført (filled), delvis utført (fewer shares, see note), venter (waiting for the opening or "
                      "its prices) or bortfalt (see note).",
            "trades": "Fills at the opening price of the stock's next trading day (at_close: the opening price was "
                      "missing, so the closing price was used); planned is the order's shares, more than shares when "
                      "a buy was cut to the cash at the opening. fx_rate is SEK/NOK at that day's close, not at the "
                      "opening. value, courtage and exchange are NOK; cash is what the trade did to the cash; a "
                      "sale's result is against the purchase, fees included.",
            "positions": "Open holdings at the latest close. held_days counts the market's trading days, the "
                         "buying day being the first.",
            "dividends": "Credited on the ex-date, from Yahoo's dividend events; Swedish ones after withholding tax.",
            "equity": "The account's value at each trading day's close: cash plus holdings at their closing prices.",
        },
    }
