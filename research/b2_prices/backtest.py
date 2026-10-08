"""B2's backtest: the price-only score (12-1 momentum and low volatility), top 12 bought, held while in the top 24.

Signals at each calendar month-end close (2013-03 to 2026-09); trades at each stock's next opening; returns
measured month-end close to month-end close in NOK. See results.md for the rules and what is missing.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from nordic_signals.advisor.allocation import Policy
from nordic_signals.advisor.paper import COURTAGE, COURTAGE_MIN, FX_SPREAD, HOLD_RANK, POLICY, SE_DIVIDEND_TAX, buy_room, costs
from nordic_signals.advisor.scoring import PARAMS, percentile_ranks
from edge import edge
from universe import COUNTRIES, LARGE_DIVIDEND, OSLO_LATE_EX_DATES, Series, Stock, build_series

log = logging.getLogger("b2.backtest")

FIRST_SIGNAL = (2013, 3)
LAST_SIGNAL = (2026, 9)  # its trades fall in October 2026: shown as today's picks, no return
START_CAPITAL = 450_000.0  # NOK: the paper account's long part (90 % of 500 000)
POLICY_NOW = Policy(account_value=500_000.0, **POLICY)
N_POSITIONS = POLICY_NOW.position_count  # 12
TARGET_POSITION = POLICY_NOW.target_position  # 37 500 NOK
HOLD = HOLD_RANK * N_POSITIONS  # 24
MIN_ADV_NOK = PARAMS["adv_multiple"] * TARGET_POSITION  # 1.875 mill. NOK a day
STALE_DAYS = 7  # a stock whose last close is older than this at a month-end has no price that month
LAG_DAYS = 14  # the close a year (a month) back must be at most this many days before the date
EDGE_WINDOW = 63  # trading days of OHLC for the EDGE spread estimate
FILL_DAYS = 10  # calendar days after the month-end within which a buy must fill
MAX_HALF_SPREAD = 0.05  # a few thin, gappy series give absurd EDGE values
DEFAULT_HALF_SPREAD = 0.005  # when neither the stock nor its country and liquidity bucket has an estimate
ACTIVE_SESSIONS = (10, 20)  # a stock must have volume on at least 10 of its last 20 sessions (frozen Yahoo series)
# How a half-spread is set from the stock's signed EDGE estimate: "clipped" (the main books: a negative estimate is
# 0), "absolute" (|estimate|, as before the check: the high end), "signed bucket mean" (the mean signed estimate of
# the stock's country and liquidity bucket that month, floored at 0: the low end)
SPREAD_VARIANTS = ("clipped", "absolute", "signed bucket mean")
# The repairs made after the check (results.md, "Changed after the check"); ``b2.py --undo NAME`` turns one off
REPAIRS = {"split_price": True, "oslo_ex_dates": True, "edge_sign": True, "frozen_series": True}


def month_ends(first: tuple[int, int], last: tuple[int, int]) -> list[date]:
    out = []
    y, m = first
    while (y, m) <= last:
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append(nxt - timedelta(days=1))
        y, m = nxt.year, nxt.month
    return out


def shift_months(d: date, months: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    m += 1
    last_day = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


@dataclass
class Row:
    """One stock at one month-end: its features as features.py/scoring.py compute them, from Yahoo."""

    stock: Stock
    i: int  # index of the month-end close
    price_nok: float  # as quoted that day (Yahoo's close × later splits)
    adv_nok: float | None
    ret_1y: float | None
    ret_1m: float | None
    momentum: float | None
    volatility: float | None
    active_sessions: int = 20  # of the last 20 sessions, those with volume
    price_nok_yahoo: float = 0.0  # Yahoo's split-adjusted close in NOK (the floor's input before the check)
    exclusion: str | None = None
    themes: dict[str, float | None] = field(default_factory=dict)
    score: float | None = None
    rank: int | None = None
    edge_signed: float | None = None  # signed EDGE half-spread, capped at ±5 %
    half_spread: dict[str, float] = field(default_factory=dict)  # by SPREAD_VARIANTS
    half_spread_source: str = ""


class Market:
    def __init__(self, stocks: list[Stock], series: dict[str, Series], indexes: dict[str, Series], fx: Series):
        self.stocks = stocks
        self.series = series
        self.indexes = indexes
        self.fx = fx
        self.tr = {k: s.total_return(SE_DIVIDEND_TAX if self._country(k) == "SE" else 0.0)
                   for k, s in series.items()}
        self.tr_gross = {k: s.total_return(0.0) for k, s in series.items()}
        self._edge_cache: dict[tuple[str, int, bool], float] = {}
        self.spread_stats: dict[date, dict[tuple[str, str], dict[str, float]]] = {}

    def _country(self, yahoo: str) -> str:
        return "SE" if yahoo.endswith(".ST") else "NO"

    def rate(self, currency: str | None, day: date) -> float:
        """NOK per unit: SEK/NOK's close on or before ``day`` (the account uses that day's evening rate)."""
        if currency in (None, "NOK"):
            return 1.0
        i = self.fx.index_on_or_before(day)
        if i is None:
            raise ValueError(f"no SEK/NOK rate on {day}")
        return self.fx.close[i]

    def features(self, stock: Stock, me: date) -> Row | None:
        s = self.series.get(stock.yahoo)
        if s is None:
            return None
        i = s.index_on_or_before(me)
        if i is None or (me - s.days[i]).days > STALE_DAYS:
            return None
        fx = self.rate(stock.currency, me)
        close = s.close[i]
        quoted = close * s.split_factor(me) if REPAIRS["split_price"] else close

        def back(target: date) -> float | None:
            j = s.index_on_or_before(target)
            if j is None or (target - s.days[j]).days > LAG_DAYS:
                return None
            return s.close[j]

        y_close, m_close = back(shift_months(me, -12)), back(shift_months(me, -1))
        ret_1y = close / y_close - 1 if y_close else None
        ret_1m = close / m_close - 1 if m_close else None
        # features._load_universe: (1 + ret_1y) / (1 + ret_1m) - 1, from Nordnet's price returns
        momentum = (1 + ret_1y) / (1 + ret_1m) - 1 if ret_1y is not None and ret_1m is not None and ret_1m > -1 else None
        # features._add_yahoo_history: bars after asof - 100 days, adjclose or close, the last 61, log returns.
        # Yahoo's adjclose takes Oslo's dividends on its late ex-dates, so the levels are our own total return.
        lo = bisect.bisect_right(s.days, me - timedelta(days=100))
        window = range(lo, i + 1)
        tr = self.tr_gross[stock.yahoo][1]
        levels = [tr[k] if REPAIRS["oslo_ex_dates"] else (s.adjclose[k] or s.close[k]) for k in window][-61:]
        rets = [math.log(b / a) for a, b in zip(levels, levels[1:], strict=False) if a > 0 and b > 0]
        vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) >= 40 else None
        traded = [s.close[k] * s.volume[k] for k in window if s.close[k] and s.volume[k]]
        adv = statistics.median(traded[-20:]) * fx if traded else None
        active = sum(1 for k in range(max(0, i - ACTIVE_SESSIONS[1] + 1), i + 1) if s.volume[k])
        return Row(stock, i, quoted * fx, adv, ret_1y, ret_1m, momentum, vol, active, close * fx)

    def half_spread(self, yahoo: str, i: int, filled_opens_missing: bool = False) -> float:
        """The signed EDGE half-spread over the 63 sessions to ``i`` (``bidask.edge(..., sign=True)`` / 2): noise
        can make the estimate of s² negative. ``filled_opens_missing``: an opening equal to the previous close
        (probably filled in by Yahoo, not the auction) counts as missing."""
        key = (yahoo, i, filled_opens_missing)
        if key not in self._edge_cache:
            s = self.series[yahoo]
            lo = max(0, i - EDGE_WINDOW + 1)
            sl = slice(lo, i + 1)
            opens = s.open[sl]
            if filled_opens_missing:
                opens = [None if k > 0 and s.open[k] == s.close[k - 1] else s.open[k] for k in range(lo, i + 1)]
            spread = edge(opens, s.high[sl], s.low[sl], s.close[sl], sign=REPAIRS["edge_sign"])
            self._edge_cache[key] = spread / 2 if not math.isnan(spread) else math.nan
        return self._edge_cache[key]


def exclusion(row: Row) -> str | None:
    """scoring._exclusion, for what prices can tell: no market cap or P/E history exists here."""
    if row.price_nok < PARAMS["min_price_nok"]:
        return "price under 5 NOK"
    if row.momentum is None:
        return "less than 12 months of prices"
    if row.ret_1y > PARAMS["max_ret_1y"]:
        return "rose more than 300 % in 12 months"
    if REPAIRS["frozen_series"] and row.active_sessions < ACTIVE_SESSIONS[0]:
        return "volume on fewer than 10 of the last 20 sessions"
    if row.adv_nok is None or row.adv_nok < MIN_ADV_NOK:
        return "turnover too low"
    return None


def score_month(market: Market, me: date) -> list[Row]:
    rows = [r for r in (market.features(s, me) for s in market.stocks) if r is not None]
    for r in rows:
        r.exclusion = exclusion(r)
    # scoring._one_share_class_per_issuer: the most liquid class of each company stays
    by_issuer: dict[int, list[Row]] = defaultdict(list)
    for r in rows:
        if r.exclusion is None and r.stock.issuer_id is not None:
            by_issuer[r.stock.issuer_id].append(r)
    for classes in by_issuer.values():
        if len(classes) > 1:
            keep = max(classes, key=lambda c: c.adv_nok or 0)
            for r in classes:
                if r is not keep:
                    r.exclusion = f"another share class ({keep.stock.symbol}) is more liquid"
    eligible = [r for r in rows if r.exclusion is None]
    # scoring._themes: percentile ranks within the country; low volatility only with 50 % coverage
    for country in COUNTRIES:
        group = [r for r in eligible if r.stock.country == country]
        mom = percentile_ranks({id(r): r.momentum for r in group})
        vol = percentile_ranks({id(r): r.volatility for r in group})
        use_vol = len(vol) >= PARAMS["low_vol_min_coverage"] * len(group)
        for r in group:
            r.themes = {"momentum": mom.get(id(r)),
                        "low_vol": (1 - vol[id(r)]) if use_vol and id(r) in vol else None}
            available = [v for v in r.themes.values() if v is not None]
            r.score = statistics.mean(available)
    for rank, r in enumerate(sorted(eligible, key=lambda r: r.score, reverse=True), 1):
        r.rank = rank
    _spreads(market, me, eligible)
    return rows


def liquidity_bucket(adv_nok: float) -> str:
    if adv_nok < 10e6:
        return "1.9-10 mill. NOK"
    if adv_nok < 50e6:
        return "10-50 mill. NOK"
    return "over 50 mill. NOK"


def _spreads(market: Market, me: date, eligible: list[Row]) -> None:
    """Each eligible stock's half-spread under each of SPREAD_VARIANTS, from its signed EDGE estimate over the last
    63 days; a missing estimate takes its country and liquidity bucket's median that month."""
    signed: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in eligible:
        r.edge_signed = capped(market.half_spread(r.stock.yahoo, r.i))
        if r.edge_signed is not None:
            r.half_spread_source = "edge"
            signed[(r.stock.country, liquidity_bucket(r.adv_nok))].append(r.edge_signed)
        else:
            r.half_spread_source = "bucket median"
    stats = {key: {"clipped": statistics.median(max(v, 0.0) for v in vs),
                   "absolute": statistics.median(abs(v) for v in vs),
                   "signed bucket mean": max(statistics.mean(vs), 0.0)} for key, vs in signed.items()}
    market.spread_stats[me] = stats
    for r in eligible:
        r.half_spread = {v: spread_for(v, r.edge_signed, r.stock.country, r.adv_nok, stats) for v in SPREAD_VARIANTS}


