"""Prices for the play-money crypto account (``crypto``): Firi's order books, and the coins' daily closes.

    GET https://api.firi.com/v2/markets/{market}/depth                      (BTCNOK, ETHNOK, XRPNOK, ADANOK, SOLNOK)
    GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d|1y&interval=1d   (BTC-USD, ...)

Firi is a Norwegian exchange that trades crypto against NOK, and the account trades there; its public API needs no
key (checked 5 October 2026). Every run stores each market's best bid and ask (``crypto_quotes``), the prices a
market order of the account's size gets: that day, 25 000 NOK filled at the best price in all five books. The raw
answers are not kept, as every 15 minutes they would fill the database, and after a week only the first complete
run of each hour is kept: the decisions, which are on the hour, keep the prices they were carried out at.

The trend rule needs 200 days of closes, which Firi does not have, so they come from Yahoo in USD (a day ends at
midnight UTC), through the Yahoo collector's parser, into ``price_bars``. Only days that are over are stored, so a
stored close is final; the day before is fetched once it is over, and a coin with too short a history gets a year.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, select

from .. import crypto
from ..http import FetchError
from ..store import UpsertResult, utcnow
from .base import Collector, RunSummary
from .yahoo import CHART_URL, parse_chart

FIRI = "https://api.firi.com/v2/markets/{market}/depth"
THIN_AFTER = timedelta(days=7)
THIN_WINDOW = timedelta(days=3)  # how far back each run looks for snapshots to thin
HISTORY = crypto.TREND_DAYS + 10  # closes a coin needs before the short refresh is enough
DAY = 86_400


class CryptoCollector(Collector):
    source = "krypto"

    def run(self, *, now: datetime | None = None) -> RunSummary:
        now = now or utcnow()
        self._quotes(now)
        self._closes(now)
        self._thin(now)
        return self.summary

    def _quotes(self, now: datetime) -> None:
        rows = []
        for coin in crypto.COINS:
            book = self._request(FIRI.format(market=coin.market))
            try:
                bid = max(float(price) for price, _ in book["bids"])
                ask = min(float(price) for price, _ in book["asks"])
            except (TypeError, KeyError, ValueError):  # no answer, or a side of the book empty
                self.warn(f"{coin.market}: ingen kurs fra Firi")
                continue
            if not 0 < bid < ask:
                self.warn(f"{coin.market}: kjøp {bid} og salg {ask} henger ikke sammen")
                continue
            rows.append({"market": coin.market, "at": now, "bid": bid, "ask": ask})
        if rows:
            q = self.store.table("crypto_quotes")
            with self.store.engine.begin() as conn:
                conn.execute(self.store._insert(q).on_conflict_do_nothing(index_elements=["market", "at"]), rows)
        self.summary.add("crypto_quotes", UpsertResult(inserted=len(rows)))

    def _closes(self, now: datetime) -> None:
        """Each coin's daily closes: the day before once it is over, and a year when the history is too short."""
        bars = self.store.table("price_bars")
        today = datetime.combine(now.astimezone(timezone.utc).date(), time(0), timezone.utc)
        yesterday = int(today.timestamp()) - DAY
        for coin in crypto.COINS:
            where = and_(bars.c.symbol == coin.yahoo, bars.c.interval == "1d")
            count = self.store.scalar(select(func.count()).select_from(bars).where(where))
            if count >= HISTORY and self.store.scalar(select(func.count()).select_from(bars)
                                                      .where(where, bars.c.ts == yesterday)):
                continue
            params = {"range": "5d" if count >= HISTORY else "1y", "interval": "1d"}
            try:
                resp, fetch_id = self.fetch("GET", CHART_URL.format(symbol=coin.yahoo), params=params)
                days, _, _ = parse_chart(resp.json())
            except (FetchError, ValueError, KeyError) as exc:
                self.warn(f"{coin.yahoo}: {exc}")
                continue
            self.save("price_bars", [b for b in days if b["ts"] + DAY <= now.timestamp()], fetch_id)

    def _thin(self, now: datetime) -> None:
        """Snapshots older than a week: only the first complete run of each hour stays (or the first run, if
        none got every market)."""
        q = self.store.table("crypto_quotes")
        until, since = now - THIN_AFTER, now - THIN_AFTER - THIN_WINDOW
        runs: dict[datetime, set[str]] = {}
        for r in self.store.query(select(q.c.market, q.c.at).where(q.c.at >= since, q.c.at < until)):
            runs.setdefault(_utc(r["at"]), set()).add(r["market"])
        markets = {c.market for c in crypto.COINS}
        keep: dict[datetime, datetime] = {}
        for at in sorted(runs, key=lambda at: (not markets <= runs[at], at)):  # complete runs first, then the earliest
            keep.setdefault(at.replace(minute=0, second=0, microsecond=0), at)
        drop = [at for at in runs if keep[at.replace(minute=0, second=0, microsecond=0)] != at]
        if drop:
            with self.store.engine.begin() as conn:
                for start in range(0, len(drop), 200):
                    conn.execute(delete(q).where(q.c.at.in_(drop[start:start + 200])))

    def _request(self, url: str) -> Any:
        """A JSON request that, unlike ``Collector.fetch``, is not kept in the raw layer."""
        try:
            resp = self.client.request("GET", url)
        except FetchError as exc:
            self.warn(str(exc))
            return None
        finally:
            self.summary.fetches += 1
        try:
            return json.loads(resp.body)
        except ValueError:
            return None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
