"""Cached, polite downloads for B1.

Every response is written under the cache directory with a deterministic name, so a second run reads the files
and makes no requests. The project's PoliteClient spaces requests per host and retries 429/5xx with backoff.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from nordic_signals.http import FetchError, PoliteClient

NEWSWEB = "https://api3.oslo.oslobors.no/v1/newsreader"
FI_EXPORT = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"
NORDNET = "https://www.nordnet.no/api/2/instrument_search/query/stocklist"

HOST_INTERVALS = {  # seconds between requests to one host
    "query1.finance.yahoo.com": 1.1,
    "query2.finance.yahoo.com": 2.5,  # the search answers 429 at about one request a second
    "api3.oslo.oslobors.no": 1.0,
    "marknadssok.fi.se": 1.0,
    "www.nordnet.no": 2.0,
}


class OfflineMiss(RuntimeError):
    """A file the run needs is not in the cache and --offline was given."""


class Cache:
    def __init__(self, root: Path, offline: bool = False):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.requests = 0
        self._client: PoliteClient | None = None

    def client(self) -> PoliteClient:
        if self._client is None:
            self._client = PoliteClient(host_intervals=HOST_INTERVALS, max_retries=8, backoff_base=10.0,
                                        max_backoff=180.0)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def get(self, rel: str, method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
            missing_ok: tuple[int, ...] = ()) -> bytes | None:
        """The response body, from the cache when present. ``None`` (cached as a .missing file) for a status in
        ``missing_ok``, such as Yahoo's 404 for a symbol it no longer has."""
        path = self.root / rel
        marker = path.with_name(path.name + ".missing")
        if path.exists():
            return path.read_bytes()
        if marker.exists():
            return None
        if self.offline:
            raise OfflineMiss(rel)
        self.requests += 1
        try:
            resp = self.client().request(method, url, params=params, headers=headers, allow_status=missing_ok)
        except FetchError as exc:
            if exc.response is not None and exc.response.status in missing_ok:
                resp = exc.response
            else:
                raise
        path.parent.mkdir(parents=True, exist_ok=True)
        if resp.status in missing_ok:
            marker.write_text(f"HTTP {resp.status}\n{resp.body[:500].decode('utf-8', 'replace')}")
            return None
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(resp.body)
        os.replace(tmp, path)
        return resp.body

    def get_json(self, rel: str, method: str, url: str, **kwargs: Any) -> Any:
        body = self.get(rel, method, url, **kwargs)
        return None if body is None else json.loads(body)


# NewsWeb

def newsweb_list(cache: Cache, category: int, start: date, end: date, warnings: list[str]) -> list[dict]:
    """Raw messages of one category from ``start`` to ``end`` (Oslo dates), split in halves while the API
    reports overflow (about 600 messages a response)."""
    from nordic_signals.collectors.newsweb import parse_list

    rel = f"newsweb/{category}/{start.isoformat()}_{end.isoformat()}.json"
    params = {"fromDate": start.isoformat(), "toDate": end.isoformat(), "category": category}
    payload = cache.get_json(rel, "GET", f"{NEWSWEB}/list", params=params)
    rows, overflow = parse_list(payload)
    if not overflow:
        return rows
    if start == end:
        warnings.append(f"NewsWeb category {category} overflows on {start}; some messages are missing")
        return rows
    middle = start + (end - start) // 2
    return (newsweb_list(cache, category, start, middle, warnings)
            + newsweb_list(cache, category, middle + timedelta(days=1), end, warnings))


def newsweb_range(cache: Cache, category: int, start: date, end: date, warnings: list[str]) -> list[dict]:
    """Month by month, de-duplicated by message id."""
    out: dict[int, dict] = {}
    chunk_start = start
    while chunk_start <= end:
        nxt = (chunk_start.replace(day=1) + timedelta(days=32)).replace(day=1)
        chunk_end = min(end, nxt - timedelta(days=1))
        for row in newsweb_list(cache, category, chunk_start, chunk_end, warnings):
            out[row["message_id"]] = row
        chunk_start = chunk_end + timedelta(days=1)
    return sorted(out.values(), key=lambda r: (r["published_at"] or "", r["message_id"]))