def capped(hs: float) -> float | None:
    return None if math.isnan(hs) else max(-MAX_HALF_SPREAD, min(hs, MAX_HALF_SPREAD))


def spread_for(variant: str, signed: float | None, country: str, adv_nok: float | None,
               stats: dict[tuple[str, str], dict[str, float]]) -> float:
    pool = stats.get((country, liquidity_bucket(adv_nok or 0.0)))
    if variant == "signed bucket mean" or signed is None:
        return pool[variant] if pool else DEFAULT_HALF_SPREAD
    return max(signed, 0.0) if variant == "clipped" else abs(signed)


@dataclass
class Book:
    """The paper account's long part, as a replay over month-ends. ``spread``/``fees`` switch the costs."""

    name: str
    fees: bool = True
    spread: bool = True
    spread_variant: str = "clipped"
    sector_cap: int | None = None
    sectors: dict[str, str | None] = field(default_factory=dict)
    cash: float = START_CAPITAL
    units: dict[str, float] = field(default_factory=dict)  # total-return units held, by Yahoo symbol
    stocks: dict[str, Stock] = field(default_factory=dict)
    returns: list[float] = field(default_factory=list)
    mix: list[dict[str, float]] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    turnover: list[float] = field(default_factory=list)
    trades: list[int] = field(default_factory=list)
    cost_parts: dict[str, float] = field(default_factory=lambda: {"courtage": 0.0, "fx": 0.0, "spread": 0.0})
    cost_by_month: list[float] = field(default_factory=list)
    held_log: list[list[str]] = field(default_factory=list)
    spread_paid: list[float] = field(default_factory=list)
    position_returns: list[tuple[str, str, float]] = field(default_factory=list)
    fills: list[tuple[str, int, str, float]] = field(default_factory=list)  # (symbol, bar, buy/sell, half-spread)

    def value(self, market: Market, day: date) -> float:
        total = self.cash
        for yahoo, units in self.units.items():
            s = self.series(market, yahoo)
            i = s.index_on_or_before(day)
            total += units * self.levels(market, yahoo)[1][i] * market.rate(self.stocks[yahoo].currency, day)
        return total

    def series(self, market: Market, yahoo: str) -> Series:
        return market.series[yahoo]

    def levels(self, market: Market, yahoo: str) -> tuple[list[float], list[float]]:
        return market.tr[yahoo]

    def _costs(self, value: float, currency: str | None, half_spread: float) -> tuple[float, float, float]:
        courtage, fx = costs(value, currency) if self.fees else (0.0, 0.0)
        return courtage, fx, (half_spread * value if self.spread else 0.0)

    def rebalance(self, market: Market, me: date, rows: list[Row]) -> None:
        start_equity = self.value(market, me)
        ranked = {r.stock.yahoo: r for r in rows if r.rank is not None}
        every = {r.stock.yahoo: r for r in rows}
        variant = self.spread_variant
        by_rank = sorted(ranked.values(), key=lambda r: r.rank)
        traded_value, n_trades, month_costs = 0.0, 0, 0.0
        # Sells: holdings no longer among the best 24 eligible
        for yahoo in list(self.units):
            r = ranked.get(yahoo)
            if r is not None and r.rank <= HOLD:
                continue
            s = self.series(market, yahoo)
            j = s.index_after(me)
            if j is None:
                continue  # no later price: kept and valued at its last close
            currency = self.stocks[yahoo].currency
            value = self.units.pop(yahoo) * self.levels(market, yahoo)[0][j] * market.rate(currency, s.days[j])
            if r is not None:
                hs = r.half_spread[variant]
            else:  # no longer eligible: its own estimate, or its country and liquidity bucket's
                row = every.get(yahoo)
                signed = capped(market.half_spread(yahoo, s.index_on_or_before(me)))
                hs = spread_for(variant, signed, self.stocks[yahoo].country, row.adv_nok if row else None,
                                market.spread_stats.get(me, {}))
            c = self._costs(value, currency, hs)
            self.fills.append((yahoo, j, "sell", hs))
            self.cash += value - sum(c)
            self._book_costs(c)
            month_costs += sum(c)
            traded_value += value
            n_trades += 1
        # Buys: the best-ranked not held, until 12 are held; the cash is shared equally between them
        counts: dict[str, int] = defaultdict(int)
        for yahoo in self.units:
            counts[self._sector(yahoo)] += 1
        picks = []
        for r in by_rank:
            if len(self.units) + len(picks) >= N_POSITIONS:
                break
            yahoo = r.stock.yahoo
            if yahoo in self.units:
                continue
            j = market.series[yahoo].index_after(me)
            if j is None or (market.series[yahoo].days[j] - me).days > FILL_DAYS:
                continue
            sector = self._sector(yahoo)
            if self.sector_cap and not sector.startswith("?") and counts[sector] >= self.sector_cap:
                continue
            counts[sector] += 1
            picks.append((r, j))
        budget = self.cash / len(picks) if picks else 0.0
        for r, j in picks:
            yahoo, currency = r.stock.yahoo, r.stock.currency
            s = market.series[yahoo]
            hs = r.half_spread[variant] if self.spread else 0.0
            value = self._affordable(budget, currency, hs)
            self.fills.append((yahoo, j, "buy", hs))
            c = self._costs(value, currency, hs)
            self.cash -= value + sum(c)
            self._book_costs(c)
            month_costs += sum(c)
            self.units[yahoo] = value / (self.levels(market, yahoo)[0][j] * market.rate(currency, s.days[j]))
            self.stocks[yahoo] = r.stock
            traded_value += value
            n_trades += 1
            self.spread_paid.append(hs)
        self.turnover.append(traded_value / 2 / start_equity)
        self.trades.append(n_trades)
        self.cost_by_month.append(month_costs / start_equity)
        self.held_log.append(sorted(self.units))

    def _affordable(self, budget: float, currency: str | None, hs: float) -> float:
        """The trade value whose courtage, currency exchange and half-spread fit in ``budget`` (paper.costs)."""
        hs = hs if self.spread else 0.0
        if not self.fees:
            return budget / (1 + hs)
        value = budget / (buy_room(currency) + hs)  # paper.buy_room: 1 + courtage + currency exchange
        if COURTAGE * value < COURTAGE_MIN:
            fx = FX_SPREAD if currency not in (None, "NOK") else 0.0
            value = (budget - COURTAGE_MIN) / (1 + fx + hs)
        return max(value, 0.0)

    def _book_costs(self, c: tuple[float, float, float]) -> None:
        self.cost_parts["courtage"] += c[0]
        self.cost_parts["fx"] += c[1]
        self.cost_parts["spread"] += c[2]

    def _sector(self, yahoo: str) -> str:
        return self.sectors.get(yahoo) or "?" + yahoo  # an unknown sector is its own: never capped

    def country_mix(self, market: Market, day: date) -> dict[str, float]:
        values: dict[str, float] = defaultdict(float)
        for yahoo, units in self.units.items():
            s = self.series(market, yahoo)
            i = s.index_on_or_before(day)
            values[self.stocks[yahoo].country] += units * self.levels(market, yahoo)[1][i] * market.rate(
                self.stocks[yahoo].currency, day)
        total = sum(values.values())
        return {c: values[c] / total for c in COUNTRIES} if total else {"NO": 0.5, "SE": 0.5}


