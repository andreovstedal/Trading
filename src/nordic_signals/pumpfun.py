"""The pump-and-dump screen for pump.fun launches, and the measurement of how well it works.

Nothing here trades. Each sampled launch is scored once, about 10 minutes after it was created, on
warning signs from rug-pull research (Solidus Labs' 2025 Rug Pull Report; SolRugDetector, 2026): a
creator launching token after token, a brand-new or robot-like creator wallet, supply concentrated in a
few wallets, a price that has already collapsed, and graduation within minutes (the whole bonding curve
bought at once). Tokens with no trades in the 5 minutes before scoring are "inactive": there is nothing
to buy, so they count in neither direction. Tokens whose checks could not all be made (an RPC failure) are
incomplete and left out too, rather than passed unchecked.

A token counts as collapsed at a horizon (1, 6 or 24 hours after scoring) if its price then is at most
10 % of the highest price seen since scoring. ``results`` answers, per horizon, the questions that decide
whether real money is ever justified: how often active launches collapse, how many collapses the screen
catches, how many survivors it lets through, what share of the tokens that pass still collapse, and what
buying at the scoring price would have returned after pump.fun's fees. The 1- and 6-hour figures come
early; the decision uses 24 hours. With about 98 % of launches ending as pump-and-dumps, a screen must
catch well over 99 % of them before the tokens that pass are mostly honest.

``paper`` turns the same data into a fake-money portfolio: 10 SOL, 0.1 SOL into every token that passes
(while the cash lasts), sold after 24 hours, fees on both trades, and a token whose price disappears
counted as lost. ``snapshot`` records its value after every collector run, for the chart.

Change SCREEN_VERSION whenever a rule or limit changes; results are shown for the current version only.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any

from sqlalchemy import select

from .store import Store, utcnow

SCREEN_VERSION = "pf1"
COLLAPSE_LEVEL = 0.10  # collapsed: at most 10 % of the peak since scoring
FEE = 0.0125  # per trade on the bonding curve: 0.95 % to pump.fun and 0.30 % to the token's creator
# Price column, peak column (highest price from scoring until then), label.
HORIZONS = (("price_1h", "peak_1h", "1 time"), ("price_6h", "peak_6h", "6 timer"),
            ("price_24h", "peak_after", "24 timer"))

PAPER_START = 10.0  # SOL in the fake-money account
PAPER_STAKE = 0.1  # SOL into every token that passes
PAPER_HOLD = timedelta(hours=24)
# Result bins for closed trades: (upper limit, label, polarity) with the last one open-ended.
RESULT_BINS = ((-0.9, "≤ −90", -1), (-0.5, "−90…−50", -1), (-0.1, "−50…−10", -1), (0.1, "±10", 0),
               (0.5, "+10…+50", 1), (1.0, "+50…+100", 1), (math.inf, "> +100", 1))

LIMITS = {
    "serial_tokens": 1,  # other launches by the same creator seen from 24 hours before until scoring
    "fresh_wallet_hours": 24.0,  # creator wallet's first transaction this soon before the launch
    "busy_wallet_tx": 100,  # a robot-like wallet: at least this many transactions ...
    "busy_wallet_tx_per_hour": 20.0,  # ... at this rate
    "top10_share": 0.30,  # largest ten holders, not counting the bonding curve itself
    "dumped": 0.5,  # price at most half of the peak before scoring
}

# Warning sign -> how the page names it.
WARNINGS = {
    "serial": "Utstederen har lansert andre tokens det siste døgnet",
    "fresh_wallet": "Utstederens lommebok er under ett døgn gammel",
    "busy_wallet": "Utstederens lommebok oppfører seg som en robot",
    "concentrated": "De ti største eierne har over 30 % av tokenene",
    "dumped": "Kursen har allerede falt under halvparten av toppen",
    "instant_graduation": "Hele kjøpskurven ble kjøpt opp i løpet av minutter",
}


def warning_signs(f: dict[str, Any]) -> list[str]:
    """The warning signs in a token's features when scored, as keys of WARNINGS."""
    signs = []
    if (f.get("serial") or 0) >= LIMITS["serial_tokens"]:
        signs.append("serial")
    age = f.get("creator_age_h")
    if f.get("creator_history_complete") and age is not None and age < LIMITS["fresh_wallet_hours"]:
        signs.append("fresh_wallet")  # the whole history was read, so the oldest transaction is the wallet's first
    tx, rate = f.get("creator_tx") or 0, f.get("creator_tx_per_h") or 0
    if tx >= LIMITS["busy_wallet_tx"] and rate > LIMITS["busy_wallet_tx_per_hour"]:
        signs.append("busy_wallet")
    if f.get("top10_share") is not None and f["top10_share"] > LIMITS["top10_share"]:
        signs.append("concentrated")
    if f.get("price") and f.get("peak_before") and f["price"] <= LIMITS["dumped"] * f["peak_before"]:
        signs.append("dumped")
    if f.get("graduated"):
        signs.append("instant_graduation")  # scored about 10 minutes after launch, so it graduated within minutes
    return signs


