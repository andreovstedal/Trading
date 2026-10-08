"""Downloads for B2, cached on disk so a second run needs no network.

Every response is kept as the raw JSON the endpoint returned, keyed by what was asked, and parsed with the
project's own parsers (``collectors.nordnet.parse_stocklist``, ``collectors.yahoo.parse_chart``). A symbol
Yahoo does not have is cached as such (``{"missing": status}``), so it is not asked for again; a request that
failed for other reasons (network, repeated 429s) is not cached and is retried on the next run.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nordic_signals.collectors import nordnet
from nordic_signals.collectors.yahoo import CHART_URL, parse_chart
from nordic_signals.http import FetchError, PoliteClient

log = logging.getLogger("b2.data")

YAHOO_HOSTS = {"query1.finance.yahoo.com": 1.0, "query2.finance.yahoo.com": 1.0}  # about one request a second
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
PERIOD1 = int(datetime(2012, 1, 1, tzinfo=timezone.utc).timestamp())
PERIOD2 = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())  # fixed, so the cache is the whole input


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._=-]", "_", name)


class Downloader:
    def __init__(self, cache: Path, *, offline: bool = False):
        self.cache = cache
        self.offline = offline
        self.network_requests = 0
        self._client: PoliteClient | None = None

    @property
    def client(self) -> PoliteClient:
        if self._client is None:
            self._client = PoliteClient(min_interval=2.0, host_intervals=YAHOO_HOSTS, max_retries=5,
                                        backoff_base=5.0, max_backoff=120.0)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _cached(self, path: Path, fetch) -> Any:
        if path.exists():
            return json.loads(path.read_text())
        if self.offline:
            return None
        payload = fetch()
        if payload is None:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(path)
        return payload

    # Nordnet's stock list: today's universe

    def nordnet(self, country: str, page_size: int = 100) -> tuple[list[dict], list[dict]]:
        instruments: list[dict] = []
        observations: list[dict] = []
        offset, total = 0, None
        while total is None or offset < total:
            path = self.cache / "nordnet" / f"{country}_{offset}.json"

            def fetch(offset: int = offset) -> Any:
                self.network_requests += 1
                params = {"apply_filters": f"exchange_country={country}", "limit": page_size, "offset": offset}
                resp = self.client.get(nordnet.URL, params=params, headers=nordnet.HEADERS)
                return {"fetched_at": resp.fetched_at.isoformat(), "payload": resp.json()}

            doc = self._cached(path, fetch)
            if doc is None:
                raise RuntimeError(f"Nordnet {country} offset {offset} not in the cache (offline run)")
            payload = doc["payload"]
            total = payload.get("total_hits", 0)
            ins, obs = nordnet.parse_stocklist(payload, doc["fetched_at"])
            instruments += ins
            observations += obs
            if not payload.get("results"):
                break
            offset += page_size
        return instruments, observations

    # Yahoo daily bars

    def yahoo_daily(self, symbol: str) -> tuple[list[dict], list[dict], list[dict]] | None:
        """(bars, dividends, splits) from 2012-01-01 to 2026-10-07, or None if Yahoo has no such symbol."""
        path = self.cache / "yahoo" / f"{_safe(symbol)}.json"

        def fetch() -> Any:
            self.network_requests += 1
            params = {"period1": PERIOD1, "period2": PERIOD2, "interval": "1d", "events": "div,splits",
                      "includePrePost": "false"}
            try:
                resp = self.client.get(CHART_URL.format(symbol=symbol), params=params, allow_status=(400, 404))
            except FetchError as exc:  # not cached: tried again on the next run
                log.warning("%s: %s", symbol, exc)
                return None
            if resp.status in (400, 404):
                return {"missing": resp.status, "body": resp.body.decode("utf-8", "replace")[:500]}
            return resp.json()

        payload = self._cached(path, fetch)
        if payload is None or "missing" in payload:
            return None
        try:
            return parse_chart(payload)
        except ValueError:
            return None

    def yahoo_status(self, symbol: str) -> str:
        path = self.cache / "yahoo" / f"{_safe(symbol)}.json"
        if not path.exists():
            return "not fetched"
        payload = json.loads(path.read_text())
        return f"missing (HTTP {payload['missing']})" if "missing" in payload else "ok"

    # Yahoo's sector, from its search endpoint (exploratory: Nordnet's list has no sectors)

    def yahoo_sector(self, symbol: str) -> str | None:
        path = self.cache / "sector" / f"{_safe(symbol)}.json"

        def fetch() -> Any:
            self.network_requests += 1
            params = {"q": symbol, "quotesCount": 5, "newsCount": 0, "listsCount": 0}
            try:
                resp = self.client.get(SEARCH_URL, params=params)
            except FetchError as exc:
                log.warning("search %s: %s", symbol, exc)
                return None
            return resp.json()

        payload = self._cached(path, fetch)
        if not payload:
            return None
        for quote in payload.get("quotes") or []:
            if quote.get("symbol") == symbol:
                return quote.get("sector") or None
        return None
