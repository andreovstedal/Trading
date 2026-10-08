"""Why this test's 200-day result differs from the README's ("Why the 200-day average").

The README's table came from a scratch script (not in the repository) that was run on 5-7 October 2026, before the
account's rules were settled. ``readme_run`` is that script's replay, ported line by line, with one switch for each
way it differs from ``crypto.py``'s replay, so the differences can be turned off one at a time:

* ``month_close``: it rebalanced on the first close of each month and read the rule on it; crypto.py decides at
  00:00 UTC on the first, on the closes before it, and trades at the last close of the month before.
* ``cost_inside``: it bought the whole gap to target and paid the fee and spread on top; crypto.py's purchase
  spends its money, costs included. (A sale got x (1 - fee - spread) instead of x (1 - spread)(1 - fee).)
* ``held_short``: it held no coin with too short a history; crypto.py holds it.
* ``final_sale``: it valued the book at the last close; this test sells everything at the bid at the end, paying
  the spread and the fee (added after the check, which found this step folded into the last one).
* The rest is crypto.py's month (``engine``): the cash part, money left over going to the parts below their target,
  a shortfall paid by those above, and trades under 10 left out. Its own month only traded the parts outside
  their band, and left any money over in cash.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import fmean

import engine

FEE = engine.FEE


def readme_run(series: dict[str, engine.Series], weights: dict[str, float], spreads: dict[str, float], start: date,
               end: date, n: int | None, *, month_close: bool = True, cost_inside: bool = False,
               held_short: bool = False, final_sale: bool = False) -> dict:
    """The README script's ``run`` (``n`` None for buy and hold, else the n-day average checked weekly)."""
    coins = list(weights)
    first = start if month_close else start - timedelta(days=1)
    days = []
    d = first
    while d <= end:
        if all(series[c].first <= d for c in coins):
            days.append(d)
        d += timedelta(days=1)

    def signal(c: str, d: date) -> bool:
        if n is None:
            return True
        s = series[c]
        k = s.upto(d)
        if k < n:
            return held_short
        return s.values[k - 1] > fmean(s.values[k - n:k])

    cash, units, state = 1.0, {c: 0.0 for c in coins}, {c: None for c in coins}
    curve, last_month = [], None
    for d in days:
        price = {c: series[c].close(d) for c in coins}
        value = cash + sum(units[c] * price[c] for c in coins)
        if month_close:
            month_start = (d.year, d.month) != last_month
        else:
            month_start = (d + timedelta(days=1)).day == 1 or d == first
        checking = month_start or (n is not None and d.weekday() == 6)
        if checking:
            new = {c: signal(c, d) for c in coins}

            def skip(c: str, held: float, target: float) -> bool:
                if new[c] and not month_start and state[c]:  # still in, not a rebalance day: leave it
                    return True
                return bool(new[c] and state[c] and month_start and abs(held - target) <= 0.2 * target)

            for c in coins:  # sales first
                target = weights[c] * value if new[c] else 0.0
                held = units[c] * price[c]
                if skip(c, held, target):
                    continue
                if held > target + 1e-12:
                    sold = held - target
                    cash += sold * ((1 - spreads[c]) * (1 - FEE) if cost_inside else 1 - FEE - spreads[c])
                    units[c] -= sold / price[c]
            for c in coins:
                target = weights[c] * value if new[c] else 0.0
                held = units[c] * price[c]
                if skip(c, held, target):
                    continue
                if target > held + 1e-12:
                    if cost_inside:
                        spend = min(target - held, cash)
                        if spend <= 0:
                            continue
                        units[c] += spend / (price[c] * (1 + spreads[c]) * (1 + FEE))
                        cash -= spend
                    else:
                        buy = min(target - held, cash / (1 + FEE + spreads[c]))
                        if buy <= 0:
                            continue
                        cash -= buy * (1 + FEE + spreads[c])
                        units[c] += buy / price[c]
            state = new
            last_month = (d.year, d.month)
        curve.append((d, cash + sum(units[c] * price[c] for c in coins)))
    years = (curve[-1][0] - curve[0][0]).days / 365.25
    peak, mdd = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    final = curve[-1][1]
    if final_sale:  # everything sold at the bid at the last close, as engine.run does
        final = cash + sum(units[c] * price[c] * (1 - spreads[c]) * (1 - FEE) for c in coins)
    return {"cagr": math.exp(math.log(final) / years) - 1, "max_drawdown": mdd}


def decompose(series: dict[str, engine.Series], spreads: dict[str, float]) -> list[dict]:
    """The README's two columns, step by step from its script to crypto.py's replay (before tax)."""
    end = date(2026, 10, 4)  # the README's last close
    periods = {"from 2018": (date(2018, 7, 1), {"BTC": 0.3125, "ETH": 0.3125, "XRP": 0.1875, "ADA": 0.1875}),
               "from 2020": (date(2020, 11, 1), {"BTC": 0.3125, "ETH": 0.3125, "XRP": 0.125, "ADA": 0.125,
                                                 "SOL": 0.125})}
    steps = [("README script (its table)", {}),
             ("+ decide at 00:00 on the 1st, on the month's last close", {"month_close": False}),
             ("+ purchases spend their money, costs included", {"month_close": False, "cost_inside": True}),
             ("+ a coin with too short a history is held", {"month_close": False, "cost_inside": True,
                                                            "held_short": True}),
             ("+ everything sold at the bid at the end", {"month_close": False, "cost_inside": True,
                                                          "held_short": True, "final_sale": True})]
    out = []
    for label, kw in steps:
        row = {"step": label}
        for name, (start, w) in periods.items():
            for key, n in (("hold", None), ("sma200", 200)):
                r = readme_run(series, w, spreads, start, end, n, **kw)
                row[f"{name} {key}"] = r["cagr"]
                row[f"{name} {key} mdd"] = r["max_drawdown"]
        out.append(row)
    row = {"step": "+ crypto.py's month (cash part, money left over, shortfall, no trade under 10): this test's "
                   "engine"}
    for name, (start, w) in periods.items():
        for key, rule in (("hold", engine.HOLD), ("sma200", engine.RULES[3])):
            r = engine.run(rule, series, w, spreads, start, end, tax=False)
            row[f"{name} {key}"] = r.cagr(after_tax=False)
            row[f"{name} {key} mdd"] = r.max_drawdown()
    out.append(row)
    return out
