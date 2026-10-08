"""The long-term score and the eligibility rules.

The score follows the research report's recommendations: an equal-weighted
average of four themes with Nordic evidence behind them (12-1 momentum,
value, quality, low volatility), each a percentile rank within the stock's
own country, plus small capped overlays for insider trading, buybacks and
disclosed short interest. Change MODEL_VERSION whenever any rule or weight
here changes, so the track record keeps versions apart.

v2 keeps windfalls out of the long-term sleeve. A P/E below 4 usually comes
from a one-off gain, changes in the value of holdings (investment companies)
or a short-lived peak, and it inflates value and quality at once. A rise of
more than 300 % in a year is an event (a takeover bid, a turnaround, a
temporary boom), not the persistent trend the momentum evidence is about.
Hunter Group in October 2026 was both: two tanker charters earning extreme
spot rates, ending within months.

v3 counts a buyback as new only when the notice announces a programme
(features.buyback_start). v2 also counted the weekly reports of programmes
already running, which are most buyback notices, so a bank buying back shares
every week looked like a fresh announcement every week.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .. import text
from .features import Stock

MODEL_VERSION = "v3"

THEMES = ("value", "quality", "momentum", "low_vol")

# Overlay sizes, on the same 0-1 scale as the themes. Capped so that events
# tilt the ranking but cannot outweigh the factor themes.
OVERLAY_CAP = (-0.15, 0.08)
PARAMS: dict[str, Any] = {
    "model_version": MODEL_VERSION,
    "themes": THEMES,
    "overlay_cap": OVERLAY_CAP,
    "insider_buy": 0.03,
    "insider_cluster_buy": 0.05,
    "insider_cluster_sell": -0.05,
    "buyback_active": 0.02,
    "buyback_new": 0.03,
    "short_2pct": -0.05,
    "short_5pct": -0.10,
    "short_increase": -0.05,
    "adv_multiple": 50,
    "min_price_nok": 5.0,  # below this one tick is a large share of the price
    "min_market_cap_nok": 500e6,
    "min_pe": 4.0,  # v2: lower usually means one-off or temporary earnings
    "max_ret_1y": 3.0,  # v2: a rise of more than 300 % in 12 months is an event, not momentum
    "low_vol_min_coverage": 0.5,
}


@dataclass
class Scored:
    stock: Stock
    eligible: bool = False
    exclusion: str | None = None
    themes: dict[str, float | None] = field(default_factory=dict)
    overlays: dict[str, float] = field(default_factory=dict)
    score: float | None = None
    rank: int | None = None
    reasons: list[str] = field(default_factory=list)
    fx: float | None = None  # NOK per unit of the stock's currency

    @property
    def adv_nok(self) -> float | None:
        adv = self.stock.features.get("adv")
        return adv * self.fx if adv is not None and self.fx is not None else None


def score_stocks(stocks: list[Stock], fx: dict[str, float], *, target_position: float,
                 ask_only: bool = False) -> list[Scored]:
    scored = [Scored(stock=s, fx=fx.get(s.currency or "")) for s in stocks]
    for item in scored:
        item.exclusion = _exclusion(item, target_position=target_position, ask_only=ask_only)
        item.eligible = item.exclusion is None
    _one_share_class_per_issuer(scored)

    for country in sorted({s.stock.country for s in scored}):
        group = [s for s in scored if s.eligible and s.stock.country == country]
        _themes(group)

    for item in (s for s in scored if s.eligible):
        available = [v for v in item.themes.values() if v is not None]
        item.overlays = _overlays(item.stock)
        total = sum(item.overlays.values())
        item.score = mean(available) + min(max(total, OVERLAY_CAP[0]), OVERLAY_CAP[1])
        item.reasons = _reasons(item)

    ranked = sorted((s for s in scored if s.eligible), key=lambda s: s.score, reverse=True)
    for rank, item in enumerate(ranked, 1):
        item.rank = rank
    return scored


def _exclusion(item: Scored, *, target_position: float, ask_only: bool) -> str | None:
    s, f = item.stock, item.stock.features
    if not s.price or s.price <= 0:
        return "Mangler kurs"
    if item.fx is None:
        return f"Mangler valutakurs {s.currency}/NOK"
    if ask_only and not s.is_regulated_market:
        return "Ikke notert på regulert marked (ikke tillatt på ASK)"
    if s.price * item.fx < PARAMS["min_price_nok"]:
        return f"Aksjekurs under {PARAMS['min_price_nok']:.0f} NOK"
    if not f.get("market_cap") or f["market_cap"] * item.fx < PARAMS["min_market_cap_nok"]:
        return f"Markedsverdi under {PARAMS['min_market_cap_nok'] / 1e6:.0f} mill. NOK"
    if f.get("earnings_yield") is None:
        return "Ikke positivt resultat (mangler P/E)"
    if f["pe"] < PARAMS["min_pe"]:
        return f"P/E under {PARAMS['min_pe']:.0f} (trolig engangseffekter eller verdiendringer, ikke varig inntjening)"
    if f.get("momentum") is None:
        return "Mindre enn 12 måneders kurshistorikk"
    if f["ret_1y"] > PARAMS["max_ret_1y"]:
        return f"Steget over {text.percent(PARAMS['max_ret_1y'], 0)} på 12 mnd. (hendelsesdrevet, ikke momentum)"
    adv_nok = item.adv_nok
    if adv_nok is None or adv_nok < PARAMS["adv_multiple"] * target_position:
        return f"For lav omsetning for en posisjon på {text.nok(target_position)}"
    return None


def _one_share_class_per_issuer(scored: list[Scored]) -> None:
    """Keep only the most liquid share class of each company (e.g. Investor B, not also Investor A)."""
    by_issuer: dict[int, list[Scored]] = {}
    for item in scored:
        if item.eligible and item.stock.issuer_id is not None:
            by_issuer.setdefault(item.stock.issuer_id, []).append(item)
    for classes in by_issuer.values():
        if len(classes) < 2:
            continue
        keep = max(classes, key=lambda c: c.adv_nok or 0)
        for item in classes:
            if item is not keep:
                item.eligible = False
                item.exclusion = f"En annen aksjeklasse ({keep.stock.symbol}) er mer likvid"


def _themes(group: list[Scored]) -> None:
    if not group:
        return
    ey = percentile_ranks({id(s): s.stock.features["earnings_yield"] for s in group})
    bp = percentile_ranks({id(s): s.stock.features.get("book_to_price") for s in group})
    dy = percentile_ranks({id(s): s.stock.features.get("dividend_yield") for s in group})
    roe = percentile_ranks({id(s): s.stock.features.get("roe") for s in group})
    mom = percentile_ranks({id(s): s.stock.features["momentum"] for s in group})
    vol = percentile_ranks({id(s): s.stock.features.get("volatility") for s in group})
    use_vol = len(vol) >= PARAMS["low_vol_min_coverage"] * len(group)
    for s in group:
        key = id(s)
        value_parts = [r[key] for r in (ey, bp, dy) if key in r]
        s.themes = {
            "value": mean(value_parts) if value_parts else None,
            "quality": roe.get(key),
            "momentum": mom.get(key),
            "low_vol": (1 - vol[key]) if use_vol and key in vol else None,
        }


def percentile_ranks(values: dict[Any, float | None]) -> dict[Any, float]:
    """Rank of each non-missing value as a fraction in [0, 1]; ties share the average rank."""
    present = sorted((v, k) for k, v in values.items() if v is not None)
    n = len(present)
    if n == 0:
        return {}
    if n == 1:
        return {present[0][1]: 0.5}
    ranks: dict[Any, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][0] == present[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[present[k][1]] = ((i + j) / 2) / (n - 1)
        i = j + 1
    return ranks


def _overlays(stock: Stock) -> dict[str, float]:
    f, p = stock.features, PARAMS
    out: dict[str, float] = {}
    if stock.country == "SE":
        net = f.get("insider_net_bps") or 0
        if f.get("insider_buyers", 0) >= 2 and net >= 5:
            out["insider"] = p["insider_cluster_buy"]
        elif f.get("insider_buyers", 0) >= 1 and net > 0:
            out["insider"] = p["insider_buy"]
        elif f.get("insider_sellers", 0) >= 2 and net <= -5:
            out["insider"] = p["insider_cluster_sell"]
    else:
        net = f.get("insider_buy_notices", 0) - f.get("insider_sell_notices", 0)
        if net >= 2:
            out["insider"] = p["insider_cluster_buy"]
        elif net == 1:
            out["insider"] = p["insider_buy"]
        elif net <= -2:
            out["insider"] = p["insider_cluster_sell"]
    if f.get("buyback_start"):
        out["buyback"] = p["buyback_new"]
    elif f.get("buyback_notices"):
        out["buyback"] = p["buyback_active"]
    short = f.get("short_pct") or 0
    if short >= 5:
        out["short"] = p["short_5pct"]
    elif short >= 2:
        out["short"] = p["short_2pct"]
    if f.get("short_new"):
        out["short"] = out.get("short", 0) + p["short_increase"]
    return out


def _reasons(item: Scored) -> list[str]:
    f, t = item.stock.features, item.themes
    out = []
    if (t.get("momentum") or 0) >= 0.8 and f.get("ret_1y") is not None:
        out.append(f"Sterk momentum: {text.percent(f['ret_1y'], 0, signed=True)} siste 12 mnd.")
    if (t.get("value") or 0) >= 0.8:
        parts = [f"P/E {text.number(f['pe'], 1)}"]
        if f.get("dividend_yield"):
            parts.append(f"utbytte {text.percent(f['dividend_yield'])}")
        out.append("Lav prising: " + ", ".join(parts))
    if (t.get("quality") or 0) >= 0.8 and f.get("roe"):
        roe = f"over {text.percent(1, 0)}" if f["roe"] > 1 else f"ca. {text.percent(f['roe'], 0)}"
        out.append(f"Høy egenkapitalavkastning ({roe})")
    if (t.get("low_vol") or 0) >= 0.8:
        out.append("Lav volatilitet")
    o = item.overlays
    if o.get("insider", 0) > 0:
        if item.stock.country == "SE":
            people = f["insider_buyers"]
            out.append(f"Innsidere kjøpte for {text.number(f['insider_buy_value'])} SEK siste 90 dager"
                       f" ({people} {'person' if people == 1 else 'personer'})")
        else:
            out.append(f"{f['insider_buy_notices']} meldinger om innsidekjøp siste 90 dager")
    if o.get("insider", 0) < 0:
        out.append("Innsidere har solgt")
    if f.get("buyback_start"):
        out.append("Nytt tilbakekjøpsprogram")
    elif f.get("buyback_notices"):
        out.append("Tilbakekjøp pågår")
    if o.get("short", 0) < 0:
        short = f"Shortandel {text.points(f['short_pct'])}"
        if f.get("short_new"):
            short += ", nylig økt"
        out.append(short)
    if (t.get("momentum") or 1) <= 0.2:
        out.append("Svak momentum")
    return out