def holding_return(market: Market, yahoo: str, currency: str | None, me: date, nxt: date,
                   gross: bool = True) -> float | None:
    """NOK total return from the month-end close to the next month-end close (the EW universe's)."""
    s = market.series[yahoo]
    i, j = s.index_on_or_before(me), s.index_on_or_before(nxt)
    if i is None or j is None:
        return None
    tr = market.tr_gross[yahoo][1] if gross else market.tr[yahoo][1]
    return tr[j] / tr[i] * market.rate(currency, nxt) / market.rate(currency, me) - 1


def forward_local(market: Market, yahoo: str, me: date, nxt: date) -> float | None:
    """Local-currency total return from the next opening to the next month-end close: the rank IC's target."""
    s = market.series[yahoo]
    j, k = s.index_after(me), s.index_on_or_before(nxt)
    if j is None or k is None or k < j or (s.days[j] - me).days > FILL_DAYS:
        return None
    tr_open, tr_close = market.tr_gross[yahoo]
    return tr_close[k] / tr_open[j] - 1


def index_return(series: Series, me: date, nxt: date) -> float:
    i, j = series.index_on_or_before(me), series.index_on_or_before(nxt)
    return series.close[j] / series.close[i] - 1


# Statistics

def stats(excess: list[float], lags: int = 6) -> dict[str, float]:
    n = len(excess)
    mean = statistics.mean(excess)
    sd = statistics.stdev(excess)
    nw = _newey_west_se(excess, lags)
    return {"months": n, "mean_month": mean, "excess_a_year": 12 * mean, "tracking_error": sd * math.sqrt(12),
            "t": mean / (sd / math.sqrt(n)), "t_newey_west": mean / nw, "sharpe_of_excess": mean / sd * math.sqrt(12),
            "se_a_year": 12 * sd / math.sqrt(n)}


