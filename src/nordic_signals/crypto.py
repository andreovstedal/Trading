"""A play-money crypto account: half in the big coins, 30 % in smaller ones and 20 % on pump.fun, to calibrate a
crypto strategy before any real money is used.

Nothing here trades. The account starts with 100 000 NOK on Firi, the Norwegian exchange that trades crypto
against NOK, and is a replay (``account``): its trades, fees and value are worked out from the stored prices each
time, so only the prices are stored (``collectors.crypto``), and late prices correct the history.

* **The parts.** Bitcoin and Ether get 25 % each (the big coins); XRP, Cardano and Solana 10 % each (the smaller
  ones); and 20 % is SOL in a wallet trading on pump.fun, which follows the pump.fun page's main fake account
  (``pumpfun.MAIN_ACCOUNT``) up and down, as a share of it would.
* **The trend rule** (the main account). Every Monday at 00:00 UTC, on Sunday's close, a coin is held only while its
  price is above its average over the last 200 days; below it, its share waits in NOK until a later Monday finds it
  above again. The 200-day average is the most widely used long-term trend line, and checked weekly rather than
  daily it trades about four times a year per coin, which Firi's costs allow (see the README for the backtest).
  A coin with less than 200 days of closes is held.
* **Rebalancing.** On the first of each month at 00:00 UTC, every coin the rule holds and the pump.fun part go back
  to their share of the account, unless they are already within a fifth of it (``TOLERANCE``): that keeps the
  50/30/20 split without paying for small trades. That night's check also applies the trend rule.
* **Prices and fees.** Firi's price list (checked 5 October 2026): 0.7 % of each trade. A trade is a market order
  at the first prices collected after the decision, buying at the best ask and selling at the best bid of Firi's
  NOK order book, so the spread is paid too: from 0.2 % (XRP) to 1 % (Ether) each way that day. A purchase spends
  the money set for it, fees and spread included, so each part pays its own costs. The pump.fun part's
  SOL is bought on Firi and sent to a wallet for 0.05 SOL (``SOL_WITHDRAWAL``, Firi's fee from 1 December 2026;
  0.045 before); sending it back is free.
* **Value.** Coins at the middle of Firi's best bid and ask, the pump.fun part at its SOL's value; the cost of
  selling is paid when something is sold.

``accounts`` gives the main account and its yardstick, which holds every coin all the time and rebalances the same
way: what the trend rule is up against. Both have the same pump.fun part.

Change ``ACCOUNT`` and ``STARTED_AT`` when the rules change, and the account starts again from scratch.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from statistics import fmean
from typing import Any

from sqlalchemy import func, select

from . import text
from .store import Store, utcnow

ACCOUNT = "krypto-1"  # a new name starts a new account; move STARTED_AT with it
START = 100_000.0  # NOK
STARTED_AT = datetime(2026, 10, 6, tzinfo=timezone.utc)  # the first trades: the first prices collected after this


@dataclass(frozen=True)
class Coin:
    symbol: str
    name: str
    part: str  # "big" or "small"
    weight: float  # its share of the account
    market: str  # Firi's NOK market
    yahoo: str  # its daily closes, in USD


COINS = (
    Coin("BTC", "Bitcoin", "big", 0.25, "BTCNOK", "BTC-USD"),
    Coin("ETH", "Ether", "big", 0.25, "ETHNOK", "ETH-USD"),
    Coin("XRP", "XRP", "small", 0.10, "XRPNOK", "XRP-USD"),
    Coin("ADA", "Cardano", "small", 0.10, "ADANOK", "ADA-USD"),
    Coin("SOL", "Solana", "small", 0.10, "SOLNOK", "SOL-USD"),
)
PUMPFUN = 0.20  # the pump.fun part's share
SOL = "SOLNOK"  # where the pump.fun part's SOL is bought, sold and valued
PARTS = {"big": "Store mynter", "small": "Mindre mynter", "pumpfun": "pump.fun"}

FEE = 0.007  # Firi, on each trade (firi.com/no/priser, checked 5 October 2026)
SOL_WITHDRAWAL = 0.05  # SOL, to send SOL from Firi to a wallet
TREND_DAYS = 200
TOLERANCE = 0.2  # the monthly rebalancing leaves a holding that is within this share of its target
DECIDE_AT = time(0, 0)  # UTC: the day before has closed
MIN_TRADE = 10.0  # NOK: smaller trades are left out


# The prices

@dataclass
class Prices:
    """What the replay needs: Firi's best bid and ask at each collector run that got every market, the coins' daily
    closes, and the pump.fun main account's value over time as an index."""
    runs: list[tuple[datetime, dict[str, tuple[float, float]]]]
    closes: dict[str, tuple[list[date], list[float]]]
    pump_times: list[datetime] = field(default_factory=list)
    pump_index: list[float] = field(default_factory=list)

    def pump(self, at: datetime) -> float:
        k = bisect.bisect_right(self.pump_times, at)
        if k:
            return self.pump_index[k - 1]
        return self.pump_index[0] if self.pump_index else 1.0

    def latest(self, now: datetime) -> tuple[datetime, dict[str, tuple[float, float]]] | None:
        k = bisect.bisect_right([at for at, _ in self.runs], now)
        return self.runs[k - 1] if k else None


