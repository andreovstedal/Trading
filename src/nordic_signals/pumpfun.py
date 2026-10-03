"""The pump-and-dump screen for pump.fun launches, and the measurement of how well it works.

Nothing here trades. Each sampled launch is scored once, about 10 minutes after it was created, on
warning signs from rug-pull research (Solidus Labs' 2025 Rug Pull Report; SolRugDetector, 2026): a
creator launching token after token, a brand-new or robot-like creator wallet, supply concentrated in a
few wallets, a price that has already collapsed, and graduation within minutes (the whole bonding curve
bought at once).

Only tradable tokens are measured (``tradable``): traded in the 5 minutes before scoring, with real money
in them. On pump.fun's bonding curve the price only rises as SOL is paid in, so a token still at its launch
price has had no net buying; its few trades are usually bots buying and selling back, and its price cannot
fall, so it would neither collapse nor earn anything but would make the screen look better than it is.
Other tokens are "inactive" and count in neither direction. Tokens whose checks could not all be made (an
RPC failure) are incomplete and left out too, rather than passed unchecked.

A token counts as collapsed at a horizon (1, 6 or 24 hours after scoring) if its price then is at most
10 % of the highest price seen since scoring, and as quiet if nobody traded it since scoring. ``results`` answers, per horizon, the questions that decide
whether real money is ever justified: how often active launches collapse, how many collapses the screen
catches, how many survivors it lets through, what share of the tokens that pass still collapse, and what
buying at the scoring price would have returned after pump.fun's fees. The 1- and 6-hour figures come
early; the decision uses 24 hours. With about 98 % of launches ending as pump-and-dumps, a screen must
catch well over 99 % of them before the tokens that pass are mostly honest.

``paper`` turns the same data into a fake-money portfolio: 10 SOL, 0.1 SOL into every token that passes
(while the cash lasts), sold after 24 hours, fees on both trades, and a token whose price disappears
counted as lost. Open positions are valued at the latest price, including the live quotes. ``snapshot``
records the portfolio's value after every collector run, for the chart, and ``histories`` gives each
position's result over time. ``paper(store, cliff=True)`` is the same portfolio with the stup rule: a
position is sold as soon as a price at or below half its buy price is seen (``CLIFF``), at that price.

``patterns`` splits the measured tokens into quarters by each feature seen at scoring (market value,
trades, the creator wallet's activity, ...) and shows how often each quarter collapsed and what it
returned: where to look for the next rule. It does the same for the hype a token showed (``HYPE``): the
social links its creator added at launch, and paid promotion on DexScreener. ``log_rows`` is the downloadable log of everything measured.

Change SCREEN_VERSION whenever a rule or limit changes; results are shown for the current version only.
pf1 (2 October 2026) counted any token with a trade as tradable; the first export showed that most of the
tokens it passed were still at their launch price.
"""

from __future__ import annotations

import bisect
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from statistics import mean, median, quantiles
from typing import Any

from sqlalchemy import func, select

from .store import Store, utcnow

SCREEN_VERSION = "pf2"
COLLAPSE_LEVEL = 0.10  # collapsed: at most 10 % of the peak since scoring
# pump.fun's bonding curve at launch: 30 virtual SOL against 1,073,000,191 virtual tokens, a market value of
# about 27.96 SOL. Some launches use a cheaper curve; they stay below this and are never tradable here.
LAUNCH_PRICE = 30 / 1_073_000_191  # SOL per token
REAL_MONEY = 1.10  # tradable from 10 % above the launch price: about 1.5 SOL of net buying
FEE = 0.0125  # per trade on the bonding curve: 0.95 % to pump.fun and 0.30 % to the token's creator
# Price column, peak column (highest price from scoring until then), label.
HORIZONS = (("price_1h", "peak_1h", "1 time"), ("price_6h", "peak_6h", "6 timer"),
            ("price_24h", "peak_after", "24 timer"))

PAPER_START = 10.0  # SOL in the fake-money account
PAPER_STAKE = 0.1  # SOL into every token that passes
PAPER_HOLD = timedelta(hours=24)
CLIFF = 0.5  # the stup rule: sold at the first price seen at or below half the buy price
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


def tradable(f: dict[str, Any]) -> bool:
    """Traded in the 5 minutes before scoring, and priced clearly above launch: someone has put money in."""
    return bool(f.get("trades_5m")) and (f.get("price") or 0) >= REAL_MONEY * LAUNCH_PRICE


