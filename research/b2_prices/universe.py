"""Today's Nordnet universe for B2, and the Yahoo series behind it, as plain per-day lists."""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from nordic_signals.collectors.base import NORDIC_TZ
from nordic_signals.collectors.yahoo import yahoo_symbol

COUNTRIES = ("NO", "SE")
CURRENCIES = {"NO": "NOK", "SE": "SEK"}  # scoring.py excludes a stock with no NOK rate: only NOK and SEK have one
LARGE_DIVIDEND = 0.2  # of the previous close
# Yahoo's ex-dates for Oslo dividends in this window are one trading day late: the price falls on the day before
# Yahoo's date (measured in results.json, universe.oslo_dividend_drop_by_year). Before 2021, after June 2024 and in
# Stockholm Yahoo's date is right.
OSLO_LATE_EX_DATES = (date(2021, 1, 1), date(2024, 6, 30))


@dataclass
class Series:
    """A Yahoo daily series by local trading date. ``tr_*`` are total-return levels (dividends reinvested)."""

    symbol: str
    currency: str | None
    days: list[date] = field(default_factory=list)
    open: list[float | None] = field(default_factory=list)
    high: list[float | None] = field(default_factory=list)
    low: list[float | None] = field(default_factory=list)
    close: list[float] = field(default_factory=list)
    adjclose: list[float | None] = field(default_factory=list)
    volume: list[float | None] = field(default_factory=list)
    dividends: dict[date, float] = field(default_factory=dict)
    splits: list[tuple[date, float]] = field(default_factory=list)  # (ex-date, numerator / denominator)
    bad_opens: int = 0
    dividends_moved: int = 0
    spikes: int = 0
    bad_dividends: int = 0
    large_dividends_kept: int = 0

    def index_on_or_before(self, day: date) -> int | None:
        i = bisect.bisect_right(self.days, day) - 1
        return i if i >= 0 else None

    def index_after(self, day: date) -> int | None:
        i = bisect.bisect_right(self.days, day)
        return i if i < len(self.days) else None

    def split_factor(self, day: date) -> float:
        """Yahoo's prices are adjusted for every later split; × this gives the price quoted on ``day``."""
        return math.prod(r for d, r in self.splits if d > day)

    def total_return(self, withholding: float = 0.0) -> tuple[list[float], list[float]]:
        """Total-return levels at each open and close: dividends (Yahoo's ex-date amounts) paid at the ex-date's
        open, net of ``withholding``. Yahoo's close and dividends are split-adjusted, not dividend-adjusted."""
        tr_open, tr_close = [], []
        level = 1.0
        for i, day in enumerate(self.days):
            if i == 0:
                tr_open.append(level * (self.open[i] or self.close[i]) / self.close[i])
                tr_close.append(level)
                continue
            prev = self.close[i - 1]
            div = self.dividends.get(day, 0.0) * (1 - withholding)
            opening = self.open[i] or prev
            tr_open.append(level * (opening + div) / prev)
            level *= (self.close[i] + div) / prev
            tr_close.append(level)
        return tr_open, tr_close


def build_series(symbol: str, bars: list[dict], dividends: list[dict], splits: list[dict] = (), spike: float = 0.4,
                 late_ex_dates: tuple[date, date] | None = None) -> Series:
    """``late_ex_dates``: a window in which Yahoo's ex-dates are a trading day late (Oslo, OSLO_LATE_EX_DATES)."""
    s = Series(symbol=symbol, currency=bars[0]["currency"] if bars else None)
    seen: dict[date, int] = {}
    for bar in sorted(bars, key=lambda b: b["ts"]):
        close = bar["close"]
        if close is None or close <= 0:
            continue
        day = datetime.fromtimestamp(bar["ts"], NORDIC_TZ).date()
        if day in seen:  # Yahoo sometimes repeats the last day; the later bar wins
            i = seen[day]
            s.open[i], s.high[i], s.low[i], s.close[i] = bar["open"], bar["high"], bar["low"], close
            s.adjclose[i], s.volume[i] = bar["adjclose"], bar["volume"]
            continue
        opening = bar["open"]
        hi, lo = bar["high"], bar["low"]
        # An opening outside the day's range, or missing, is a bad print: the account would then fill at the
        # previous close, which is what ``total_return`` uses for a None.
        if opening is None or opening <= 0 or (hi and lo and not (lo * 0.999 <= opening <= hi * 1.001)):
            opening = None
            s.bad_opens += 1
        seen[day] = len(s.days)
        s.days.append(day)
        s.open.append(opening)
        s.high.append(hi if hi and hi > 0 else None)
        s.low.append(lo if lo and lo > 0 else None)
        s.close.append(close)
        s.adjclose.append(bar["adjclose"] if bar["adjclose"] and bar["adjclose"] > 0 else None)
        s.volume.append(bar["volume"])
    _despike(s, spike)
    s.splits = sorted((date.fromisoformat(x["ex_date"]), x["numerator"] / x["denominator"])
                      for x in splits if x.get("numerator") and x.get("denominator"))
    for d in dividends:
        if d.get("amount"):
            day = date.fromisoformat(d["ex_date"])
            if late_ex_dates and late_ex_dates[0] <= day <= late_ex_dates[1]:
                day = _true_ex_date(s, day, d["amount"])
            s.dividends[day] = s.dividends.get(day, 0.0) + d["amount"]
    # A dividend above 20 % of the price counts only if the price fell by at least half of it at the ex-date
    # opening or close: Yahoo has some that were never split-adjusted, or in the wrong unit. Others, such as
    # liquidation payouts, are real and kept.
    for day in list(s.dividends):
        i = s.index_on_or_before(day - timedelta(days=1))
        k = s.index_after(day - timedelta(days=1))
        if i is None or k is None:
            del s.dividends[day]
            continue
        amount, prev = s.dividends[day], s.close[i]
        if amount > LARGE_DIVIDEND * prev:
            if _drop(s, k) < 0.5 * amount:
                del s.dividends[day]
                s.bad_dividends += 1
            else:
                s.large_dividends_kept += 1
    return s


