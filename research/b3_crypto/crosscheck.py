"""Checks that ``engine`` replays the book the way the project's own account does.

``nordic_signals.crypto.account`` is run on the same closes, as if Firi's best bid and ask at 00:00 UTC each day
were the close of the day before minus and plus the spread, with its module constants set to this test's book:
the five coins at 31.25/31.25/12.5/12.5/12.5 %, no pump.fun part, starting on the test's first day, and the
average's length set to each rule's. Without tax, the two replays must end at the same value.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from nordic_signals import crypto

import engine


@contextmanager
def patched(weights: dict[str, float], start: date, days: int):
    saved = {k: getattr(crypto, k) for k in ("COINS", "COIN", "PUMPFUN", "STARTED_AT", "TREND_DAYS")}
    try:
        coins = tuple(replace(c, weight=weights[c.symbol]) for c in saved["COINS"])
        crypto.COINS = coins
        crypto.COIN = {c.symbol: c for c in coins}
        crypto.PUMPFUN = 0.0
        crypto.STARTED_AT = datetime.combine(start, time(0), timezone.utc)
        crypto.TREND_DAYS = days
        yield
    finally:
        for k, v in saved.items():
            setattr(crypto, k, v)


def prices(series: dict[str, engine.Series], spreads: dict[str, float], start: date, end: date) -> crypto.Prices:
    market = {c.symbol: c.market for c in crypto.COINS}
    runs = []
    day = start - timedelta(days=2)
    while day <= end:
        at = datetime.combine(day + timedelta(days=1), time(0), timezone.utc)
        runs.append((at, {market[c]: (s.close(day) * (1 - spreads[c]), s.close(day) * (1 + spreads[c]))
                          for c, s in series.items()}))
        day += timedelta(days=1)
    closes = {c: (s.days, s.values) for c, s in series.items()}
    return crypto.Prices(runs, closes)


def compare(series: dict[str, engine.Series], weights: dict[str, float], spreads: dict[str, float],
            start: date, end: date) -> list[dict]:
    """The value at the last close, in this engine and in ``crypto.account``, for buy and hold and each average."""
    out = []
    now = datetime.combine(end + timedelta(days=1), time(0), timezone.utc)
    for rule in (engine.HOLD,) + tuple(r for r in engine.RULES if r.kind == "sma"):
        ours = engine.run(rule, series, weights, spreads, start, end, tax=False).curve[-1][1]
        with patched(weights, start, rule.n or 200):
            theirs = crypto.account(None, now, trend=rule.kind == "sma",
                                    prices=prices(series, spreads, start, end))["equity"]
        out.append({"rule": rule.name, "engine": ours, "crypto_py": theirs, "difference": ours / theirs - 1})
    return out