def quiet(start: float | None, end: float | None, peak: float | None) -> bool:
    """Nobody traded it from scoring until then: the price never rose and ended where it started.

    Any trade on the bonding curve moves the price, so an exact match means no trades."""
    return start is not None and end == start and peak == start


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
        r["quiet"] = quiet(r["price_t"], r["price_24h"], r["peak_after"])
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
    still = [r for r in rows if quiet(r["price_t"], r[price], r[peak])]
    held = [r for r in rows if r["mint"] not in ids and r not in still]  # survived, and was traded
    passed = [r for r in rows if r["passed"]]
    returns = {r["mint"]: net_return(r["price_t"], r[price]) for r in rows}
    return {
        "label": label, "measured": len(rows), "rows": rows, "collapsed_ids": ids,
        "collapse_rate": _share(collapsed, rows),
        "quiet_rate": _share(still, rows),
        "caught": _share([r for r in collapsed if not r["passed"]], collapsed),
        "kept": _share([r for r in held if r["passed"]], held),
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

def paper(store: Store, *, cliff: bool = False) -> dict[str, Any]:
    """Replay every token that passed, in order: buy 0.1 SOL while the cash lasts, sell after 24 hours.

    With ``cliff``, the stup rule: a position is sold as soon as a price at or below half its buy price is
    seen, at that price. Prices are seen a minute or more apart, so a token that falls straight through the
    line is sold lower, as it would be in real trading."""
    t = store.table("pf_tokens")
    rows = [dict(r) for r in store.query(
        select(t.c.mint, t.c.name, t.c.symbol, t.c.status, t.c.scored_at, t.c.price_t, t.c.price_1h, t.c.price_6h,
               t.c.price_24h, t.c.last_price, t.c.last_checked_at, t.c.cliff_at, t.c.cliff_price)
        .where(t.c.sampled.is_(True), t.c.screen_version == SCREEN_VERSION, t.c.passed.is_(True)))]
    events = []
    for r in rows:
        opened, dropped = _aware(r["scored_at"]), _aware(r["cliff_at"])
        events.append((opened, 1, "buy", r))
        if cliff and dropped is not None and opened < dropped <= opened + PAPER_HOLD:
            events.append((dropped, 0, "cliff", r))
        elif r["status"] == "done":
            events.append((opened + PAPER_HOLD, 0, "held", r))
        elif r["status"] == "missing":
            events.append((_aware(r["last_checked_at"]) or opened, 0, "lost", r))
    events.sort(key=lambda e: (e[0], e[1]))  # sales before purchases at the same moment, to free the cash

    cash, holding, closed, skipped = PAPER_START, {}, [], 0
    for at, _, kind, r in events:
        if kind == "buy":
            if cash < PAPER_STAKE - 1e-9:
                skipped += 1
                continue
            cash -= PAPER_STAKE
            holding[r["mint"]] = {**r, "opened_at": at, "qty": PAPER_STAKE * (1 - FEE) / r["price_t"]}
        elif (position := holding.pop(r["mint"], None)) is not None:
            exit_price = {"cliff": r["cliff_price"], "lost": 0.0}.get(kind, r["price_24h"])
            proceeds = position["qty"] * exit_price * (1 - FEE)
            cash += proceeds
            closed.append({**position, "closed_at": at, "exit_price": exit_price, "proceeds": proceeds,
                           "result": proceeds / PAPER_STAKE - 1, "lost": kind == "lost", "cliff": kind == "cliff"})

    latest = latest_prices(store, list(holding))
    open_positions = []
    for position in holding.values():
        price_at, price = latest.get(position["mint"], (_aware(position["last_checked_at"]), position["last_price"]))
        value = position["qty"] * (price or 0) * (1 - FEE)  # what a sale would bring now
        open_positions.append({**position, "price": price, "price_at": price_at, "value": value,
                               "result": value / PAPER_STAKE - 1})
    positions_value = sum(p["value"] for p in open_positions)
    equity = cash + positions_value
    cliffs = [(c["closed_at"] - c["opened_at"]).total_seconds() / 60 for c in closed if c["cliff"]]
    return {
        "start": PAPER_START, "stake": PAPER_STAKE, "hold_hours": PAPER_HOLD.total_seconds() / 3600,
        "cliff_level": CLIFF if cliff else None,
        "cliff_sales": len(cliffs), "cliff_minutes": median(cliffs) if cliffs else None,
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
            open_positions=len(p["open"]), screen_version=SCREEN_VERSION,
        ).on_conflict_do_nothing(index_elements=["at"]))


