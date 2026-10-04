"""pump.fun launches for the pump-and-dump measurement in ``nordic_signals.pumpfun``. Nothing here trades.

Each run (every 5 minutes on Railway):

1. **Discover.** pump.fun's list of the newest tokens:
   ``GET https://frontend-api-v3.pump.fun/coins?sort=created_timestamp&order=DESC&limit=50``, the unofficial
   API behind pump.fun. It serves only the newest tokens (about a minute and a half of launches) and
   rate-limits bursts. Every token is stored, so creators who launch token after token can be recognised;
   all new ones are scored (``sample`` can limit that to a random sample).
2. **Score** each sampled token once it is 10 minutes old:

   * price, trades and graduation from DexScreener,
     ``GET https://api.dexscreener.com/tokens/v1/solana/{mint,mint,...}`` (documented; up to 30 tokens per
     request and 300 requests a minute);
   * the creator wallet's last 200 transactions from Solana JSON-RPC ``getSignaturesForAddress``: how old
     the wallet is, or how busy;
   * holder concentration from ``getTokenLargestAccounts``, only when SOLANA_RPC_URL points at a private
     RPC node (Helius, QuickNode, ...), because the public node refuses that call with HTTP 429.
3. **Follow** the price of each measured token (tradable and fully checked, see ``pumpfun.tradable``;
   the rest are left as "scored") on DexScreener every run for the first 6 hours after scoring, then every 30
   minutes, recording it (and the peak so far) 1, 6 and 24 hours after scoring. At 24 hours the token is
   done and labelled. Every price seen for a token that passed also goes into ``pf_prices``, for the charts.
4. **Record** the fake-money portfolio's value (``pumpfun.snapshot``).

Between runs, ``PumpFunCollector.quote`` (every minute on Railway) fetches the open fake-money positions'
prices from DexScreener, so the page moves while it is open. Those quotes only feed the charts, the
positions' current value and the exit rules; the measurement keeps to the checks above, so its numbers do
not depend on how often anyone looks.

The exit rules need the first price seen beyond their line within 24 hours of scoring: at or below half the
scoring price for the stup rule (``cliff_at``, ``cliff_price``), at or above the take-profit line for the
main account (``profit_at``, ``profit_price``). The follow step records them for every measured token and
the quotes for the open positions. Tokens followed before a rule was recorded get it from their price
history (``_backfill_exits``).

Hype at scoring: the social links the creator added at launch (pump.fun's own fields) and paid promotion on
DexScreener (a token profile, boosts). X and Telegram cannot be read without paid access or breaking their
terms, and pump.fun's comment threads are no longer served.

A token whose wallet (or, with a private node, holder) lookup failed is scored as incomplete and left out
of the results, so an outage cannot let tokens pass unchecked. A DexScreener request that fails counts
against no token; only a token DexScreener does not list is counted as missing.

Checked live on 2026-10-02. pump.fun's older per-token, trades and candle endpoints are gone and its
search does not match token addresses, so DexScreener is the only price source after discovery.

Unlike the other collectors, responses are not kept in the raw layer: at this frequency they would add
gigabytes a year, and ``pf_tokens`` holds everything the measurement uses.
"""

from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update

from .. import pumpfun
from ..http import FetchError
from ..store import UpsertResult, utcnow
from .base import Collector, RunSummary

API = "https://frontend-api-v3.pump.fun"
DEXSCREENER = "https://api.dexscreener.com/tokens/v1/solana"
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
SUPPLY = 1e9  # every pump.fun token has a billion