def load(store: Store) -> Prices:
    q = store.table("crypto_quotes")
    markets = {c.market for c in COINS}
    runs: dict[datetime, dict[str, tuple[float, float]]] = {}
    for r in store.query(select(q).where(q.c.at >= STARTED_AT - timedelta(days=2)).order_by(q.c.at)):
        runs.setdefault(_aware(r["at"]), {})[r["market"]] = (r["bid"], r["ask"])
    bars = store.table("price_bars")
    symbols = {c.yahoo: c.symbol for c in COINS}
    closes: dict[str, tuple[list[date], list[float]]] = {}
    for r in store.query(select(bars.c.symbol, bars.c.ts, bars.c.close)
                         .where(bars.c.symbol.in_(list(symbols)), bars.c.interval == "1d", bars.c.close > 0)
                         .order_by(bars.c.ts)):
        days, values = closes.setdefault(symbols[r["symbol"]], ([], []))
        days.append(datetime.fromtimestamp(r["ts"], timezone.utc).date())
        values.append(r["close"])
    times, index = _pump_index(store, STARTED_AT - timedelta(days=1))
    return Prices([(at, books) for at, books in runs.items() if markets <= books.keys()], closes, times, index)


def freshness(store: Store) -> tuple[str, datetime | None]:
    """A stamp that changes whenever the account's data does (new prices from Firi, a new value of the pump.fun
    account), and when it last changed: what the page polls to stay live."""
    quoted = _aware(store.scalar(select(func.max(store.table("crypto_quotes").c.at))))
    pumped = _aware(store.scalar(select(func.max(store.table("pf_equity").c.at))))
    stamp = ".".join(str(int(t.timestamp() * 1000)) if t else "0" for t in (quoted, pumped))
    return stamp, max((t for t in (quoted, pumped) if t), default=None)


def _pump_index(store: Store, since: datetime) -> tuple[list[datetime], list[float]]:
    """The pump.fun main account's value from ``since`` as an index starting at 1. It moves with the account's
    value in SOL; a new screen version or set of rules, whose account starts again at 10 SOL, carries on from
    where the last one ended."""
    e = store.table("pf_equity")
    times: list[datetime] = []
    index: list[float] = []
    level, last = 1.0, None
    for r in store.query(select(e.c.at, e.c.equity, e.c.screen_version, e.c.account)
                         .where(e.c.at >= since).order_by(e.c.at)):
        key = (r["screen_version"], r["account"])
        if last is not None and last[0] == key and last[1] > 0:
            level *= r["equity"] / last[1]
        last = (key, r["equity"])
        times.append(_aware(r["at"]))
        index.append(level)
    return times, index


def trend(closes: tuple[list[date], list[float]] | None, before: date) -> dict[str, Any] | None:
    """The trend rule's view on the closes of the days before ``before``: the latest, its average over TREND_DAYS
    days and whether it is above; None without that much history."""
    if not closes:
        return None
    days, values = closes
    k = bisect.bisect_left(days, before)
    if k < TREND_DAYS:
        return None
    average = fmean(values[k - TREND_DAYS:k])
    close = values[k - 1]
    return {"day": days[k - 1], "close": close, "average": average, "gap": close / average - 1,
            "above": close > average}


# When it decides

