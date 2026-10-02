"""Polite HTTP client shared by all collectors.

Every request goes through one client so we can enforce a minimum delay per
host, retry transient failures with backoff, and send one identifiable
User-Agent. The collectors read public data at low frequency for personal
research, so the delays are deliberately conservative.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; nordic-signals/0.1; personal research)"

# Seconds between requests to the same host. Yahoo answers bursts with HTTP 429,
# so it gets a longer gap than the regulators and exchanges.
DEFAULT_HOST_INTERVALS = {
    "query1.finance.yahoo.com": 4.0,
    "query2.finance.yahoo.com": 4.0,
}

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchedResponse:
    method: str
    url: str
    status: int
    content_type: str
    body: bytes
    fetched_at: datetime

    def json(self) -> Any:
        return json.loads(self.body)


class FetchError(RuntimeError):
    """A request that still failed after all retries."""

    def __init__(self, message: str, response: FetchedResponse | None = None):
        super().__init__(message)
        self.response = response


class PoliteClient:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float = 1.0,
        host_intervals: Mapping[str, float] | None = None,
        max_retries: int = 3,
        backoff_base: float = 5.0,
        max_backoff: float = 120.0,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._min_interval = min_interval
        self._host_intervals = {**DEFAULT_HOST_INTERVALS, **(host_intervals or {})}
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._sleep = sleep
        self._clock = clock
        self._last_request: dict[str, float] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str, **kwargs: Any) -> FetchedResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FetchedResponse:
        return self.request("POST", url, **kwargs)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        data: Any = None,
        allow_status: Collection[int] = (),
    ) -> FetchedResponse:
        """Send a request; raise FetchError for HTTP errors not in ``allow_status``."""
        host = urlsplit(url).hostname or ""
        for attempt in range(self._max_retries + 1):
            self._wait_for(host)
            try:
                r = self._client.request(method, url, params=params, headers=headers, data=data)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise FetchError(f"{method} {url}: {exc}") from exc
                delay = self._backoff(attempt, None)
                log.warning("%s %s failed (%s); retrying in %.0fs", method, url, exc, delay)
                self._sleep(delay)
                continue

            resp = FetchedResponse(
                method=method,
                url=str(r.url),
                status=r.status_code,
                content_type=r.headers.get("content-type", ""),
                body=r.content,
                fetched_at=datetime.now(timezone.utc),
            )
            if r.status_code in RETRY_STATUSES and attempt < self._max_retries:
                delay = self._backoff(attempt, r.headers.get("retry-after"))
                log.warning("%s %s -> HTTP %s; retrying in %.0fs", method, resp.url, r.status_code, delay)
                self._sleep(delay)
                continue
            if r.status_code >= 400 and r.status_code not in allow_status:
                raise FetchError(f"{method} {resp.url} -> HTTP {r.status_code}", resp)
            return resp
        raise AssertionError("unreachable")

    def _wait_for(self, host: str) -> None:
        interval = self._host_intervals.get(host, self._min_interval)
        last = self._last_request.get(host)
        if last is not None:
            remaining = interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self._max_backoff)
            except ValueError:
                try:
                    when = parsedate_to_datetime(retry_after)
                    wait = (when - datetime.now(timezone.utc)).total_seconds()
                    return min(max(wait, 0.0), self._max_backoff)
                except (TypeError, ValueError):
                    pass
        return min(self._backoff_base * 2**attempt, self._max_backoff)