SCORE_AGE = timedelta(minutes=10)
FAST_PHASE = timedelta(hours=6)
SLOW_INTERVAL = timedelta(minutes=29)  # every 30 minutes, with slack for run times
HORIZON = timedelta(hours=24)
CHECKPOINTS = (("price_1h", timedelta(hours=1)), ("price_6h", timedelta(hours=6)), ("price_24h", HORIZON))
PEAK_AT = {"price_1h": "peak_1h", "price_6h": "peak_6h"}  # at 24 hours the peak is peak_after
MISSING_BEFORE_SCORING = 3  # runs without a DexScreener pair before a new token is given up
MISSING_AFTER_SCORING = 12
SERIAL_WINDOW = timedelta(hours=24)
KEEP_SKIPPED = timedelta(days=7)
PRICE_HISTORY = timedelta(days=7)  # pf_prices; the checkpoint prices in pf_tokens are kept for good
DEX_BATCH = 30
SIGNATURE_LIMIT = 200  # enough to see a new wallet's first transaction, or a busy wallet's pace
LAUNCH_FIELDS = ("market_cap", "usd_market_cap", "ath_market_cap", "complete", "reply_count", "real_sol_reserves",
                 "bonding_curve", "associated_bonding_curve", "pool_address", "program", "nsfw", "is_banned",
                 "twitter", "telegram", "website")