def equity_history(store: Store, *, since: datetime | None = None,
                   points: int = 400) -> list[tuple[datetime, float]]:
    """The current screen's recorded values (from ``since``), thinned to at most ``points`` for the chart,
    keeping the latest. Each screen version has its own portfolio, starting from scratch."""
    e = store.table("pf_equity")
    stmt = select(e.c.at, e.c.equity).where(e.c.screen_version == SCREEN_VERSION).order_by(e.c.at)
    rows = store.query(stmt if since is None else stmt.where(e.c.at >= since))
    if len(rows) > points:
        step = math.ceil(len(rows) / points)
        rows = [*rows[::step], rows[-1]] if (len(rows) - 1) % step else rows[::step]
    return [(_aware(r["at"]), r["equity"]) for r in rows]


def latest_prices(store: Store, mints: list[str]) -> dict[str, tuple[datetime, float]]:
    """Each token's newest recorded price and when it was seen."""
    if not mints:
        return {}
    p = store.table("pf_prices")
    newest = (select(p.c.mint, func.max(p.c.at).label("at")).where(p.c.mint.in_(mints))
              .group_by(p.c.mint).subquery())
    rows = store.query(select(p.c.mint, p.c.at, p.c.price)
                       .join(newest, (p.c.mint == newest.c.mint) & (p.c.at == newest.c.at)))
    return {r["mint"]: (_aware(r["at"]), r["price"]) for r in rows}


def histories(store: Store, positions: list[dict[str, Any]], now: datetime, *,
              slices: int = 40) -> dict[str, list[tuple[datetime, float]]]:
    """Each position's result after fees from its purchase until it was sold (or now), for a small chart.

    From the recorded prices, or for a position bought before they were recorded, its 1- and 6-hour
    prices. A position still open is drawn at its latest price until now.
    """
    observed: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    if positions:
        p = store.table("pf_prices")
        for r in store.query(select(p.c.mint, p.c.at, p.c.price)
                             .where(p.c.mint.in_([pos["mint"] for pos in positions])).order_by(p.c.at)):
            observed[r["mint"]].append((_aware(r["at"]), r["price"]))
    out = {}
    for pos in positions:
        start, closed = pos["opened_at"], "closed_at" in pos
        end = pos["closed_at"] if closed else now
        prices = [(t, v) for t, v in observed.get(pos["mint"], []) if start < t <= end] or _checkpoints(pos, end)
        series = [(start, pos["price_t"]), *prices]
        if closed:
            series.append((end, pos["exit_price"]))  # sold at the 24-hour price, or nothing if it disappeared
        elif series[-1][0] < now:
            series.append((now, series[-1][1]))
        out[pos["mint"]] = _thin([(t, net_return(pos["price_t"], v)) for t, v in series], slices)
    return out


def _checkpoints(pos: dict[str, Any], end: datetime) -> list[tuple[datetime, float]]:
    start = pos["opened_at"]
    points = [(start + after, pos[column]) for column, after in (("price_1h", timedelta(hours=1)),
                                                                 ("price_6h", timedelta(hours=6)))
              if pos.get(column) is not None]
    if pos.get("price") is not None and pos.get("price_at") is not None:
        points.append((pos["price_at"], pos["price"]))
    return sorted(point for point in points if start < point[0] <= end)


def _thin(series: list[tuple[datetime, float]], slices: int) -> list[tuple[datetime, float]]:
    """About two points per time slice, the lowest and the highest, so short spikes stay visible."""
    if len(series) <= 2 * slices + 2 or series[-1][0] <= series[0][0]:
        return series
    first, last = series[0], series[-1]
    width = (last[0] - first[0]) / slices
    groups: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    for point in series[1:-1]:
        groups[min(int((point[0] - first[0]) / width), slices - 1)].append(point)
    out = [first]
    for key in sorted(groups):
        group = groups[key]
        out.extend(sorted({min(group, key=lambda q: q[1]), max(group, key=lambda q: q[1])}))
    return [*out, last]


def freshness(store: Store) -> tuple[str, datetime | None]:
    """A stamp that changes whenever the page's data does (a pump.fun run starts or ends, a quote arrives),
    and when the data last changed."""
    runs, p = store.table("runs"), store.table("pf_prices")
    last = store.query(select(runs.c.id, runs.c.started_at, runs.c.finished_at)
                       .where(runs.c.source == "pumpfun").order_by(runs.c.id.desc()).limit(1))
    quoted = _aware(store.scalar(select(func.max(p.c.at))))
    run = last[0] if last else {"id": 0, "started_at": None, "finished_at": None}
    finished = _aware(run["finished_at"])
    stamp = f"{run['id']}.{_ms(finished)}.{_ms(quoted)}"
    return stamp, max((t for t in (finished, quoted) if t), default=None)