def decisions(until: datetime, *, trend: bool) -> list[tuple[datetime, str]]:
    """The account's decisions up to ``until``: the start, each first of the month and, with the trend rule, each
    Monday, at 00:00 UTC. A Monday that is the first is the month's."""
    out = [(STARTED_AT, "start")] if STARTED_AT <= until else []
    day = STARTED_AT.date() + timedelta(days=1)
    while (at := datetime.combine(day, DECIDE_AT, timezone.utc)) <= until:
        if day.day == 1:
            out.append((at, "month"))
        elif trend and day.weekday() == 0:
            out.append((at, "week"))
        day += timedelta(days=1)
    return out


def upcoming(now: datetime) -> dict[str, datetime]:
    """The next start, weekly check and monthly rebalancing after ``now``."""
    if now < STARTED_AT:
        return {"start": STARTED_AT}
    week = month = None
    day = now.date() + timedelta(days=1)
    while week is None or month is None:
        at = datetime.combine(day, DECIDE_AT, timezone.utc)
        if month is None and day.day == 1:
            month = at
        if week is None and day.weekday() == 0 and day.day != 1:
            week = at
        day += timedelta(days=1)
    return {"week": week, "month": month}


# The account, worked out from the prices

@dataclass
class Holding:
    units: float = 0.0  # coins; for the pump.fun part, SOL at an index of 1 (``Prices.pump``)
    cost: float = 0.0  # NOK paid for what is held, fees and spread included (average cost)