def _newey_west_se(x: list[float], lags: int) -> float:
    n, mean = len(x), statistics.mean(x)
    d = [v - mean for v in x]
    var = sum(v * v for v in d) / n
    for lag in range(1, lags + 1):
        w = 1 - lag / (lags + 1)
        var += 2 * w * sum(d[t] * d[t - lag] for t in range(lag, n)) / n
    return math.sqrt(var / n)


def cagr(returns: list[float]) -> float:
    growth = math.prod(1 + r for r in returns)
    return growth ** (12 / len(returns)) - 1


def max_drawdown(returns: list[float]) -> float:
    level, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        level *= 1 + r
        peak = max(peak, level)
        worst = min(worst, level / peak - 1)
    return worst


def summary(returns: list[float]) -> dict[str, float]:
    return {"cagr": cagr(returns), "vol": statistics.stdev(returns) * math.sqrt(12),
            "max_drawdown": max_drawdown(returns), "mean_a_year": 12 * statistics.mean(returns)}


def rank_ic(pairs: list[tuple[float, float]]) -> float | None:
    """Spearman: the correlation of percentile ranks (ties share the average rank, as scoring.py ranks)."""
    if len(pairs) < 10:
        return None
    a = percentile_ranks(dict(enumerate(p[0] for p in pairs)))
    b = percentile_ranks(dict(enumerate(p[1] for p in pairs)))
    xs, ys = [a[k] for k in range(len(pairs))], [b[k] for k in range(len(pairs))]
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def ic_stats(series: list[float]) -> dict[str, float]:
    n = len(series)
    mean, sd = statistics.mean(series), statistics.stdev(series)
    return {"months": n, "mean_ic": mean, "sd": sd, "t": mean / (sd / math.sqrt(n)),
            "share_positive": sum(v > 0 for v in series) / n}