def newsweb_body(cache: Cache, message_id: int) -> str | None:
    payload = cache.get_json(f"newsweb/bodies/{message_id}.json", "GET", f"{NEWSWEB}/message",
                             params={"messageId": message_id}, missing_ok=(404,))
    if payload is None:
        return None
    data = payload.get("data") or {}
    message = data.get("message", data)
    return message.get("body")


# Finansinspektionen

def fi_window(cache: Cache, start: date, end: date, warnings: list[str]) -> list[dict]:
    """FI's insider export for publication dates ``start``..``end``, split in halves at the 1,000-row cap."""
    from nordic_signals.collectors.fi_insider import ROW_CAP, parse_export

    rel = f"fi/{start.isoformat()}_{end.isoformat()}.csv"
    params = {"SearchFunctionType": "Insyn", "Publiceringsdatum.From": start.isoformat(),
              "Publiceringsdatum.To": end.isoformat(), "button": "export"}
    rows = parse_export(cache.get(rel, "GET", FI_EXPORT, params=params))
    if len(rows) < ROW_CAP:
        return rows
    if start == end:
        warnings.append(f"FI export hits the {ROW_CAP}-row cap on {start}; some rows may be missing")
        return rows
    middle = start + (end - start) // 2
    return fi_window(cache, start, middle, warnings) + fi_window(cache, middle + timedelta(days=1), end, warnings)


def fi_range(cache: Cache, start: date, end: date, warnings: list[str]) -> list[dict]:
    """Two weeks at a time, de-duplicated by the parser's row hash."""
    out: dict[str, dict] = {}
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=13))
        for row in fi_window(cache, chunk_start, chunk_end, warnings):
            out[row["row_hash"]] = row
        chunk_start = chunk_end + timedelta(days=1)
    return list(out.values())


# Yahoo and Nordnet

def yahoo_chart(cache: Cache, symbol: str, period1: int, period2: int) -> dict | None:
    params = {"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits",
              "includePrePost": "false"}
    safe = symbol.replace("^", "_idx_").replace("=", "_eq_")
    return cache.get_json(f"yahoo/chart/{safe}.json", "GET", YAHOO_CHART.format(symbol=symbol), params=params,
                          missing_ok=(404, 400))


def yahoo_search(cache: Cache, query: str) -> list[dict]:
    # Punctuation such as "ser. B" makes Yahoo's edge answer 429 every time, so search on words only.
    query = " ".join("".join(c if c.isalnum() else " " for c in query).split())
    safe = query.replace(" ", "_")[:80]
    payload = cache.get_json(f"yahoo/search/{safe}.json", "GET", YAHOO_SEARCH,
                             params={"q": query, "quotesCount": 6, "newsCount": 0}, missing_ok=(404, 400))
    return (payload or {}).get("quotes") or []


def nordnet_list(cache: Cache, country: str) -> list[dict]:
    """Nordnet's current stock list for one country: (isin, symbol, name) of today's listings."""
    from nordic_signals.collectors.nordnet import parse_stocklist

    out: list[dict] = []
    offset, total = 0, None
    while total is None or offset < total:
        payload = cache.get_json(f"nordnet/{country}_{offset}.json", "GET", NORDNET,
                                 params={"apply_filters": f"exchange_country={country}", "limit": 100,
                                         "offset": offset},
                                 headers={"client-id": "NEXT", "Accept": "application/json"})
        total = payload.get("total_hits", 0)
        instruments, _ = parse_stocklist(payload, "2026-10-08T00:00:00Z")
        out.extend(instruments)
        if not payload.get("results"):
            break
        offset += 100
    return out