def _ms(value: datetime | None) -> str:
    return str(round(value.timestamp() * 1000)) if value else "0"


# Patterns: how the outcome varies with each feature seen at scoring

PATTERN_MIN = 40  # measured tokens with the feature before it is split into quarters
PATTERN_MIN_GROUP = 10  # tokens in a quarter before its figures are shown
PATTERN_HORIZON_MIN = 100  # the longest horizon with this many measured tokens; else the one with the most


def _fraction(part: float | None, other: float | None) -> float | None:
    return part / (part + other) if part is not None and other is not None and part + other > 0 else None


def _ratio(value: float | None, of: float | None) -> float | None:
    return value / of if value and of else None


# Key, label, how the cut points are written ("number", "decimal" or "percent"), value from the features.
PATTERNS: tuple[tuple[str, str, str, Callable[[dict[str, Any]], float | None]], ...] = (
    ("market_cap_usd", "Markedsverdi (USD)", "number", lambda f: f.get("market_cap_usd")),
    ("trades_5m", "Handler de siste 5 minuttene", "number", lambda f: f.get("trades_5m")),
    ("buy_share_1h", "Andel kjøp av handlene den siste timen", "percent",
     lambda f: _fraction(f.get("buys_1h"), f.get("sells_1h"))),
    ("volume_1h_usd", "Volum den siste timen (USD)", "number", lambda f: f.get("volume_1h_usd")),
    ("from_peak", "Kurs i forhold til toppen før vurderingen", "percent",
     lambda f: _ratio(f.get("price"), f.get("peak_before"))),
    ("creator_tx", "Utstederens transaksjoner (av de siste 200)", "number", lambda f: f.get("creator_tx")),
    ("creator_age_h", "Utstederens lommebok: alder i timer", "decimal",
     lambda f: f.get("creator_age_h") if f.get("creator_history_complete") else None),
    ("creator_tx_per_h", "Utstederens transaksjoner per time", "decimal", lambda f: f.get("creator_tx_per_h")),
    ("top10_share", "De ti største eiernes andel", "percent", lambda f: f.get("top10_share")),
)


def _links(launch: dict[str, Any] | None) -> int:
    """Social links the creator added at launch: X, Telegram, a website."""
    return sum(bool((launch or {}).get(k)) for k in ("twitter", "telegram", "website"))


# Hype at scoring: key, label, and the groups (label, test on the features). Tokens scored before a feature
# was recorded have none, and count in no group.
HYPE: tuple[tuple[str, str, tuple[tuple[str, Callable[[dict[str, Any]], bool]], ...]], ...] = (
    ("links", "Lenker ved lanseringen (X, Telegram, nettside)",
     (("Ingen", lambda f: f.get("links") == 0), ("1", lambda f: f.get("links") == 1),
      ("2–3", lambda f: (f.get("links") or 0) >= 2))),
    ("dex_profile", "Betalt profil hos DexScreener",
     (("Nei", lambda f: f.get("dex_profile") is False), ("Ja", lambda f: f.get("dex_profile") is True))),
    ("boosts", "Betalt boost hos DexScreener",
     (("Nei", lambda f: f.get("boosts") == 0), ("Ja", lambda f: (f.get("boosts") or 0) > 0))),
)


def patterns(store: Store) -> dict[str, Any]:
    """Each feature's quarters, for all active tokens and for those that passed, at the longest horizon with
    enough measurements (early on, the one with the most). Sorted by how far apart the quarters' collapse
    rates are."""
    t = store.table("pf_tokens")
    names = ("mint", "features", "launch", "passed", "price_t", *{c for horizon in HORIZONS for c in horizon[:2]})
    rows = [dict(r) for r in store.query(select(*[t.c[n] for n in names]).where(
        t.c.sampled.is_(True), t.c.screen_version == SCREEN_VERSION, t.c.active.is_(True),
        t.c.complete.is_(True), t.c.scored_at.is_not(None)))]
    by_horizon = [([r for r in rows if r[price] is not None and r[peak] and r["price_t"]], price, peak, label)
                  for price, peak, label in HORIZONS]
    if not any(h[0] for h in by_horizon):
        return {"label": None, "populations": {}}
    enough = [h for h in by_horizon if len(h[0]) >= PATTERN_HORIZON_MIN]
    # On a tie, max keeps the first it meets: the longest horizon.
    measured, price, peak, label = enough[-1] if enough else max(reversed(by_horizon), key=lambda h: len(h[0]))
    outcomes = [{"features": {**(r["features"] or {}), "links": _links(r["launch"])}, "passed": r["passed"],
                 "collapsed": r[price] <= COLLAPSE_LEVEL * r[peak], "return": net_return(r["price_t"], r[price])}
                for r in measured]
    populations = {"all": outcomes, "passed": [o for o in outcomes if o["passed"]]}
    return {"label": label, "populations": {key: {
        **_outcome(group),
        "features": sorted((_pattern(spec, group) for spec in PATTERNS),
                           key=lambda f: (f["spread"] is None, -(f["spread"] or 0))),
        "hype": [{"key": key_, "label": label_, "groups": [
            {"label": name, **_quarter([o for o in group if test(o["features"])])} for name, test in tests]}
            for key_, label_, tests in HYPE],
    } for key, group in populations.items()}}