# Checks of the data repairs made after the review

DELISTED_EXAMPLES = ("SWMA.ST", "ICA.ST", "HNA.OL", "EKO.OL", "OCY.OL", "ADE.OL", "KIND-SDB.ST")  # taken over


def _dividend_drops(s: Series, dividends: dict[date, float]) -> list[tuple[int, float, float]]:
    """(year, close-to-close fall on the ex-date, fall the day before), in units of the dividend, for dividends of
    2-20 % of the previous close that fall on a trading day."""
    out = []
    for day, amount in dividends.items():
        k = s.index_on_or_before(day)
        if k is None or k < 2 or s.days[k] != day or not 0.02 <= amount / s.close[k - 1] <= LARGE_DIVIDEND:
            continue
        out.append((day.year, (s.close[k - 1] - s.close[k]) / amount, (s.close[k - 2] - s.close[k - 1]) / amount))
    return out


def checks(dl, market: Market, signals: list[date], scored: dict[date, list[Row]], net: Book,
           stocks: list[Stock]) -> dict[str, Any]:
    out: dict[str, Any] = {"delisted_examples_on_yahoo": {y: dl.yahoo_status(y) for y in DELISTED_EXAMPLES}}
    # The 5 NOK floor on the quoted price vs on Yahoo's split-adjusted close
    let_in = kept_out = 0
    for me in signals:
        for r in scored[me]:
            if (r.price_nok < PARAMS["min_price_nok"]) == (r.price_nok_yahoo < PARAMS["min_price_nok"]):
                continue
            other = exclusion(replace(r, price_nok=r.price_nok_yahoo))
            if r.exclusion == "price under 5 NOK" and other is None:
                let_in += 1
            elif r.exclusion is None and other == "price under 5 NOK":
                kept_out += 1
    out["price_floor"] = {
        "stocks_with_splits": sum(1 for s in market.series.values() if s.splits),
        "reverse_splits": sum(r < 1 for s in market.series.values() for _, r in s.splits),
        "forward_splits": sum(r > 1 for s in market.series.values() for _, r in s.splits),
        "rows_under_5_nok_quoted_but_not_split_adjusted": let_in,
        "rows_over_5_nok_quoted_but_not_split_adjusted": kept_out}
    # Oslo's late ex-dates: the fall at the ex-date, before and after the correction, by year
    raw: dict[int, list[tuple[float, float]]] = defaultdict(list)
    fixed: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for st in stocks:
        s = market.series.get(st.yahoo)
        if s is None or st.country != "NO":
            continue
        yahoo_divs: dict[date, float] = defaultdict(float)
        for d in dl.yahoo_daily(st.yahoo)[1]:
            yahoo_divs[date.fromisoformat(d["ex_date"])] += d.get("amount") or 0.0
        for y, a, b in _dividend_drops(s, yahoo_divs):
            raw[y].append((a, b))
        for y, a, b in _dividend_drops(s, s.dividends):
            fixed[y].append((a, b))

    def medians(d: dict[int, list[tuple[float, float]]]) -> dict[int, list[float]]:
        return {str(y): [len(v), statistics.median(a for a, _ in v), statistics.median(b for _, b in v)]
                for y, v in sorted(d.items())}

    out["oslo_dividends"] = {
        "moved_a_trading_day_earlier": sum(s.dividends_moved for s in market.series.values()),
        "window": [d.isoformat() for d in OSLO_LATE_EX_DATES],
        "median_fall_by_year_n_on_ex_date_day_before_yahoo": medians(raw),
        "median_fall_by_year_n_on_ex_date_day_before_corrected": medians(fixed)}
    # Frozen or barely traded series
    frozen = [r for me in signals for r in scored[me] if r.exclusion == "volume on fewer than 10 of the last 20 sessions"]
    out["frozen_series"] = {
        "rows_excluded": len(frozen),
        "of_which_turnover_passed": sum(1 for r in frozen if r.adv_nok and r.adv_nok >= MIN_ADV_NOK),
        "of_which_volatility_zero": sum(1 for r in frozen if r.volatility == 0),
        "symbols": sorted({r.stock.yahoo for r in frozen if r.adv_nok and r.adv_nok >= MIN_ADV_NOK})}
    # The net book's fills: how many at an opening equal to the previous close (probably filled in by Yahoo)
    fills: dict[str, dict[str, Any]] = {}
    for side in ("buy", "sell"):
        rows = [(market.series[y], j) for y, j, sd, _ in net.fills if sd == side and j >= 1]
        same = [1 for s, j in rows if s.open[j] is not None and s.open[j] == s.close[j - 1]]
        missing = [1 for s, j in rows if s.open[j] is None]
        gaps = [(s.open[j] or s.close[j - 1]) / s.close[j - 1] - 1 for s, j in rows]
        fills[side] = {"n": len(rows), "share_opening_equals_previous_close": len(same) / len(rows),
                       "share_opening_missing_filled_at_previous_close": len(missing) / len(rows),
                       "mean_gap_previous_close_to_fill": statistics.mean(gaps)}
    # EDGE on the book's buys with such openings counted as missing (a sensitivity, not used by the books)
    pairs = []
    for y, j, side, hs in net.fills:
        if side != "buy":
            continue
        i = market.series[y].index_on_or_before(market.series[y].days[j] - timedelta(days=1))
        alt = capped(market.half_spread(y, i, filled_opens_missing=True))
        if alt is not None:
            pairs.append((hs, max(alt, 0.0)))
    fills["edge_on_buys"] = {"n": len(pairs), "mean_half_spread_charged": statistics.mean(a for a, _ in pairs),
                             "mean_with_filled_openings_missing": statistics.mean(b for _, b in pairs)}
    out["net_book_fills"] = fills
    return out