def net_return(start: float | None, end: float | None) -> float | None:
    """Buying at ``start`` and selling at ``end``, after pump.fun's fee on both trades (slippage not included)."""
    if not start or end is None:
        return None
    return end / start * (1 - FEE) ** 2 - 1


def results(store: Store) -> dict[str, Any]:
    """Everything the measurement part of the page shows, for the current screen version."""
    t = store.table("pf_tokens")
    status = Counter(r["status"] for r in store.query(select(t.c.status)))
    names = ("mint", "name", "symbol", "status", "scored_at", "warnings", "active", "complete", "passed",
             "collapsed", "price_t", *{c for horizon in HORIZONS for c in horizon[:2]})
    rows = [dict(r) for r in store.query(select(*[t.c[n] for n in names]).where(
        t.c.sampled.is_(True), t.c.screen_version == SCREEN_VERSION, t.c.scored_at.is_not(None)))]
    measured = [r for r in rows if r["active"] and r["complete"]]
    horizons = [_horizon(measured, price, peak, label) for price, peak, label in HORIZONS]
    longest = next((h for h in reversed(horizons) if h["measured"]), None)
    done = sorted((r for r in rows if r["status"] == "done"), key=lambda r: r["scored_at"], reverse=True)[:50]
    for r in done:
        r["returns"] = [net_return(r["price_t"], r[price]) for price, _, _ in HORIZONS]
        r["warning_labels"] = [WARNINGS.get(key, key) for key in r["warnings"] or []]
    return {
        "screen_version": SCREEN_VERSION,
        "status": dict(status),
        "seen": sum(status.values()),
        "scored": len(rows),
        "inactive": sum(1 for r in rows if not r["active"]),
        "incomplete": sum(1 for r in rows if r["active"] and not r["complete"]),
        "horizons": [{k: v for k, v in h.items() if k not in ("rows", "collapsed_ids")} for h in horizons],
        "measured": any(h["measured"] for h in horizons),
        "warnings_horizon": longest["label"] if longest else None,
        "warnings": [_warning(key, label, longest["rows"], longest["collapsed_ids"])
                     for key, label in WARNINGS.items()] if longest else [],
        "recent": done,
    }


def _horizon(measured: list[dict[str, Any]], price: str, peak: str, label: str) -> dict[str, Any]:
    rows = [r for r in measured if r[price] is not None and r[peak] and r["price_t"]]
    collapsed = [r for r in rows if r[price] <= COLLAPSE_LEVEL * r[peak]]
    ids = {r["mint"] for r in collapsed}
    survived = [r for r in rows if r["mint"] not in ids]
    passed = [r for r in rows if r["passed"]]
    returns = {r["mint"]: net_return(r["price_t"], r[price]) for r in rows}
    return {
        "label": label, "measured": len(rows), "rows": rows, "collapsed_ids": ids,
        "collapse_rate": _share(collapsed, rows),
        "caught": _share([r for r in collapsed if not r["passed"]], collapsed),
        "kept": _share([r for r in survived if r["passed"]], survived),
        "passed": len(passed),
        "passed_collapse_rate": _share([r for r in passed if r["mint"] in ids], passed),
        "passed_returns": _summary([returns[r["mint"]] for r in passed]),
        "all_returns": _summary(list(returns.values())),
    }


def _share(part: list, whole: list) -> float | None:
    return len(part) / len(whole) if whole else None


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "mean": None, "positive": None}
    return {"n": len(values), "median": median(values), "mean": mean(values),
            "positive": sum(v > 0 for v in values) / len(values)}


def _warning(key: str, label: str, rows: list[dict[str, Any]], collapsed: set[str]) -> dict[str, Any]:
    flagged = [r for r in rows if key in (r["warnings"] or [])]
    clear = [r for r in rows if key not in (r["warnings"] or [])]
    return {"key": key, "label": label, "n": len(flagged),
            "collapse_with": _share([r for r in flagged if r["mint"] in collapsed], flagged),
            "collapse_without": _share([r for r in clear if r["mint"] in collapsed], clear)}


