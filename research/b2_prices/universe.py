"""Today's Nordnet universe for B2, and the Yahoo series behind it, as plain per-day lists."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from nordic_signals.collectors.base import NORDIC_TZ
from nordic_signals.collectors.yahoo import yahoo_symbol

COUNTRIES = ("NO", "SE")
CURRENCIES = {"NO": "NOK", "SE": "SEK"}  # scoring.py excludes a stock with no NOK rate: only NOK and SEK have one
LARGE_DIVIDEND = 0.2  # of the previous close


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
    bad_opens: int = 0
    bad_dividends: int = 0
    large_dividends_kept: int = 0

    def index_on_or_before(self, day: date) -> int | None:
        i = bisect.bisect_right(self.days, day) - 1
        return i if i >= 0 else None

    def index_after(self, day: date) -> int | None:
        i = bisect.bisect_right(self.days, day)
        return i if i < len(self.days) else None

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


def build_series(symbol: str, bars: list[dict], dividends: list[dict]) -> Series:
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
    for d in dividends:
        if d.get("amount"):
            day = date.fromisoformat(d["ex_date"])
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
            low = min(s.open[k] or s.close[k], s.close[k])
            if prev - low < 0.5 * amount:
                del s.dividends[day]
                s.bad_dividends += 1
            else:
                s.large_dividends_kept += 1
    return s


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