# The run

def run_books(market: Market, signals: list[date], scored: dict[date, list[Row]], books: list[Book]) -> None:
    """Rebalance every book at each month-end and record the month's NOK return to the next month-end."""
    for k, me in enumerate(signals[:-1]):
        nxt = signals[k + 1]
        for book in books:
            before = book.value(market, me)
            book.rebalance(market, me, scored[me])
            book.mix.append(book.country_mix(market, me))  # the new book's mix, valued at the month-end close
            after = book.value(market, nxt)
            book.returns.append(after / before - 1)
            book.equity.append(after)
            for yahoo in book.held_log[-1]:
                r = holding_return(market, yahoo, book.stocks[yahoo].currency, me, nxt, gross=False)
                if r is not None:
                    book.position_returns.append((me.isoformat(), yahoo, r))


def load(dl, stocks: list[Stock]) -> tuple[Market, list[str]]:
    from b2 import FX, INDEXES  # noqa: PLC0415

    series: dict[str, Series] = {}
    missing: list[str] = []
    for s in stocks:
        parsed = dl.yahoo_daily(s.yahoo)
        if parsed is None or not parsed[0]:
            missing.append(s.yahoo)
            continue
        late = OSLO_LATE_EX_DATES if s.country == "NO" and REPAIRS["oslo_ex_dates"] else None
        series[s.yahoo] = build_series(s.yahoo, *parsed, late_ex_dates=late)
    have = [s for s in stocks if s.yahoo in series]
    idx = {c: build_series(sym, *dl.yahoo_daily(sym)[:2]) for c, sym in INDEXES.items()}
    fx = build_series(FX, *dl.yahoo_daily(FX)[:2], spike=0.03)
    return Market(have, series, idx, fx), missing


def index_nok(market: Market, signals: list[date]) -> dict[str, list[float]]:
    """Each index's NOK return over each month (OMXSBGI × SEK/NOK)."""
    months = signals[1:]
    idx = {c: [index_return(market.indexes[c], a, b) for a, b in zip(signals, months, strict=False)]
           for c in COUNTRIES}
    fx = [market.rate("SEK", b) / market.rate("SEK", a) - 1 for a, b in zip(signals, months, strict=False)]
    return {"NO": idx["NO"], "SE": [(1 + r) * (1 + f) - 1 for r, f in zip(idx["SE"], fx, strict=True)]}


def blend(book: Book, parts: dict[str, list[float]]) -> list[float]:
    return [sum(book.mix[k][c] * parts[c][k] for c in COUNTRIES) for k in range(len(book.returns))]


def ew_universe(market: Market, signals: list[date], scored: dict[date, list[Row]]
                ) -> tuple[list[float], dict[str, list[float]]]:
    """Equal-weighted universe: every eligible stock at the month-end, NOK gross total return, no costs; pooled
    and by country."""
    ew_all: list[float] = []
    ew_country: dict[str, list[float]] = {c: [] for c in COUNTRIES}
    for me, nxt in zip(signals, signals[1:], strict=False):
        rets = defaultdict(list)
        for r in scored[me]:
            if r.rank is None:
                continue
            x = holding_return(market, r.stock.yahoo, r.stock.currency, me, nxt)
            if x is not None:
                rets[r.stock.country].append(x)
        ew_all.append(statistics.mean(rets["NO"] + rets["SE"]))
        for c in COUNTRIES:
            ew_country[c].append(statistics.mean(rets[c]) if rets[c] else ew_all[-1])
    return ew_all, ew_country


def rank_ics(market: Market, signals: list[date], scored: dict[date, list[Row]]) -> dict[str, Any]:
    """Rank IC of each theme against the next month's local total return (from the next opening), by country;
    pooled = the countries' ICs weighted by their numbers of stocks."""
    ic: dict[str, dict[str, list[float]]] = {t: {"NO": [], "SE": [], "pooled": []}
                                             for t in ("momentum", "low_vol", "score")}
    for me, nxt in zip(signals, signals[1:], strict=False):
        rows = [r for r in scored[me] if r.rank is not None]
        fwd = {r.stock.yahoo: forward_local(market, r.stock.yahoo, me, nxt) for r in rows}
        for theme in ic:
            per = {}
            for c in COUNTRIES:
                pairs = []
                for r in rows:
                    v = r.score if theme == "score" else r.themes.get(theme)
                    if r.stock.country == c and v is not None and fwd[r.stock.yahoo] is not None:
                        pairs.append((v, fwd[r.stock.yahoo]))
                value = rank_ic(pairs)
                if value is not None:
                    ic[theme][c].append(value)
                    per[c] = (value, len(pairs))
            if len(per) == 2:
                ic[theme]["pooled"].append(sum(v * n for v, n in per.values()) / sum(n for _, n in per.values()))
    return {t: {c: ic_stats(v) for c, v in d.items() if len(v) > 2} for t, d in ic.items()}