# The fake-money portfolio

def paper(store: Store) -> dict[str, Any]:
    """Replay every token that passed, in order: buy 0.1 SOL while the cash lasts, sell after 24 hours."""
    t = store.table("pf_tokens")
    rows = [dict(r) for r in store.query(
        select(t.c.mint, t.c.name, t.c.symbol, t.c.status, t.c.scored_at, t.c.price_t, t.c.price_24h,
               t.c.last_price, t.c.last_checked_at)
        .where(t.c.sampled.is_(True), t.c.screen_version == SCREEN_VERSION, t.c.passed.is_(True)))]
    events = []
    for r in rows:
        opened = _aware(r["scored_at"])
        events.append((opened, 1, r))
        if r["status"] == "done":
            events.append((opened + PAPER_HOLD, 0, r))
        elif r["status"] == "missing":
            events.append((_aware(r["last_checked_at"]) or opened, 0, r))
    events.sort(key=lambda e: (e[0], e[1]))  # sales before purchases at the same moment, to free the cash

    cash, holding, closed, skipped = PAPER_START, {}, [], 0
    for at, opening, r in events:
        if opening:
            if cash < PAPER_STAKE - 1e-9:
                skipped += 1
                continue
            cash -= PAPER_STAKE
            holding[r["mint"]] = {**r, "opened_at": at, "qty": PAPER_STAKE * (1 - FEE) / r["price_t"]}
        elif (position := holding.pop(r["mint"], None)) is not None:
            lost = r["status"] == "missing"
            exit_price = 0.0 if lost else r["price_24h"]
            proceeds = position["qty"] * exit_price * (1 - FEE)
            cash += proceeds
            closed.append({**position, "closed_at": at, "exit_price": exit_price, "proceeds": proceeds,
                           "result": proceeds / PAPER_STAKE - 1, "lost": lost})

    open_positions = []
    for position in holding.values():
        value = position["qty"] * (position["last_price"] or 0) * (1 - FEE)  # what a sale would bring now
        open_positions.append({**position, "value": value, "result": value / PAPER_STAKE - 1})
    positions_value = sum(p["value"] for p in open_positions)
    equity = cash + positions_value
    return {
        "start": PAPER_START, "stake": PAPER_STAKE, "hold_hours": PAPER_HOLD.total_seconds() / 3600,
        "started_at": events[0][0] if events else None,
        "cash": cash, "positions_value": positions_value, "equity": equity, "result": equity / PAPER_START - 1,
        "open": sorted(open_positions, key=lambda p: p["opened_at"], reverse=True),
        "closed": sorted(closed, key=lambda c: c["closed_at"], reverse=True),
        "trades": len(closed),
        "win_rate": sum(c["proceeds"] > PAPER_STAKE for c in closed) / len(closed) if closed else None,
        "skipped": skipped,
        "bins": _bins([c["result"] for c in closed]),
    }


def snapshot(store: Store, now: datetime | None = None) -> None:
    """Record the portfolio's value, once trading has started."""
    p = paper(store)
    if p["started_at"] is None:
        return
    e = store.table("pf_equity")
    with store.engine.begin() as conn:
        conn.execute(store._insert(e).values(
            at=now or utcnow(), cash=p["cash"], positions=p["positions_value"], equity=p["equity"],
            open_positions=len(p["open"])).on_conflict_do_nothing(index_elements=["at"]))


def equity_history(store: Store, *, points: int = 400) -> list[tuple[datetime, float]]:
    """The recorded values, thinned to at most ``points`` for the chart (always keeping the latest)."""
    e = store.table("pf_equity")
    rows = store.query(select(e.c.at, e.c.equity).order_by(e.c.at))
    if len(rows) > points:
        step = math.ceil(len(rows) / points)
        rows = [*rows[::step], rows[-1]] if (len(rows) - 1) % step else rows[::step]
    return [(_aware(r["at"]), r["equity"]) for r in rows]


def _bins(results: list[float]) -> list[dict[str, Any]]:
    counts = [0] * len(RESULT_BINS)
    for value in results:
        counts[next(i for i, (upper, _, _) in enumerate(RESULT_BINS) if value <= upper)] += 1
    return [{"label": label, "polarity": polarity, "count": count}
            for (_, label, polarity), count in zip(RESULT_BINS, counts, strict=True)]


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