def _quarter(group: list[dict[str, Any]]) -> dict[str, Any]:
    """A group's outcome, or only its size when it is too small to say anything."""
    return _outcome(group) if len(group) >= PATTERN_MIN_GROUP else {"n": len(group), "collapse_rate": None,
                                                                    "median_return": None}


def _outcome(group: list[dict[str, Any]]) -> dict[str, Any]:
    return {"n": len(group),
            "collapse_rate": _share([o for o in group if o["collapsed"]], group),
            "median_return": median(o["return"] for o in group) if group else None}


def _pattern(spec: tuple[str, str, str, Callable], group: list[dict[str, Any]]) -> dict[str, Any]:
    key, label, unit, value_of = spec
    values = [(v, o) for o in group if (v := value_of(o["features"])) is not None]
    out: dict[str, Any] = {"key": key, "label": label, "unit": unit, "n": len(values), "cuts": [], "quarters": [],
                           "spread": None}
    if len(values) < PATTERN_MIN:
        return out
    cuts = quantiles([v for v, _ in values], n=4)
    quarters: list[list[dict[str, Any]]] = [[], [], [], []]
    for v, o in values:
        quarters[bisect.bisect_right(cuts, v)].append(o)
    stats = [_quarter(q) for q in quarters]
    rates = [s["collapse_rate"] for s in stats if s["collapse_rate"] is not None]
    out.update(cuts=cuts, quarters=stats, spread=max(rates) - min(rates) if len(rates) >= 2 else None)
    return out


# The downloadable log

def log_rows(store: Store) -> Iterator[dict[str, Any]]:
    """Every sampled token, oldest first: what was stored, its outcome at each horizon, and what the fake-money
    portfolio did with it."""
    portfolio, stup = paper(store), paper(store, cliff=True)
    trades = {p["mint"]: p for p in (*portfolio["open"], *portfolio["closed"])}
    stup_trades = {p["mint"]: p for p in (*stup["open"], *stup["closed"])}
    t = store.table("pf_tokens")
    stmt = select(t).where(t.c.sampled.is_(True)).order_by(t.c.created_at, t.c.mint)
    with store.engine.connect() as conn:
        for row in conn.execution_options(yield_per=500).execute(stmt).mappings():
            r = dict(row)
            for price, peak, _ in HORIZONS:
                h = price.removeprefix("price_")
                r[f"return_{h}"] = net_return(r["price_t"], r[price])
                r[f"collapsed_{h}"] = (r[price] <= COLLAPSE_LEVEL * r[peak]
                                       if r[price] is not None and r[peak] else None)
                r[f"quiet_{h}"] = quiet(r["price_t"], r[price], r[peak]) if r[price] is not None else None
            trade = trades.get(r["mint"])
            current = r["passed"] and r["screen_version"] == SCREEN_VERSION
            r["paper"] = ("open" if "closed_at" not in trade else "sold") if trade else ("skipped" if current else None)
            r["paper_result"] = trade["result"] if trade else None
            trade = stup_trades.get(r["mint"])
            r["paper_stup"] = ("open" if "closed_at" not in trade else "sold") if trade else ("skipped" if current else None)
            r["paper_stup_result"] = trade["result"] if trade else None
            yield r


def _bins(results: list[float]) -> list[dict[str, Any]]:
    counts = [0] * len(RESULT_BINS)
    for value in results:
        counts[next(i for i, (upper, _, _) in enumerate(RESULT_BINS) if value <= upper)] += 1
    return [{"label": label, "polarity": polarity, "count": count}
            for (_, label, polarity), count in zip(RESULT_BINS, counts, strict=True)]


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