def score_quintiles(market: Market, signals: list[date], scored: dict[date, list[Row]]) -> list[float]:
    """Equal-weighted gross NOK return a year of each score quintile (pooled ranking), month-end to month-end."""
    quintiles: list[list[float]] = [[] for _ in range(5)]
    for me, nxt in zip(signals, signals[1:], strict=False):
        ranked = sorted((r for r in scored[me] if r.rank is not None), key=lambda r: r.rank)
        for q in range(5):
            group = ranked[q * len(ranked) // 5:(q + 1) * len(ranked) // 5]
            rets = [x for x in (holding_return(market, r.stock.yahoo, r.stock.currency, me, nxt) for r in group)
                    if x is not None]
            quintiles[q].append(statistics.mean(rets))
    return [12 * statistics.mean(q) for q in quintiles]


def key_numbers(market: Market, signals: list[date], scored: dict[date, list[Row]]) -> dict[str, float]:
    """The numbers the check moved, for "Changed after the check": the net book and the cross-section."""
    net = Book("net")
    run_books(market, signals, scored, [net])
    bench = blend(net, index_nok(market, signals))
    ew_all, ew_country = ew_universe(market, signals, scored)
    vs_index = stats([a - b for a, b in zip(net.returns, bench, strict=True)])
    ic = rank_ics(market, signals, scored)
    total_cost = sum(net.cost_parts.values())
    cost = 12 * statistics.mean(net.cost_by_month)
    return {"net_vs_index": vs_index["excess_a_year"], "net_vs_index_t": vs_index["t"], "cost_a_year": cost,
            "half_spread_cost_a_year": cost * net.cost_parts["spread"] / total_cost,
            "ew_universe_cagr": cagr(ew_all),
            "net_vs_ew_book_mix": statistics.mean(a - b for a, b in zip(
                net.returns, blend(net, ew_country), strict=True)) * 12,
            "ic_momentum_pooled": ic["momentum"]["pooled"]["mean_ic"], "ic_momentum_pooled_t": ic["momentum"]["pooled"]["t"],
            "ic_momentum_stockholm_t": ic["momentum"]["SE"]["t"],
            "ic_low_vol_pooled": ic["low_vol"]["pooled"]["mean_ic"], "ic_low_vol_pooled_t": ic["low_vol"]["pooled"]["t"],
            "bottom_quintile": score_quintiles(market, signals, scored)[-1]}


def leave_one_out(dl, stocks: list[Stock], market: Market, signals: list[date]) -> dict[str, dict[str, float]]:
    """Key numbers with each repair made after the check turned off in turn (all the others on)."""
    out = {}
    for name in [k for k, on in REPAIRS.items() if on]:
        REPAIRS[name] = False
        try:
            log.info("leave-one-out: without %s", name)
            m = load(dl, stocks)[0] if name == "oslo_ex_dates" else Market(market.stocks, market.series,
                                                                           market.indexes, market.fx)
            out[name] = key_numbers(m, signals, {me: score_month(m, me) for me in signals})
        finally:
            REPAIRS[name] = True
    return out


def run(dl, stocks: list[Stock], dropped: dict[str, int], out_dir: Path, attribution: bool = True) -> None:  # noqa: PLR0915
    market, missing = load(dl, stocks)
    series, fx = market.series, market.fx
    signals = month_ends(FIRST_SIGNAL, LAST_SIGNAL)
    log.info("scoring %d month-ends over %d stocks", len(signals), len(market.stocks))
    scored = {me: score_month(market, me) for me in signals}

    # Exploratory: Yahoo's sectors (Nordnet's list has none) for every stock ever ranked in the top 60
    ever_top = sorted({r.stock.yahoo for rows in scored.values() for r in rows if r.rank and r.rank <= 60})
    sectors = {y: dl.yahoo_sector(y) for y in ever_top}

    books = [Book("net"), Book("fees only", spread=False), Book("gross", fees=False, spread=False),
             Book("net, sector cap 3 (exploratory)", sector_cap=3, sectors=sectors),
             Book("net, half-spread |EDGE| (high end)", spread_variant="absolute"),
             Book("net, half-spread signed bucket mean (low end)", spread_variant="signed bucket mean")]
    run_books(market, signals, scored, books)
    net, fees_only, gross = books[:3]

    months = signals[1:]  # each return month ends at these month-ends
    idx_nok = index_nok(market, signals)
    ew_all, ew_country = ew_universe(market, signals, scored)
    results: dict[str, Any] = {"period": {"first_signal": signals[0].isoformat(), "last_return_month_end":
                                          months[-1].isoformat(), "months": len(months)}}

    def excess_block(book: Book) -> dict[str, Any]:
        bench = blend(book, idx_nok)
        ew_mix = blend(book, ew_country)
        out = {
            "book": summary(book.returns),
            "index_blend": summary(bench),
            "ew_universe": summary(ew_all),
            "ew_universe_book_mix": summary(ew_mix),
            "vs_index": stats([a - b for a, b in zip(book.returns, bench, strict=True)]),
            "vs_ew_universe": stats([a - b for a, b in zip(book.returns, ew_all, strict=True)]),
            "vs_ew_universe_book_mix": stats([a - b for a, b in zip(book.returns, ew_mix, strict=True)]),
            "relative_max_drawdown_vs_index": max_drawdown(
                [(1 + a) / (1 + b) - 1 for a, b in zip(book.returns, bench, strict=True)]),
            "monthly_turnover_one_way": statistics.mean(book.turnover),
            "trades_a_month": statistics.mean(book.trades),
            "cost_a_year": 12 * statistics.mean(book.cost_by_month),
            "mean_se_share": statistics.mean(m["SE"] for m in book.mix),
            "final_value_nok": book.equity[-1],
        }
        total_cost = sum(book.cost_parts.values())  # split cost_a_year in the parts' shares of all costs paid
        out["cost_parts_a_year"] = {k: out["cost_a_year"] * v / total_cost if total_cost else 0.0
                                    for k, v in book.cost_parts.items()}
        if book.spread_paid:
            out["half_spread_paid_median"] = statistics.median(book.spread_paid)
            out["half_spread_paid_mean"] = statistics.mean(book.spread_paid)
        halves = len(months) // 2
        out["halves_vs_index"] = {
            f"{months[0]:%Y-%m}..{months[halves - 1]:%Y-%m}": stats(
                [a - b for a, b in zip(book.returns[:halves], bench[:halves], strict=True)]),
            f"{months[halves]:%Y-%m}..{months[-1]:%Y-%m}": stats(
                [a - b for a, b in zip(book.returns[halves:], bench[halves:], strict=True)]),
        }
        years_tbl: dict[str, dict[str, float]] = {}
        for y in sorted({m.year for m in months}):
            ks = [k for k, m in enumerate(months) if m.year == y]
            years_tbl[str(y)] = {"book": math.prod(1 + book.returns[k] for k in ks) - 1,
                                 "index_blend": math.prod(1 + bench[k] for k in ks) - 1,
                                 "months": len(ks)}
        out["calendar_years"] = years_tbl
        return out

    results["books"] = {b.name: excess_block(b) for b in books}
    results["cost_drag_a_year"] = {
        "gross_minus_net_mean_return": 12 * (statistics.mean(gross.returns) - statistics.mean(net.returns)),
        "gross_minus_net_cagr": cagr(gross.returns) - cagr(net.returns),
        "fees_only_minus_net_cagr": cagr(fees_only.returns) - cagr(net.returns),
    }

    results["rank_ic"] = rank_ics(market, signals, scored)
    results["score_quintiles_a_year"] = score_quintiles(market, signals, scored)  # exploratory

    # Universe, coverage and survivorship
    eligible_by_year = {}
    for me in signals:
        if me.month == 12 or me == signals[0]:
            rows = [r for r in scored[me] if r.rank is not None]
            eligible_by_year[me.isoformat()] = {c: sum(r.stock.country == c for r in rows) for c in COUNTRIES}
    exclusions: dict[str, int] = defaultdict(int)
    for r in scored[signals[-1]]:
        exclusions[r.exclusion or "eligible"] += 1
    late = [y for y, s in series.items() if s.days[0] > date(2012, 3, 31)]
    spread_sources = defaultdict(int)
    spread_buckets: dict[str, list[float]] = defaultdict(list)
    for me in signals:
        for r in scored[me]:
            if r.rank is not None:
                spread_sources[r.half_spread_source] += 1
                if r.edge_signed is not None:
                    spread_buckets[f"{r.stock.country} {liquidity_bucket(r.adv_nok)}"].append(r.edge_signed)
    results["universe"] = {
        "nordnet_instruments_kept": len(stocks),
        "nordnet_dropped": dropped,
        "by_country": {c: sum(s.country == c for s in stocks) for c in COUNTRIES},
        "yahoo_missing": len(missing),
        "yahoo_missing_symbols": missing,
        "yahoo_history_starts_after_2012_03": len(late),
        "eligible_by_month_end": eligible_by_year,
        "exclusions_at_last_signal": dict(exclusions),
        "bad_opens_replaced_by_previous_close": sum(s.bad_opens for s in series.values()),
        "bad_dividends_dropped": sum(s.bad_dividends for s in series.values()),
        "one_day_spikes_repaired": sum(s.spikes for s in series.values()),
        "fx_spikes_repaired": fx.spikes,
        "large_dividends_kept": sum(s.large_dividends_kept for s in series.values()),
        "bars": sum(len(s.days) for s in series.values()),
        "half_spread_sources": dict(spread_sources),
        "edge_half_spread_by_bucket": {k: {"n": len(v), "share_negative": sum(x < 0 for x in v) / len(v),
                                           "median_clipped": statistics.median(max(x, 0.0) for x in v),
                                           "median_absolute": statistics.median(abs(x) for x in v),
                                           "signed_mean": statistics.mean(v)}
                                       for k, v in sorted(spread_buckets.items())},
        "sector_coverage_ever_top60": {"stocks": len(sectors), "with_sector": sum(1 for v in sectors.values() if v)},
    }
    results["checks"] = checks(dl, market, signals, scored, net, stocks)
    # Checks: the largest monthly position returns (bad prints would show here), and today's picks
    big = sorted(net.position_returns, key=lambda t: abs(t[2]), reverse=True)[:10]
    results["largest_position_months"] = [{"month_end": a, "symbol": b, "return": c} for a, b, c in big]
    last = sorted((r for r in scored[signals[-1]] if r.rank is not None), key=lambda r: r.rank)[:HOLD]
    results["picks_at_last_signal"] = [{"rank": r.rank, "symbol": r.stock.symbol, "country": r.stock.country,
                                        "score": round(r.score, 3), "momentum": r.momentum,
                                        "volatility": r.volatility, "sector": sectors.get(r.stock.yahoo)}
                                       for r in last]
    results["parameters"] = {"repairs_after_check": dict(REPAIRS), "n_positions": N_POSITIONS, "hold_rank": HOLD,
                             "min_adv_nok": MIN_ADV_NOK,
                             "target_position_nok": TARGET_POSITION, "min_price_nok": PARAMS["min_price_nok"],
                             "max_ret_1y": PARAMS["max_ret_1y"], "start_capital_nok": START_CAPITAL,
                             "edge_window_days": EDGE_WINDOW, "se_dividend_withholding": SE_DIVIDEND_TAX}
    results["monthly"] = [
        {"month_end": m.isoformat(), "net": net.returns[k], "gross": gross.returns[k],
         "index_blend": blend(net, idx_nok)[k], "ew_universe": ew_all[k], "se_share": net.mix[k]["SE"],
         "turnover": net.turnover[k], "held": net.held_log[k]}
        for k, m in enumerate(months)
    ]
    if attribution:
        results["changed_after_check"] = {"with_all_repairs": key_numbers(market, signals, scored),
                                          "without_one_repair": leave_one_out(dl, stocks, market, signals)}
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    from report import write_report  # noqa: PLC0415

    write_report(results, out_dir / "results.md")
    log.info("wrote %s", out_dir)