class _Book:
    def __init__(self, trend: bool):
        self.trend = trend
        self.cash = START
        self.coins = {c.symbol: Holding() for c in COINS}
        self.pump = Holding()
        self.wanted: dict[str, bool] = {}  # the trend rule's view at the latest check
        self.trades: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.history: list[tuple[datetime, float]] = []
        self.started_at: datetime | None = None
        self.fees = self.spread = self.withdrawals = 0.0

    def value(self, books: dict[str, tuple[float, float]], index: float) -> float:
        return (self.cash + sum(self.coins[c.symbol].units * mid_price(books[c.market]) for c in COINS)
                + self.pump.units * index * mid_price(books[SOL]))

    def decide(self, decided: datetime, kind: str, at: datetime, books: dict[str, tuple[float, float]],
               prices: Prices) -> None:
        index = prices.pump(at)
        views = {c.symbol: trend(prices.closes.get(c.symbol), decided.date()) for c in COINS}
        wanted = {s: not self.trend or v is None or v["above"] for s, v in views.items()}
        value = self.value(books, index)
        plans: list[tuple[Coin, float, str]] = []
        for c in COINS:
            held = self.coins[c.symbol].units * mid_price(books[c.market])
            target = c.weight * value if wanted[c.symbol] else 0.0
            switched = kind != "start" and wanted[c.symbol] != self.wanted.get(c.symbol)
            if kind == "week" and not switched:
                continue
            if kind == "month" and not switched and held > 0 and abs(held - target) <= TOLERANCE * target:
                continue
            if kind == "start":
                reason = f"Start: {text.percent(c.weight, 0)} av kontoen"
            elif switched:
                view = views[c.symbol]
                gap = text.percent(view["gap"], 1, True) if view else "for kort historikk"
                reason = (f"Over snittet for {TREND_DAYS} dager igjen ({gap})" if wanted[c.symbol]
                          else f"Under snittet for {TREND_DAYS} dager ({gap})")
            else:
                reason = f"Månedlig rebalansering fra {text.percent(held / value, 1)} til {text.percent(c.weight, 0)}"
            plans.append((c, target, reason))
        pump_target = None
        if kind != "week":
            held = self.pump.units * index * mid_price(books[SOL])
            if kind == "start" or abs(held - PUMPFUN * value) > TOLERANCE * PUMPFUN * value:
                pump_target = PUMPFUN * value
        before = len(self.trades)
        # Sales first, so their money is there for the purchases.
        for c, target, reason in plans:
            self._sell_down(c, target, books[c.market], at, decided, kind, reason)
        if pump_target is not None:
            self._pump_out(pump_target, books[SOL], index, at, decided, kind, value)
        for c, target, reason in plans:
            self._buy_up(c, target, books[c.market], at, decided, kind, reason)
        if pump_target is not None:
            self._pump_in(pump_target, books[SOL], index, at, decided, kind, value)
        self.wanted = wanted
        self.started_at = self.started_at or at
        self.checks.append({"decided_at": decided, "at": at, "kind": kind, "value": value, "trades": len(self.trades) - before,
                            "wanted": wanted, "views": views})

    def _sell_down(self, c: Coin, target: float, book: tuple[float, float], at: datetime, decided: datetime,
                   kind: str, reason: str) -> None:
        h = self.coins[c.symbol]
        mid = mid_price(book)
        held = h.units * mid
        if held <= target or held - target < MIN_TRADE:
            return
        units = h.units if target == 0 else (held - target) / mid
        self._sell(c.symbol, c.name, c.part, h, units, book, at, decided, kind, reason)

    def _buy_up(self, c: Coin, target: float, book: tuple[float, float], at: datetime, decided: datetime,
                kind: str, reason: str) -> None:
        h = self.coins[c.symbol]
        spend = min(target - h.units * mid_price(book), self.cash)  # fees and spread included
        if spend >= MIN_TRADE:
            self._buy(c.symbol, c.name, c.part, h, spend / (book[1] * (1 + FEE)), book, at, decided, kind, reason)

    def _pump_out(self, target: float, book: tuple[float, float], index: float, at: datetime, decided: datetime,
                  kind: str, value: float) -> None:
        mid = mid_price(book)
        held = self.pump.units * index * mid
        if held - target < MIN_TRADE:
            return
        sol = (held - target) / mid
        reason = (f"pump.fun-delen fra {text.percent(held / value, 1)} til {text.percent(PUMPFUN, 0)}: "
                  "SOL tilbake til Firi og solgt")
        self._sell("pump.fun", "pump.fun-delen", "pumpfun", self.pump, sol / index, book, at, decided, kind, reason,
                   per_unit=index)

    def _pump_in(self, target: float, book: tuple[float, float], index: float, at: datetime, decided: datetime,
                 kind: str, value: float) -> None:
        mid = mid_price(book)
        held = self.pump.units * index * mid
        spend = min(target - held, self.cash)  # fees and spread included; the withdrawal fee comes off the SOL
        sol = spend / (book[1] * (1 + FEE))
        if spend < MIN_TRADE or sol <= SOL_WITHDRAWAL:
            return
        reason = (f"Start: {text.percent(PUMPFUN, 0)} av kontoen" if kind == "start"
                  else f"pump.fun-delen fra {text.percent(held / value, 1)} til {text.percent(PUMPFUN, 0)}")
        trade = self._buy("pump.fun", "pump.fun-delen", "pumpfun", self.pump, sol, book, at, decided, kind,
                          reason + ": SOL kjøpt og sendt til lommeboken", per_unit=index, units=(sol - SOL_WITHDRAWAL) / index)
        trade["withdrawal"] = SOL_WITHDRAWAL * mid
        self.withdrawals += trade["withdrawal"]

    def _buy(self, asset: str, name: str, part: str, h: Holding, qty: float, book: tuple[float, float],
             at: datetime, decided: datetime, kind: str, reason: str, *, per_unit: float = 1.0,
             units: float | None = None) -> dict[str, Any]:
        """Buy ``qty`` (coins, or SOL for the pump.fun part) at the best ask; ``units`` is what the holding gets."""
        ask, mid = book[1], mid_price(book)
        paid = qty * ask * (1 + FEE)
        self.cash -= paid
        h.units += qty / per_unit if units is None else units
        h.cost += paid
        trade = self._trade(at, decided, kind, "buy", asset, name, part, qty, ask, mid, -paid, reason)
        return trade

    def _sell(self, asset: str, name: str, part: str, h: Holding, units: float, book: tuple[float, float],
              at: datetime, decided: datetime, kind: str, reason: str, *, per_unit: float = 1.0) -> dict[str, Any]:
        """Sell ``units`` of the holding at the best bid: coins, or for the pump.fun part SOL at an index of 1."""
        bid, mid = book[0], mid_price(book)
        share = min(units / h.units, 1.0)
        qty = units * per_unit
        received = qty * bid * (1 - FEE)
        cost = h.cost * share
        self.cash += received
        h.units, h.cost = (0.0, 0.0) if share >= 1 - 1e-9 else (h.units - units, h.cost - cost)
        trade = self._trade(at, decided, kind, "sell", asset, name, part, qty, bid, mid, received, reason)
        trade.update(result=received - cost, result_pct=(received - cost) / cost if cost else None)
        return trade

    def _trade(self, at: datetime, decided: datetime, kind: str, side: str, asset: str, name: str, part: str,
               qty: float, price: float, mid: float, cash: float, reason: str) -> dict[str, Any]:
        fee, spread = qty * price * FEE, qty * abs(price - mid)
        self.fees += fee
        self.spread += spread
        trade = {"at": at, "decided_at": decided, "kind": kind, "side": side, "asset": asset, "name": name,
                 "part": part, "qty": qty, "price": price, "mid": mid, "value": qty * price, "fee": fee,
                 "spread": spread, "withdrawal": 0.0, "cash": cash, "result": None, "result_pct": None,
                 "reason": reason}
        self.trades.append(trade)
        return trade