def _drop(s: Series, k: int) -> float:
    """The fall from the previous close to the lower of day ``k``'s opening and close."""
    return s.close[k - 1] - min(s.open[k] or s.close[k], s.close[k]) if k >= 1 else 0.0


def _true_ex_date(s: Series, day: date, amount: float) -> date:
    """The trading day before Yahoo's (late) ex-date. A dividend over 20 % of the price, whose drop is beyond doubt,
    stays on Yahoo's day if the price fell there rather than the day before."""
    k = s.index_after(day - timedelta(days=1))  # Yahoo's day, or the next trading day
    if k is None or k < 1:
        return day
    if amount > LARGE_DIVIDEND * s.close[k - 1] and _drop(s, k) > _drop(s, k - 1):
        return day
    s.dividends_moved += 1
    return s.days[k - 1]


@dataclass
class Stock:
    instrument_id: int
    issuer_id: int | None
    symbol: str
    yahoo: str
    name: str
    country: str
    currency: str | None
    instrument_type: str | None
    segments: list[str]


def nordnet_universe(instruments: list[dict]) -> tuple[list[Stock], dict[str, int]]:
    """Shares on today's list (ESH and ESHMTF, as ``features._load_universe``), with counts of what was dropped."""
    out: list[Stock] = []
    dropped: dict[str, int] = {}
    seen: set[int] = set()
    for r in instruments:
        if r["instrument_id"] in seen:
            continue
        seen.add(r["instrument_id"])
        country = r["exchange_country"]
        if r["instrument_type"] not in ("ESH", "ESHMTF"):
            dropped["not a share (ESH/ESHMTF)"] = dropped.get("not a share (ESH/ESHMTF)", 0) + 1
            continue
        if not r["symbol"] or country not in COUNTRIES:
            dropped["no symbol"] = dropped.get("no symbol", 0) + 1
            continue
        if r["currency"] != CURRENCIES[country]:
            key = "quoted in another currency (no NOK rate in scoring.py)"
            dropped[key] = dropped.get(key, 0) + 1
            continue
        out.append(Stock(r["instrument_id"], r["issuer_id"], r["symbol"], yahoo_symbol(r["symbol"], country),
                         r["name"], country, r["currency"], r["instrument_type"], list(r["exchanges"] or [])))
    return out, dropped


def _despike(s: Series, threshold: float) -> None:
    """A one-day print far from both neighbours (by more than ``threshold`` either way), which agree with each
    other within 25 %, is a bad tick (Yahoo has some, such as Borr at 29.76 between 14.84 and 14.99): its close
    becomes the neighbours' geometric mean and its opening, high and low are dropped."""
    c = s.close
    for i in range(1, len(c) - 1):
        a, b, d = c[i - 1], c[i], c[i + 1]
        up = b / a > 1 + threshold and b / d > 1 + threshold
        down = a / b > 1 + threshold and d / b > 1 + threshold
        if (up or down) and 0.8 < d / a < 1.25:
            fixed = (a * d) ** 0.5
            if s.adjclose[i]:
                s.adjclose[i] *= fixed / b
            c[i] = fixed
            s.open[i] = s.high[i] = s.low[i] = None
            s.spikes += 1
