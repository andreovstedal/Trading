"""The short-term signals the stock account saw each evening (``paper_signals``), followed on paper.

Each is bought at the opening of the stock's next trading day, as the account would, and sold at the close of its
market's 5th trading day, the buying day being the first, with any dividend in between (Swedish ones after the
withholding tax); after Nordnet's costs for a position of ``NOTIONAL``, against the market's index over the same days
(``paper.INDEXES``, with dividends, from the opening to the close). Only days whose close is in count: until 18:00
Norwegian time, today is not over. Whether the account ordered it is noted, but the result is the same either way,
so the record does not depend on the account's slots or cash, and keeps growing after the account stopped buying
them.

Each event counts once: a signal stays fresh for a few evenings (``features.EVENT_WINDOW``), so the same stock and
signal again within ``SAME_EVENT`` of its first evening is the same event, ordered if the account ordered it on any
of those evenings. The standard errors treat the events as independent; events on the same days move together, so
they are a little too small.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..collectors.base import NORDIC_TZ
from ..store import Store
from . import paper

SAME_EVENT = timedelta(days=7)
NOTIONAL = 25_000.0  # NOK: the costs are worked out for one short-term slot of the first account
FOLLOW = timedelta(days=35)  # more than enough calendar days for an event's ORDER_DAYS and SHORT_HOLD, holidays too
SIGNALS = {"buyback_start": "Nytt tilbakekjøpsprogram", "insider_cluster": "Flere innsidere kjøpte"}


def record(store: Store, now: datetime | None = None) -> dict[str, Any]:
    """Every event, newest first, with its result once its 5 days are over, and the results per signal type and in
    all: count, mean net return over the index, its standard error and t."""
    now = now or paper.utcnow()
    t = store.table("paper_signals")
    events: list[dict[str, Any]] = []
    first: dict[tuple[int, str], dict[str, Any]] = {}
    for r in store.query(select(t).order_by(t.c.decided_on, t.c.decided_at, t.c.instrument_id)):
        key = (r["instrument_id"], r["signal_type"])
        if key in first and r["decided_on"] - first[key]["decided_on"] <= SAME_EVENT:
            first[key]["bought"] = bool(first[key]["bought"] or r["bought"])
            continue
        first[key] = {**r, "bought": bool(r["bought"])}
        events.append(first[key])
    if not events:
        return {"events": [], "types": [], "total": _stats([])}
    prices = _prices(store, events)
    stocks = {e["instrument_id"]: e for e in events}
    dividends: dict[int, list[tuple[date, float, str]]] = defaultdict(list)
    for ex_date, instrument_id, amount, currency in paper._dividends(store, stocks,
                                                                   min(e["decided_on"] for e in events)):
        dividends[instrument_id].append((ex_date, amount, currency))
    indexes, fx = paper._indexes(store), paper._fx(store)
    close = paper._closes(prices)
    local = now.astimezone(NORDIC_TZ)
    closed = local.date() if local.time() >= paper.AFTER_CLOSE else local.date() - timedelta(days=1)
    latest = min(closed, max((d for series in prices.values() for d in series), default=closed))
    for e in events:
        e.update(_follow(e, prices.get(e["instrument_id"], {}), close, indexes.get(e["country"], {}), latest,
                         dividends.get(e["instrument_id"], []), fx))
    done = [e for e in events if e["excess"] is not None]
    types = [{"signal_type": kind, "label": SIGNALS.get(kind, kind),
              **_stats([e for e in done if e["signal_type"] == kind])}
             for kind in sorted({e["signal_type"] for e in events})]
    return {"events": events[::-1], "types": types, "total": _stats(done)}


def _prices(store: Store, events: list[dict[str, Any]]) -> dict[int, dict[date, tuple]]:
    """Each event's stock from its evening to ``FOLLOW`` after, a month's events at a time, so the work grows with
    the number of events rather than with every signal stock's whole history."""
    months: dict[date, dict[int, dict[str, Any]]] = defaultdict(dict)
    for e in events:
        months[e["decided_on"].replace(day=1)][e["instrument_id"]] = e
    out: dict[int, dict[date, tuple]] = defaultdict(dict)
    for month, stocks in months.items():
        month_end = (month + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        for instrument_id, series in paper._prices(store, stocks, month, month_end + FOLLOW).items():
            out[instrument_id].update(series)
    return out


def _follow(e: dict[str, Any], series: dict[date, tuple], close: Any, index: dict[date, tuple], latest: date,
            dividends: list[tuple[date, float, str]], fx: dict[str, list[tuple[date, float]]]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "venter", "entry_day": None, "exit_day": None, "ret": None, "dividend": None,
                           "costs": None, "index_ret": None, "net": None, "excess": None}
    traded = sorted(d for d in series if e["decided_on"] < d <= latest)
    window = paper.market_days(e["country"], e["decided_on"], min(latest, e["decided_on"] + FOLLOW))
    if not traded or (len(window) >= paper.ORDER_DAYS and traded[0] > window[paper.ORDER_DAYS - 1]):
        if len(window) >= paper.ORDER_DAYS:
            out["status"] = f"ikke handlet på {paper.ORDER_DAYS} handelsdager"
        return out
    entry = traded[0]
    held = [d for d in window if d >= entry][:paper.SHORT_HOLD]
    out["entry_day"] = entry
    if len(held) < paper.SHORT_HOLD:
        return out
    exit_day = held[-1]
    bought, sold = series[entry][0] or series[entry][1], close(e["instrument_id"], exit_day)
    moved = sold / bought - 1
    paid = sum(_in_stock_currency(amount, currency, e["currency"], ex_date, fx)
               for ex_date, amount, currency in dividends if entry < ex_date <= exit_day)
    if e["country"] == "SE":
        paid *= 1 - paper.SE_DIVIDEND_TAX
    cost = sum(paper.costs(NOTIONAL, e["currency"])) + sum(paper.costs(NOTIONAL * (1 + moved), e["currency"]))
    ret = moved + paid / bought
    out.update(status="ferdig", exit_day=exit_day, ret=ret, dividend=paid / bought, costs=cost / NOTIONAL,
               net=ret - cost / NOTIONAL)
    out["index_ret"] = _index_return(index, entry, exit_day)
    if out["index_ret"] is None:
        out["status"] = "venter på indeksen"
    else:
        out["excess"] = out["net"] - out["index_ret"]
    return out


def _index_return(index: dict[date, tuple], entry: date, exit_day: date) -> float | None:
    """From the entry day's opening to the exit day's close; without an opening, from the close before it (as if
    it opened where it closed, as the account's yardstick does). None while the exit day's close is missing."""
    if exit_day not in index:
        return None
    opening = index[entry][0] if entry in index else None
    if opening is None:
        before = [d for d in index if d < entry]
        if not before:
            return None
        opening = index[max(before)][1]
    return index[exit_day][1] / opening - 1


def _in_stock_currency(amount: float, currency: str | None, stock_currency: str | None, day: date,
                       fx: dict[str, list[tuple[date, float]]]) -> float:
    paid, unit = paper._rate(fx, currency, day), paper._rate(fx, stock_currency, day)
    return amount * paid / unit if paid and unit else (amount if currency == stock_currency else 0.0)


def _stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    values = [e["excess"] for e in events]
    n = len(values)
    mean = statistics.fmean(values) if values else None
    se = statistics.stdev(values) / n ** 0.5 if n >= 2 else None
    return {"n": n, "mean": mean, "se": se, "t": mean / se if se else None,
            "won": sum(v > 0 for v in values)}
