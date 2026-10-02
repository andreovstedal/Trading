"""The pump-and-dump screen for pump.fun launches, and the measurement of how well it works.

Nothing here trades. Each sampled launch is scored once, about 10 minutes after it was created, on
warning signs from rug-pull research (Solidus Labs' 2025 Rug Pull Report; SolRugDetector, 2026): a
creator launching token after token, a brand-new or robot-like creator wallet, supply concentrated in a
few wallets, a price that has already collapsed, and graduation within minutes (the whole bonding curve
bought at once). Tokens with no trades in the 5 minutes before scoring are "inactive": there is nothing
to buy, so they count in neither direction. Tokens whose checks could not all be made (an RPC failure) are
incomplete and left out too, rather than passed unchecked.

24 hours after scoring, a token is labelled collapsed if its price is at most 10 % of the highest price
seen since scoring. ``results`` then answers the questions that decide whether real money is ever
justified: how often active launches collapse, how many collapses the screen catches, how many survivors
it lets through, what share of the tokens that pass still collapse, and what buying at the scoring price
would have returned after pump.fun's fees. With about 98 % of launches ending as pump-and-dumps, a screen
must catch well over 99 % of them before the tokens that pass are mostly honest.

Change SCREEN_VERSION whenever a rule or limit changes; results are shown for the current version only.
"""

from __future__ import annotations

from collections import Counter
from statistics import mean, median
from typing import Any

from sqlalchemy import select

from .store import Store

SCREEN_VERSION = "pf1"
COLLAPSE_LEVEL = 0.10  # collapsed: at most 10 % of the peak since scoring
FEE = 0.0125  # per trade on the bonding curve: 0.95 % to pump.fun and 0.30 % to the token's creator
HORIZONS = (("price_1h", "1 time"), ("price_6h", "6 timer"), ("price_24h", "24 timer"))

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
    """Everything the measurement page shows, for the current screen version."""
    t = store.table("pf_tokens")
    status = Counter(r["status"] for r in store.query(select(t.c.status)))
    columns = [t.c[name] for name in ("mint", "name", "symbol", "scored_at", "warnings", "active", "complete",
                                       "passed", "collapsed", "price_t", *(column for column, _ in HORIZONS))]
    rows = [dict(r) for r in store.query(
        select(*columns).where(t.c.sampled.is_(True), t.c.status == "done", t.c.screen_version == SCREEN_VERSION))]
    measured = [r for r in rows if r["active"] and r["complete"]]
    collapsed = [r for r in measured if r["collapsed"]]
    survived = [r for r in measured if not r["collapsed"]]
    passed = [r for r in measured if r["passed"]]
    for r in rows:
        r["returns"] = [net_return(r["price_t"], r[column]) for column, _ in HORIZONS]
        r["warning_labels"] = [WARNINGS.get(key, key) for key in r["warnings"] or []]
    return {
        "screen_version": SCREEN_VERSION,
        "status": dict(status),
        "seen": sum(status.values()),
        "inactive": sum(1 for r in rows if not r["active"]),
        "incomplete": sum(1 for r in rows if r["active"] and not r["complete"]),
        "measured": len(measured),
        "collapse_rate": _share(collapsed, measured),
        "caught": _share([r for r in collapsed if not r["passed"]], collapsed),
        "kept": _share([r for r in survived if r["passed"]], survived),
        "passed": len(passed),
        "passed_collapse_rate": _share([r for r in passed if r["collapsed"]], passed),
        "returns": [
            {"group": group, "n": len(members), "horizons": [_summary(members, i) for i in range(len(HORIZONS))]}
            for group, members in (("Bestod filteret", passed), ("Alle aktive", measured))
        ],
        "warnings": [_warning(key, label, measured) for key, label in WARNINGS.items()],
        "recent": sorted(rows, key=lambda r: r["scored_at"], reverse=True)[:50],
    }


def _share(part: list, whole: list) -> float | None:
    return len(part) / len(whole) if whole else None


def _summary(rows: list[dict[str, Any]], horizon: int) -> dict[str, Any]:
    values = [r["returns"][horizon] for r in rows if r["returns"][horizon] is not None]
    if not values:
        return {"n": 0, "median": None, "mean": None, "positive": None}
    return {"n": len(values), "median": median(values), "mean": mean(values),
            "positive": sum(v > 0 for v in values) / len(values)}


def _warning(key: str, label: str, measured: list[dict[str, Any]]) -> dict[str, Any]:
    flagged = [r for r in measured if key in (r["warnings"] or [])]
    clear = [r for r in measured if key not in (r["warnings"] or [])]
    return {"key": key, "label": label, "n": len(flagged),
            "collapse_with": _share([r for r in flagged if r["collapsed"]], flagged),
            "collapse_without": _share([r for r in clear if r["collapsed"]], clear)}
