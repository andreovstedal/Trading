"""Downloads for B3, cached on disk so a second run needs no network.

* Yahoo's daily chart for each coin in USD (``period1``/``period2`` with ``interval=1d``: ``range=max`` returns
  monthly bars), kept as the raw JSON and parsed with the project's own parser (``collectors.yahoo.parse_chart``).
* Coin Metrics' community data for Bitcoin (github.com/coinmetrics/data, ``csv/btc.csv``), whose ``PriceUSD`` is
  the holdout's daily close (Coin Metrics' reference rate at 00:00 UTC the next day, the same convention as Yahoo's
  crypto day). The whole CSV is kept as downloaded.

A request that fails after the client's retries is not cached, so the next run tries again.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from nordic_signals.collectors.yahoo import CHART_URL, parse_chart
from nordic_signals.http import PoliteClient

log = logging.getLogger("b3.data")

YAHOO_HOSTS = {"query1.finance.yahoo.com": 1.0, "query2.finance.yahoo.com": 1.0}  # about one request a second
PERIOD1 = int(datetime(2010, 1, 1, tzinfo=timezone.utc).timestamp())
PERIOD2 = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())  # fixed, so the cache is the whole input
COINMETRICS_URL = "https://raw.githubusercontent.com/coinmetrics/data/master/csv/btc.csv"


class Downloader:
    def __init__(self, cache: Path, *, offline: bool = False):
        self.cache = cache
        self.offline = offline
        self.network_requests = 0
        self._client: PoliteClient | None = None

    @property
    def client(self) -> PoliteClient:
        if self._client is None:
            self._client = PoliteClient(min_interval=1.0, host_intervals=YAHOO_HOSTS, max_retries=5,
                                        backoff_base=5.0, max_backoff=120.0)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _cached(self, path: Path, fetch) -> bytes:
        if path.exists():
            return path.read_bytes()
        if self.offline:
            raise FileNotFoundError(f"{path} is not in the cache (offline run)")
        body = fetch()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return body

    def yahoo(self, symbol: str) -> list[dict]:
        """Yahoo's daily bars for ``symbol`` from 2010 to 7 October 2026 (the last day that is over)."""
        def fetch() -> bytes:
            self.network_requests += 1
            params = {"period1": PERIOD1, "period2": PERIOD2, "interval": "1d", "includePrePost": "false"}
            return self.client.get(CHART_URL.format(symbol=symbol), params=params).body

        body = self._cached(self.cache / "yahoo" / f"{symbol}.json", fetch)
        bars, _, _ = parse_chart(json.loads(body))
        if bars and bars[0]["interval"] != "1d":
            raise ValueError(f"{symbol}: Yahoo sent {bars[0]['interval']} bars, not daily")
        return bars

    def coinmetrics_btc(self) -> list[dict[str, str]]:
        def fetch() -> bytes:
            self.network_requests += 1
            return self.client.get(COINMETRICS_URL).body

        body = self._cached(self.cache / "coinmetrics" / "btc.csv", fetch)
        return list(csv.DictReader(io.StringIO(body.decode("utf-8"))))


def yahoo_closes(bars: list[dict], last: date) -> dict[date, float]:
    """A coin's daily closes by UTC day, up to ``last`` (a day that is over)."""
    out: dict[date, float] = {}
    for b in bars:
        day = datetime.fromtimestamp(b["ts"], timezone.utc).date()
        if day <= last and b["close"] and b["close"] > 0:
            out[day] = float(b["close"])
    return out


def fx_closes(bars: list[dict], last: date) -> dict[date, float]:
    """An FX rate's daily closes by London day: Yahoo stamps them at 00:00 London time (23:00 UTC in summer)."""
    out: dict[date, float] = {}
    for b in bars:
        day = datetime.fromtimestamp(b["ts"] + 3600, timezone.utc).date()
        if day <= last and b["close"] and b["close"] > 0:
            out[day] = float(b["close"])
    return out


def coinmetrics_closes(rows: list[dict[str, str]], first: date, last: date) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in rows:
        day = date.fromisoformat(r["time"][:10])
        price = r.get("PriceUSD") or ""
        if first <= day <= last and price:
            value = float(price)
            if value > 0:
                out[day] = value
    return out


def fill(closes: dict[date, float]) -> tuple[dict[date, float], list[date]]:
    """Every day from the first close to the last, a missing day carrying the close before it; and the days filled."""
    if not closes:
        return {}, []
    days = sorted(closes)
    out: dict[date, float] = {}
    filled: list[date] = []
    day, last = days[0], closes[days[0]]
    while day <= days[-1]:
        if day in closes:
            last = closes[day]
        else:
            filled.append(day)
        out[day] = last
        day += timedelta(days=1)
    return out, filled


def describe(closes: dict[date, float]) -> dict[str, Any]:
    days = sorted(closes)
    return {"first": days[0].isoformat(), "last": days[-1].isoformat(), "days": len(days)}
