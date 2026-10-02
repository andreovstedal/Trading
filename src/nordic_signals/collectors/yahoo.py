"""Yahoo Finance chart API: daily and intraday prices, dividends and splits.

    GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
        ?range=5d|1mo|1y|10y|max&interval=1m|5m|15m|1h|1d&events=div,splits

Verified live 2026-10-02 for .OL and .ST symbols without a cookie or crumb.
Intraday history is short (1-minute bars cover about a week, 5-minute to
hourly bars about 60 days), so archive intraday bars from day one if the
short-term sleeve will ever test intraday signals. Yahoo answers bursts with
HTTP 429; http.py spaces requests to this host 4 s apart. Its terms allow
personal use only, so never redistribute the data.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from .base import NORDIC_TZ, Collector, RunSummary

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

EXCHANGE_SUFFIX = {"NO": ".OL", "SE": ".ST", "DK": ".CO", "FI": ".HE"}


def yahoo_symbol(symbol: str, country: str) -> str:
    """Nordnet/exchange ticker to Yahoo's: "VOLV B" in SE -> "VOLV-B.ST"."""
    return symbol.strip().replace(" ", "-") + EXCHANGE_SUFFIX[country]


def parse_chart(payload: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    chart = payload["chart"]
    if chart.get("error") or not chart.get("result"):
        raise ValueError(f"Yahoo chart error: {chart.get('error')}")
    result = chart["result"][0]
    meta = result["meta"]
    symbol, currency, interval = meta["symbol"], meta.get("currency"), meta.get("dataGranularity")

    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    bars = []
    for i, ts in enumerate(result.get("timestamp") or []):
        close = _at(quote.get("close"), i)
        # Yahoo pads gaps with nulls, and on long ranges sends the newest day with
        # null prices until it is final; shorter ranges fill it in on later runs.
        if close is None:
            continue
        bars.append({
            "symbol": symbol,
            "interval": interval,
            "ts": ts,
            "ts_utc": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "currency": currency,
            "open": _at(quote.get("open"), i),
            "high": _at(quote.get("high"), i),
            "low": _at(quote.get("low"), i),
            "close": close,
            "adjclose": _at(adjclose, i),
            "volume": _at(quote.get("volume"), i),
        })

    events = result.get("events") or {}
    dividends = [
        {"symbol": symbol, "ts": int(d["date"]), "ex_date": _local_date(d["date"]),
         "amount": d.get("amount"), "currency": currency}
        for d in (events.get("dividends") or {}).values()
    ]
    splits = [
        {"symbol": symbol, "ts": int(s["date"]), "ex_date": _local_date(s["date"]),
         "numerator": s.get("numerator"), "denominator": s.get("denominator")}
        for s in (events.get("splits") or {}).values()
    ]
    return bars, dividends, splits


def _at(values: list | None, i: int) -> Any:
    return values[i] if values is not None and i < len(values) else None


def _local_date(ts: int | float) -> str:
    return datetime.fromtimestamp(ts, tz=NORDIC_TZ).date().isoformat()


class YahooCollector(Collector):
    source = "yahoo"

    def run(self, *, symbols: Iterable[str], range_: str = "5d", interval: str = "1d") -> RunSummary:
        params = {"range": range_, "interval": interval, "events": "div,splits", "includePrePost": "false"}
        for symbol in symbols:
            resp, fetch_id = self.fetch("GET", CHART_URL.format(symbol=symbol), params=params)
            try:
                bars, dividends, splits = parse_chart(resp.json())
            except ValueError as exc:
                self.warn(f"{symbol}: {exc}")
                continue
            self.save("price_bars", bars, fetch_id)
            self.save("dividends", dividends, fetch_id)
            self.save("splits", splits, fetch_id)
        return self.summary


def universe_symbols(store, countries: Iterable[str], limit: int | None = None) -> list[str]:
    """Yahoo symbols for tradable shares in the stored Nordnet universe."""
    countries = list(countries)
    sql = (
        "SELECT symbol, exchange_country FROM instruments WHERE is_tradable = 1"
        f" AND exchange_country IN ({', '.join('?' * len(countries))}) ORDER BY instrument_id"
    )
    rows = store.conn.execute(sql, countries).fetchall()
    symbols = [yahoo_symbol(r["symbol"], r["exchange_country"]) for r in rows if r["symbol"]]
    return symbols[:limit] if limit else symbols