class PumpFunCollector(Collector):
    source = "pumpfun"

    def run(self, *, sample: int = 50, now: datetime | None = None,
            rng: random.Random | None = None) -> RunSummary:
        now = now or utcnow()
        self.rpc_url = os.environ.get("SOLANA_RPC_URL") or PUBLIC_RPC
        self.private_rpc = self.rpc_url != PUBLIC_RPC
        self._warned: set[str] = set()
        self._discover(now, sample, rng or random.Random())
        self._score(now)
        self._follow(now)
        self._backfill_exits(now)
        self._prune(now)
        pumpfun.snapshot(self.store, now)  # the fake-money portfolio's value, for the chart
        return self.summary

    # 1. Discover

    def _discover(self, now: datetime, sample: int, rng: random.Random) -> None:
        params = {"offset": 0, "limit": 50, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "true"}
        coins = [c for c in self._request("GET", f"{API}/coins", params=params) or []
                 if c.get("mint") and c.get("created_timestamp")
                 and str(c.get("chain_id", "solana")).startswith("solana")]
        t = self._table()
        known = {r["mint"] for r in self.store.query(select(t.c.mint).where(t.c.mint.in_([c["mint"] for c in coins])))}
        fresh = [c for c in coins if c["mint"] not in known]
        chosen = set(rng.sample(sorted(c["mint"] for c in fresh), min(sample, len(fresh))))
        rows = [{
            "mint": c["mint"], "name": c.get("name"), "symbol": c.get("symbol"), "creator": c.get("creator"),
            "created_at": datetime.fromtimestamp(c["created_timestamp"] / 1000, timezone.utc),
            "discovered_at": now, "sampled": c["mint"] in chosen, "status": "new" if c["mint"] in chosen else "skipped",
            "launch": {k: c[k] for k in LAUNCH_FIELDS if c.get(k) is not None}, "peak_before": _ath_price(c),
            "misses": 0,
        } for c in fresh]
        if rows:
            with self.store.engine.begin() as conn:
                conn.execute(self.store._insert(t).on_conflict_do_nothing(index_elements=["mint"]), rows)
        self.summary.add("pf_tokens", UpsertResult(inserted=len(rows)))

    # 2. Score

    def _score(self, now: datetime) -> None:
        t = self._table()
        due = [dict(r) for r in self.store.query(
            select(t).where(t.c.status == "new", t.c.created_at <= now - SCORE_AGE))]
        pairs, unchecked = self._pairs([r["mint"] for r in due])
        prices = []
        for r in due:
            pair = pairs.get(r["mint"])
            if pair is None:
                if r["mint"] not in unchecked:
                    misses = r["misses"] + 1
                    status = "missing" if misses >= MISSING_BEFORE_SCORING else "new"
                    self._update(r["mint"], misses=misses, status=status)
                continue
            features = self._features(r, pair, now)
            signs = pumpfun.warning_signs(features)
            active = pumpfun.tradable(features)
            price = features["price"]
            passed = active and features["complete"] and not signs
            measured = active and features["complete"]  # only these are followed: nothing else is measured
            self._update(r["mint"], status="tracking" if measured else "scored", scored_at=now,
                         screen_version=pumpfun.SCREEN_VERSION,
                         features=features, warnings=signs, active=active, complete=features["complete"],
                         passed=passed, price_t=price, peak_after=price, low_after=price, last_price=price,
                         last_checked_at=now, graduated=features["graduated"])
            if passed:
                prices.append({"mint": r["mint"], "at": now, "price": price})
        self._record_prices(prices)
        self.summary.add("pf_tokens", UpsertResult(updated=len(due)))

    def _features(self, r: dict[str, Any], pair: dict[str, Any], now: datetime) -> dict[str, Any]:
        created, launch = _utc(r["created_at"]), r["launch"] or {}
        txns = pair.get("txns") or {}
        m5, h1 = txns.get("m5") or {}, txns.get("h1") or {}
        f: dict[str, Any] = {
            "age_min": round((now - created).total_seconds() / 60, 1),
            "price": pair["price"],
            "launch_multiple": round(pair["price"] / pumpfun.LAUNCH_PRICE, 3),
            "peak_before": max(p for p in (r["peak_before"], pair["price"]) if p),
            "market_cap_usd": pair.get("marketCap"),
            "trades_5m": (m5.get("buys") or 0) + (m5.get("sells") or 0),
            "buys_1h": h1.get("buys"),
            "sells_1h": h1.get("sells"),
            "volume_1h_usd": (pair.get("volume") or {}).get("h1"),
            "dex": pair.get("dexId"),
            "graduated": pair.get("dexId") == "pumpswap" or bool(launch.get("complete")),
            "links": pumpfun._links(launch),
            "dex_profile": bool(pair.get("info")),  # a paid token profile on DexScreener
            "boosts": int((pair.get("boosts") or {}).get("active") or 0),  # paid DexScreener boosts
            "serial": self._serial(r, now),
            **self._creator(r["creator"], created),
        }
        needs_holders = self.private_rpc and not f["graduated"]
        if needs_holders:
            f["top10_share"] = self._top10_share(r["mint"], launch.get("associated_bonding_curve"))
        f["complete"] = "creator_tx" in f and (not needs_holders or f["top10_share"] is not None)
        return f

    def _serial(self, r: dict[str, Any], now: datetime) -> int:
        """Other launches by the same creator seen from 24 hours before this one until now."""
        if not r["creator"]:
            return 0
        t = self._table()
        return self.store.scalar(select(func.count()).select_from(t).where(
            t.c.creator == r["creator"], t.c.mint != r["mint"],
            t.c.created_at >= _utc(r["created_at"]) - SERIAL_WINDOW, t.c.created_at <= now))

    def _creator(self, creator: str | None, created: datetime) -> dict[str, Any]:
        """The creator wallet's age before the launch, or how busy it is, from its latest transactions."""
        signatures = self._rpc("getSignaturesForAddress", [creator, {"limit": SIGNATURE_LIMIT}]) if creator else None
        times = [s["blockTime"] for s in signatures or [] if s.get("blockTime")]
        if not times:
            return {}
        oldest, newest = (datetime.fromtimestamp(x, timezone.utc) for x in (min(times), max(times)))
        span_h = max((newest - oldest).total_seconds() / 3600, 1 / 60)
        return {
            "creator_tx": len(signatures),
            "creator_history_complete": len(signatures) < SIGNATURE_LIMIT,  # then the oldest is the wallet's first
            "creator_age_h": round((created - oldest).total_seconds() / 3600, 2),
            "creator_tx_per_h": round(len(signatures) / span_h, 1),
        }

    def _top10_share(self, mint: str, curve_account: str | None) -> float | None:
        accounts = self._rpc("getTokenLargestAccounts", [mint])
        if not accounts:
            return None
        amounts = [float(a.get("uiAmountString") or a.get("uiAmount") or 0)
                   for a in accounts if a.get("address") != curve_account]
        return round(sum(sorted(amounts, reverse=True)[:10]) / SUPPLY, 4)

    # 3. Follow

    def _follow(self, now: datetime) -> None:
        t = self._table()
        rows = [dict(r) for r in self.store.query(select(t).where(t.c.status.in_(("new", "tracking"))))]
        due = [r for r in rows if _due(r, now)]
        pairs, unchecked = self._pairs([r["mint"] for r in due])
        prices = []
        for r in due:
            pair = pairs.get(r["mint"])
            if r["status"] == "new":  # not scored yet: only keep the peak, for the "already collapsed" sign
                if pair:
                    self._update(r["mint"], peak_before=max(p for p in (r["peak_before"], pair["price"]) if p))
                continue
            if pair is None and r["mint"] in unchecked:
                continue  # the request failed; try again next run
            if pair is None:
                misses = r["misses"] + 1
                self._update(r["mint"], misses=misses, last_checked_at=now,
                             status="missing" if misses >= MISSING_AFTER_SCORING else "tracking")
                continue
            price = pair["price"]
            if r["passed"]:
                prices.append({"mint": r["mint"], "at": now, "price": price})
            changes: dict[str, Any] = {
                "last_price": price, "last_checked_at": now,
                "peak_after": max(r["peak_after"] or price, price), "low_after": min(r["low_after"] or price, price),
                "graduated": bool(r["graduated"]) or pair.get("dexId") == "pumpswap",
            }
            elapsed = now - _utc(r["scored_at"])
            changes.update(_exits(r, price, elapsed, now))
            for column, after in CHECKPOINTS:
                if r[column] is None and elapsed >= after:
                    changes[column] = price
                    if column in PEAK_AT:
                        changes[PEAK_AT[column]] = changes["peak_after"]
            if elapsed >= HORIZON:
                final = changes.get("price_24h", r["price_24h"])
                changes.update(status="done", collapsed=final <= pumpfun.COLLAPSE_LEVEL * changes["peak_after"])
            self._update(r["mint"], **changes)
        self._record_prices(prices)
        self.summary.add("pf_tokens", UpsertResult(updated=len(due)))

    def _prune(self, now: datetime) -> None:
        """Launches outside the sample are only needed to spot serial creators; price history only for a week."""
        t, p = self._table(), self.store.table("pf_prices")
        with self.store.engine.begin() as conn:
            conn.execute(delete(t).where(t.c.status == "skipped", t.c.created_at < now - KEEP_SKIPPED))
            conn.execute(delete(p).where(p.c.at < now - PRICE_HISTORY))

    # Live quotes

    def quote(self, now: datetime | None = None) -> int:
        """The open positions' prices, of every fake account, stored when they changed; returns how many."""
        now = now or utcnow()
        self._warned = set()
        positions = {p["mint"]: p for account in pumpfun.accounts(self.store).values() for p in account["open"]}
        pairs, _ = self._pairs(list(positions))
        latest = pumpfun.latest_prices(self.store, list(pairs))
        changed = [{"mint": mint, "at": now, "price": pair["price"]} for mint, pair in pairs.items()
                   if mint not in latest or latest[mint][1] != pair["price"]]
        self._record_prices(changed)
        for mint, pair in pairs.items():
            position = positions[mint]
            if changes := _exits(position, pair["price"], now - position["opened_at"], now):
                self._update(mint, **changes)
        return len(changed)

    def _backfill_exits(self, now: datetime) -> None:
        """Tokens followed before an exit rule's price was recorded: find it in their price history.

        Only tokens that passed have a history, and only for a week. The quotes are in it too, so this finds
        the price the follow step or the quotes would have recorded."""
        t, p = self._table(), self.store.table("pf_prices")
        for name, beyond in (("cliff", p.c.price <= pumpfun.CLIFF * t.c.price_t),
                             ("profit", p.c.price >= pumpfun.PROFIT_LINE * t.c.price_t)):
            rows = self.store.query(
                select(t.c.mint, t.c.scored_at, p.c.at, p.c.price).join(p, p.c.mint == t.c.mint)
                .where(t.c.passed.is_(True), t.c[f"{name}_at"].is_(None), t.c.scored_at >= now - PRICE_HISTORY,
                       p.c.at > t.c.scored_at, beyond)
                .order_by(t.c.mint, p.c.at))
            first: dict[str, Any] = {}
            for r in rows:
                if r["mint"] not in first and _utc(r["at"]) <= _utc(r["scored_at"]) + HORIZON:
                    first[r["mint"]] = r
            for mint, r in first.items():
                self._update(mint, **{f"{name}_at": r["at"], f"{name}_price": r["price"]})

    def _record_prices(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            p = self.store.table("pf_prices")
            with self.store.engine.begin() as conn:
                conn.execute(self.store._insert(p).on_conflict_do_nothing(index_elements=["mint", "at"]), rows)

    # Sources

    def _pairs(self, mints: list[str]) -> tuple[dict[str, dict[str, Any]], set[str]]:
        """Each token's SOL pair on DexScreener with its price in SOL, preferring PumpSwap once it has graduated,
        and the tokens whose request failed."""
        found: dict[str, dict[str, Any]] = {}
        unchecked: set[str] = set()
        for i in range(0, len(mints), DEX_BATCH):
            chunk = mints[i:i + DEX_BATCH]
            data = self._request("GET", f"{DEXSCREENER}/{','.join(chunk)}")
            if not isinstance(data, list):
                unchecked.update(chunk)
                continue
            for p in data:
                mint = (p.get("baseToken") or {}).get("address")
                if mint not in chunk or (p.get("quoteToken") or {}).get("symbol") not in ("SOL", "WSOL"):
                    continue
                try:
                    price = float(p.get("priceNative") or 0)
                except ValueError:
                    continue
                if price > 0 and (mint not in found or _rank(p) > _rank(found[mint])):
                    found[mint] = {**p, "price": price}
        return found, unchecked

    def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        body = self._request("POST", self.rpc_url, content=payload, headers={"Content-Type": "application/json"},
                             allow_status=(429,))
        if not isinstance(body, dict) or "error" in body:
            reason = body.get("error") if isinstance(body, dict) else "HTTP 429 or no response"
            self._warn_once(method, f"{method} gave no result: {reason}")
            return None
        result = body.get("result")
        return result["value"] if isinstance(result, dict) and "value" in result else result

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """A JSON request that, unlike ``Collector.fetch``, is not kept in the raw layer."""
        try:
            resp = self.client.request(method, url, **kwargs)
        except FetchError as exc:
            self._warn_once(url.split("?")[0][:60], str(exc))
            return None
        finally:
            self.summary.fetches += 1
        return json.loads(resp.body) if resp.status < 400 else None

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            self.warn(message)

    def _update(self, mint: str, **values: Any) -> None:
        t = self._table()
        with self.store.engine.begin() as conn:
            conn.execute(update(t).where(t.c.mint == mint).values(**values))

    def _table(self):
        return self.store.table("pf_tokens")


def _exits(r: dict[str, Any], price: float, elapsed: timedelta, now: datetime) -> dict[str, Any]:
    """The exit rules' lines this price crosses for the first time within 24 hours of scoring: at or below
    half the scoring price, where the stup rule sells, and at or above the take-profit line, where the main
    account sells."""
    if not r["price_t"] or not timedelta(0) < elapsed <= HORIZON:
        return {}
    changes: dict[str, Any] = {}
    if r["cliff_at"] is None and price <= pumpfun.CLIFF * r["price_t"]:
        changes.update(cliff_at=now, cliff_price=price)
    if r["profit_at"] is None and price >= pumpfun.PROFIT_LINE * r["price_t"]:
        changes.update(profit_at=now, profit_price=price)
    return changes


def _due(r: dict[str, Any], now: datetime) -> bool:
    if r["status"] == "new":
        return _utc(r["discovered_at"]) < now  # seen in an earlier run and not scored yet
    elapsed = now - _utc(r["scored_at"])
    if elapsed <= timedelta(0):
        return False  # scored in this run
    if elapsed <= FAST_PHASE or any(r[c] is None and elapsed >= after for c, after in CHECKPOINTS):
        return True
    return r["last_checked_at"] is None or now - _utc(r["last_checked_at"]) >= SLOW_INTERVAL


def _rank(pair: dict[str, Any]) -> tuple[bool, float]:
    return pair.get("dexId") == "pumpswap", float((pair.get("volume") or {}).get("h24") or 0)


def _ath_price(c: dict[str, Any]) -> float | None:
    """pump.fun gives the all-time-high market cap in USD and the current one in both SOL and USD."""
    sol, usd, ath = c.get("market_cap"), c.get("usd_market_cap"), c.get("ath_market_cap")
    if sol and usd and ath:
        return ath * (sol / usd) / SUPPLY
    return sol / SUPPLY if sol else None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