def account(store: Store, now: datetime | None = None, *, trend: bool = True,
            prices: Prices | None = None) -> dict[str, Any]:
    """The account replayed from the start up to ``now``: each decision is carried out at the first prices collected
    after it (a decision without them yet is pending), and the account is valued at each collection."""
    now = now or utcnow()
    prices = prices or load(store)
    book = _Book(trend)
    planned = decisions(now, trend=trend)
    i = 0
    for at, books in prices.runs:
        if at > now:
            break
        while i < len(planned) and planned[i][0] <= at:
            book.decide(*planned[i], at, books, prices)
            i += 1
        if book.started_at is not None:
            book.history.append((at, book.value(books, prices.pump(at))))
    return _summary(book, prices, now, planned[i:])


def accounts(store: Store, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """The main account (the trend rule) and its yardstick (buy and hold), from the same prices."""
    now = now or utcnow()
    prices = load(store)
    return {"trend": account(store, now, trend=True, prices=prices),
            "hold": account(store, now, trend=False, prices=prices)}


def _summary(book: _Book, prices: Prices, now: datetime, pending: list[tuple[datetime, str]]) -> dict[str, Any]:
    latest = prices.latest(now)
    valued_at, books = latest if latest else (None, None)
    index = prices.pump(valued_at) if valued_at else 1.0
    equity = book.value(books, index) if books else book.cash
    coins = []
    for c in COINS:
        h = book.coins[c.symbol]
        bid, ask = books[c.market] if books else (None, None)
        price = mid_price(books[c.market]) if books else None
        value = h.units * price if price else 0.0
        coins.append({"symbol": c.symbol, "name": c.name, "part": c.part, "weight": c.weight, "market": c.market,
                      "units": h.units, "bid": bid, "ask": ask, "price": price, "value": value,
                      "share": value / equity if equity else 0.0, "cost": h.cost,
                      "result": value - h.cost if h.units else None,
                      "result_pct": value / h.cost - 1 if h.units and h.cost else None,
                      "wanted": book.wanted.get(c.symbol),
                      "trend": trend(prices.closes.get(c.symbol), (now + timedelta(days=1)).date())})
    sol_price = mid_price(books[SOL]) if books else None
    pump_sol = book.pump.units * index
    pump_value = pump_sol * sol_price if sol_price else 0.0
    pump = {"sol": pump_sol, "value": pump_value, "share": pump_value / equity if equity else 0.0,
            "weight": PUMPFUN, "cost": book.pump.cost, "sol_price": sol_price,
            "result": pump_value - book.pump.cost if book.pump.units else None,
            "result_pct": pump_value / book.pump.cost - 1 if book.pump.units and book.pump.cost else None}
    parts = []
    for key, name in PARTS.items():
        value = pump_value if key == "pumpfun" else sum(c["value"] for c in coins if c["part"] == key)
        weight = PUMPFUN if key == "pumpfun" else sum(c.weight for c in COINS if c.part == key)
        parts.append({"key": key, "name": name, "weight": weight, "value": value,
                      "share": value / equity if equity else 0.0})
    return {
        "account": ACCOUNT, "trend": book.trend, "start": START, "started_at": book.started_at,
        "valued_at": valued_at, "cash": book.cash, "equity": equity, "result": equity / START - 1,
        "coins": coins, "pumpfun": pump, "parts": parts, "trades": book.trades, "checks": book.checks,
        "history": book.history, "pending": pending,
        "fees": book.fees, "spread": book.spread, "withdrawals": book.withdrawals,
        "costs": book.fees + book.spread + book.withdrawals,
        "upcoming": upcoming(now),
    }


def mid_price(book: tuple[float, float]) -> float:
    """The middle of the best bid and ask."""
    return (book[0] + book[1]) / 2


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
