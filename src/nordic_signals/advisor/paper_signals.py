"""The short-term signals the stock account saw each evening (``paper_signals``), followed on paper.

Each is bought at the opening of the stock's next trading day, as the account would, and sold at the close of its
market's 5th trading day, the buying day being the first; after Nordnet's costs for a position of ``NOTIONAL``,
against the market's index over the same days (``paper.INDEXES``, from the opening to the close). Whether the
account bought it is noted, but the result is the same either way, so the record does not depend on the account's
slots or cash, and keeps growing after the account stopped buying them.

Each event counts once: a signal stays fresh for a few evenings (``features.EVENT_WINDOW``), so the same stock and
signal again within ``SAME_EVENT`` of its first evening is the same event. The standard errors treat the events as
independent; events on the same days move together, so they are a little too small.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from ..store import Store
from . import paper

SAME_EVENT = timedelta(days=7)
NOTIONAL = 25_000.0  # NOK: the costs are worked out for one short-term slot of the first account
SIGNALS = {"buyback_start": "Nytt tilbakekjøpsprogram", "insider_cluster": "Flere innsidere kjøpte"}


def record(store: Store, now: datetime | None = None) -> dict[str, Any]:
    """Every event, newest first, with its result once its 5 days are over, and the results per signal type and in
    all: count, mean net return over the index, its standard error and t."""
    t = store.table("paper_signals")
    events: list[dict[str, Any]] = []
    first: dict[tuple[int, str], date] = {}
    for r in store.query(select(t).order_by(t.c.decided_on, t.c.decided_at, t.c.instrument_id)):
        key = (r["instrument_id"], r["signal_type"])
        if key in first and r["decided_on"] - first[key] <= SAME_EVENT:
            continue
        first[key] = r["decided_on"]
        events.append(dict(r))
    if not events:
        return {"events": [], "types": [], "total": _stats([])}
    stocks = {e["instrument_id"]: e for e in events}
    prices = paper._prices(store, stocks, min(e["decided_on"] for e in events))
    indexes = paper._indexes(store)
    close = paper._closes(prices)
    latest = max((d for series in prices.values() for d in series), default=events[-1]["decided_on"])
    for e in events:
        e.update(_follow(e, prices.get(e["instrument_id"], {}), close, indexes.get(e["country"], {}), latest))
    done = [e for e in events if e["excess"] is not None]
    types = [{"signal_type": kind, "label": SIGNALS.get(kind, kind),
              **_stats([e for e in done if e["signal_type"] == kind])}
             for kind in sorted({e["signal_type"] for e in events})]
    return {"events": events[::-1], "types": types, "total": _stats(done)}


def _follow(e: dict[str, Any], series: dict[date, tuple], close: Any, index: dict[date, tuple],
            latest: date) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "venter", "entry_day": None, "exit_day": None, "ret": None, "costs": None,
                           "index_ret": None, "net": None, "excess": None}
    traded = sorted(d for d in series if d > e["decided_on"])
    window = paper.market_days(e["country"], e["decided_on"], latest)
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
    ret = sold / bought - 1
    cost = (sum(paper.costs(NOTIONAL, e["currency"])) + sum(paper.costs(NOTIONAL * (1 + ret), e["currency"])))
    out.update(status="ferdig", exit_day=exit_day, ret=ret, costs=cost / NOTIONAL, net=ret - cost / NOTIONAL)
    start, end = index.get(entry), [index[d] for d in sorted(index) if entry <= d <= exit_day]
    if start and end:
        out["index_ret"] = end[-1][1] / (start[0] or start[1]) - 1
        out["excess"] = out["net"] - out["index_ret"]
    return out


def _stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    values = [e["excess"] for e in events]
    n = len(values)
    mean = statistics.fmean(values) if values else None
    se = statistics.stdev(values) / n ** 0.5 if n >= 2 else None
    return {"n": n, "mean": mean, "se": se, "t": mean / se if se else None,
            "won": sum(v > 0 for v in values)}
