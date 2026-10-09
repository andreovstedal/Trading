"""The Lekepenger page: the play-money stock account (``advisor.paper``), the short-term signals followed on paper
(``advisor.paper_signals``), and the downloadable log."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterator
from datetime import datetime, time, timezone
from typing import Any

from .. import text
from ..advisor import paper, paper_signals
from ..advisor.scoring import MODEL_VERSION
from ..collectors.base import NORDIC_TZ
from ..store import Store, utcnow
from . import charts, exports

TRADE_ROWS = 30
DAY_ROWS = 10
SIGNAL_ROWS = 20
SLEEVES = {"long": "Langsiktig", "short": "Kortsiktig"}
INDEX_NAMES = {"NO": "Oslo Børs Benchmark Index", "SE": "OMX Stockholm Benchmark"}  # paper.INDEXES, with dividends
SIDES = {"buy": "Kjøp", "sell": "Salg"}
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")
MONTHS = ("januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober", "november",
          "desember")
VALUED_AT = time(17, 30)  # a day's value is at the close: Stockholm's, the later of the two


def find(konto: str | None, now: datetime | None = None) -> paper.Version | None:
    """The account called ``konto`` once it has started; without a name, the current one."""
    now = now or utcnow()
    return paper.named(konto, now) if konto else paper.version_on(paper.evening_of(now))


def context(store: Store, now: datetime | None = None, version: paper.Version | None = None) -> dict[str, Any]:
    now = now or utcnow()
    current = paper.version_on(paper.evening_of(now))
    account = paper.account(store, now, version or current)
    points = [(datetime.combine(day, VALUED_AT, NORDIC_TZ), equity) for day, equity, _ in account["history"]]
    yardstick = [(datetime.combine(day, VALUED_AT, NORDIC_TZ), value)
                 for day, value in (account["yardstick"] or {}).get("history", [])]
    if points and account["started_on"]:  # from the start: the evening of the first decision, all in cash
        first = (datetime.combine(account["started_on"], VALUED_AT, NORDIC_TZ), account["start"])
        points.insert(0, first)
        yardstick.insert(0, first)
    pending = []
    for o in account["pending"]:
        opening = paper.next_opening(o["country"], o["decided_on"])
        pending.append({**o, "opening": opening, "opened": opening is not None and opening <= now})
    markets = [paper.market_status(c, now) for c in paper.MARKETS]
    version = account["version"]
    signals = paper_signals.record(store, now)
    earlier = version is not current
    first_evening, first_tonight = (None, False) if account["orders"] or earlier else _first_evening(store, version, now)
    return {
        "a": account, "now": now, "markets": markets,
        "today": now.astimezone(NORDIC_TZ).date(), "open_now": any(m["open"] for m in markets),
        "chart": charts.account_chart(points, account["start"], money=text.nok, daily=True, yardstick=yardstick),
        "y": account["yardstick"], "indexes": INDEX_NAMES,
        "history": points, "pending": pending, "trades": account["trades"][::-1][:TRADE_ROWS],
        "days": paper.days(store, DAY_ROWS, version), "sleeves": SLEEVES, "sides": SIDES,
        "version": version, "policy": version.policy, "cut_keeps": paper.CUT_KEEPS,
        "rebalance_months": [MONTHS[m - 1] for m in version.rebalance_months or ()],
        "current": current, "earlier": earlier, "until": account["valued_on"] if earlier else None,
        "finished": [] if earlier else paper.finished(store, now),
        "signals": signals, "signal_rows": signals["events"][:SIGNAL_ROWS],
        "signal_names": paper_signals.SIGNALS,
        "fees": {"courtage": paper.COURTAGE, "minimum": paper.COURTAGE_MIN, "exchange": paper.FX_SPREAD,
                 "dividend_tax": paper.SE_DIVIDEND_TAX},
        "rules": {"hold_rank": version.hold_rank * version.policy["max_positions"], "short_hold": paper.SHORT_HOLD,
                  "max_new_short": paper.MAX_NEW_SHORT, "order_days": paper.ORDER_DAYS,
                  "max_per_sector": paper.PARAMS["max_per_sector"]},
        "first_evening": first_evening, "first_tonight": first_tonight,
    }


def _first_evening(store: Store, version: paper.Version, now: datetime) -> tuple[datetime | None, bool]:
    """When a new account decides first, and whether that is tonight: from 20:45 UTC on a trading day the nightly
    collection may still be running, and the decision is made once it is done."""
    tonight = paper.evening_of(now)
    starts = datetime.combine(tonight, paper.EVENING, timezone.utc)
    if (starts <= now and tonight >= version.first_evening
            and any(paper.trading_hours(c, tonight) for c in paper.MARKETS)
            and not store.get("paper_days", account=version.name, decided_on=tonight)):
        return starts, True
    return paper.next_evening(now), False


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


def export_csv(store: Store, now: datetime | None = None, version: paper.Version | None = None) -> Iterator[str]:
    """Every trade of ``version`` (the current account by default), oldest first: semicolons, decimal commas and a
    byte-order mark, for Excel with Norwegian settings."""
    now = now or utcnow()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([header for header, _, _ in CSV_COLUMNS])
    yield "﻿" + exports.drain(out)
    for trade in paper.account(store, now, version)["trades"]:
        writer.writerow([exports.cell(get(trade), digits) for _, get, digits in CSV_COLUMNS])
    yield exports.drain(out)


def export_json(store: Store, now: datetime | None = None, version: paper.Version | None = None) -> Iterator[str]:
    """Everything about ``version`` (the current account by default), for analysis in code: the evenings'
    decisions, the orders and what became of them, the trades, the holdings, the dividends and the value day by
    day; and every account's signals on paper, and the finished accounts' results."""
    now = now or utcnow()
    account = paper.account(store, now, version)
    filled = {t["order_id"]: t["shares"] for t in account["trades"]}
    waiting = {o["id"] for o in account["pending"]}
    lapsed = {o["id"]: o["status"] for o in account["lapsed"]}
    orders = [{**o, "status": _status(o, filled, waiting), "note": lapsed.get(o["id"]) or _cut(o, filled)}
              for o in account["orders"]]
    positions = [{k: p[k] for k in ("instrument_id", "symbol", "name", "country", "currency", "sleeve", "shares",
                                    "opened_on", "cost", "price", "rate", "value", "result", "result_pct",
                                    "held_days", "reason", "signal_type")} for p in account["positions"]]
    yield '{"meta": ' + exports.to_json(_meta(account, now))
    yield ',\n"days": [' + ",\n".join(exports.to_json(d) for d in paper.days(store, None, account["version"])) + "]"
    yield ',\n"orders": [' + ",\n".join(exports.to_json(o) for o in orders) + "]"
    yield ',\n"trades": [' + ",\n".join(exports.to_json(t) for t in account["trades"]) + "]"
    yield ',\n"positions": [' + ",\n".join(exports.to_json(p) for p in positions) + "]"
    yield ',\n"dividends": [' + ",\n".join(exports.to_json(d) for d in account["dividends"]) + "]"
    beside = dict((account["yardstick"] or {}).get("history", []))
    yield ',\n"equity": [' + ",\n".join(exports.to_json({"day": day, "equity": equity, "cash": cash,
                                                          "yardstick": beside.get(day)})
                                        for day, equity, cash in account["history"]) + "]"
    signals = paper_signals.record(store, now)
    yield ',\n"signals": {"summary": ' + exports.to_json({"total": signals["total"], "types": signals["types"]})
    yield ',\n"events": [' + ",\n".join(exports.to_json(e) for e in signals["events"]) + "]}"
    yield ',\n"finished_accounts": ' + exports.to_json(paper.finished(store, now)) + "}\n"


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
        "account": account["account"],
        "versions": [{"account": v.name, "first_evening": v.first_evening, "about": v.about, "policy": v.policy,
                      "hold_rank": v.hold_rank * v.policy["max_positions"],
                      "rebalance_months": v.rebalance_months} for v in paper.VERSIONS],
        "model_version": MODEL_VERSION,
        "start_nok": paper.START,
        "equity_nok": account["equity"],
        "cash_nok": account["cash"],
        "valued_on": account["valued_on"],
        "policy": account["version"].policy,
        "fees": {"broker": "Nordnet Norge", "class": "Mini", "courtage_rate": paper.COURTAGE,
                 "courtage_min_nok": paper.COURTAGE_MIN, "currency_exchange": paper.FX_SPREAD,
                 "swedish_dividend_tax": paper.SE_DIVIDEND_TAX, "checked": "2026-10-04",
                 "source": "https://www.nordnet.no/kundeservice/prisliste"},
        "finished": account["version"] is not paper.version_on(paper.evening_of(now)),
        "rules": {"rebalance": "long-term part, the account's first evening, then the first trading evening of "
                               + (", ".join(MONTHS_EN[m - 1] for m in account["version"].rebalance_months)
                                  if account["version"].rebalance_months else "each month"),
                  "hold_rank": account["version"].hold_rank * account["version"].policy["max_positions"],
                  "max_per_sector": paper.PARAMS["max_per_sector"],
                  "short_hold_trading_days": paper.SHORT_HOLD, "max_new_short_per_evening": paper.MAX_NEW_SHORT,
                  "order_lapses_after_trading_days": paper.ORDER_DAYS},
        "markets": {c: {"name": m.name, "opens": m.opens.isoformat("minutes"), "closes": m.closes.isoformat("minutes")}
                    for c, m in paper.MARKETS.items()},
        "yardstick": {
            "indexes": {c: {"yahoo": symbol, "name": INDEX_NAMES[c] + " (gross, dividends reinvested)"}
                        for c, symbol in paper.INDEXES.items()},
            "method": "The same money in each market's index, at the same times as the account: what it held at a "
                      "close earns the index from that close, what it bought at an opening from that opening, and "
                      "what it sold at an opening the index's move up to it; Stockholm's index in NOK at SEK/NOK; "
                      "cash earns nothing. No fees or fund costs.",
            "valued_on": (account["yardstick"] or {}).get("valued_on"),
            "result": (account["yardstick"] or {}).get("result"),
            "account_result_same_day": (account["yardstick"] or {}).get("account_result"),
            "excess": (account["yardstick"] or {}).get("excess"),
        },
        "notes": {
            "days": "One row per evening the account decided, after both markets had closed: whether it was a "
                    "rebalance (meta.rules.rebalance), the recommendation it followed then, its value and cash at "
                    "that close, and notes.",
            "orders": "What it decided, for the next opening: shares planned, the closing price it saw (ref_price, "
                      "in the stock's currency; fx_rate is NOK per unit), the rank and score that evening. status: "
                      "utført (filled), delvis utført (fewer shares, see note), venter (waiting for the opening or "
                      "its prices) or bortfalt (see note).",
            "trades": "Fills at the opening price of the stock's next trading day (at_close: the opening price was "
                      "missing, so the closing price was used); planned is the order's shares, more than shares when "
                      "a buy was cut to the cash at the opening. fx_rate is SEK/NOK at that day's close, not at the "
                      "opening. value, courtage and exchange are NOK; cash is what the trade did to the cash; a "
                      "sale's result is against the purchase, fees included.",
            "positions": "Open holdings at the latest close (for a finished account, its last close). held_days "
                         "counts the market's trading days, the buying day being the first.",
            "dividends": "Credited on the ex-date, from Yahoo's dividend events; Swedish ones after withholding tax.",
            "equity": "The account's value at each trading day's close: cash plus holdings at their closing prices. "
                      "yardstick: the same money in the indexes (meta.yardstick), at the same times.",
            "signals": "Every short-term signal the accounts saw, each event once (the same stock and signal within "
                       "7 days of its first evening is the same event), followed on paper whether bought or not: "
                       "bought at the opening of its next trading day, sold at the close of its market's 5th "
                       "trading day, dividends in between included (dividend; Swedish after withholding tax); net "
                       "is after Nordnet's costs for 25 000 NOK, excess is net minus the market's index from that "
                       "opening to that close. bought: the account ordered it on one of the event's evenings. "
                       "Standard errors treat events as independent.",
            "finished_accounts": "Earlier versions of the account, at the close of their last trading day; each "
                                 "one's own log is at ?konto=<name>.",
        },
    }
