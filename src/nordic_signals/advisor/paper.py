"""A play-money Nordnet account that trades on the advisor's recommendations, to calibrate them.

Nothing here trades. The account starts with 500 000 NOK and follows the advisor's own rules (the default
policy: 90 % in the long-term part, 10 % in the short-term part, up to 12 positions of at least 20 000 NOK),
the way a customer of Nordnet in Norway would trade them:

* **When.** Orders are decided in the evening, once both markets have closed and the nightly data is in
  (``decide``), and fill at the opening price of the stock's next trading day: the opening auction, where every
  order gets the same price, so no spread is paid. Oslo Børs trades 09:00-16:25 and Nasdaq Stockholm
  09:00-17:30, Norwegian time. An order fills on the first day its stock traded after the decision, from the
  prices, so a halt or a day without trades waits; one whose stock has not traded within 5 of its market's
  trading days lapses. The markets' calendars (``MARKETS``) count those days and a short-term position's
  holding period, and show on the page whether the markets are open.
* **Fees.** Nordnet's Norwegian price list, class Mini (checked 4 October 2026, the cheapest for trades under
  52 667 NOK): 0.15 % of each trade in Nordic shares, at least 29 NOK. Swedish shares bought from a NOK account
  also pay 0.25 % on each automatic currency exchange, buying and selling.
* **Dividends** are credited on the ex-date, from Yahoo's dividend events; Swedish ones after 15 % withholding
  tax (the tax treaty's rate for a Norwegian resident). An ASK pays no Norwegian tax on them.
* **Value.** Positions are valued at each day's closing price, as Nordnet's account overview does: the cost of
  selling is paid when a position is sold. While a market is open, the stocks the account holds or has orders for
  are fetched from Yahoo every half hour (``watched_symbols``): the morning's orders fill at the opening price soon
  after 09:00, and the account is valued at the latest prices, until the evening's closing prices replace them.

The long-term part is rebalanced once a month, on the first trading evening: holdings the advisor still ranks
among the best 2 × 12 eligible stocks stay, the rest are sold, and the best-ranked stocks it does not hold are
bought until it holds 12 (the research report's buy/hold spread: stricter to enter than to stay, so turnover
and courtage stay low). That evening's recommendation is logged like any other, so the track record measures it
too. The short-term part buys the advisor's event signals (a new buyback programme, several insiders buying)
every evening, at most 2 a day and as many at once as its 50 000 NOK allows, and sells each after 5 trading
days, the signals' horizon.

The account is a replay (``account``): the orders are stored, and the fills, fees, dividends and value are
worked out from the prices each time, so late data corrects the history. Change ``ACCOUNT`` when the rules
change, and the account starts again from scratch.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, insert, select

from ..collectors.base import NORDIC_TZ
from ..collectors.yahoo import EXCHANGE_SUFFIX, yahoo_symbol
from ..store import Store, utcnow
from . import recommend
from .allocation import MAX_SHORT_POSITIONS, SHORT_HORIZON_DAYS, Policy, short_sleeve
from .features import build_features, trading_day
from .recommend import FX_PAIRS, load_fx
from .scoring import MODEL_VERSION, score_stocks

ACCOUNT = "lekepenger-1"  # a new name starts a new account
ORIGIN = "lekepenger"  # recommendations.origin of the account's monthly recommendations
START = 500_000.0  # NOK
POLICY: dict[str, Any] = {"long_pct": 90.0, "short_pct": 10.0, "cash_pct": 0.0, "max_positions": 12,
                          "min_position": 20_000.0, "short_paper_only": False, "ask_only": False,
                          "countries": ("NO", "SE")}

# Nordnet Norway, class Mini, Nordic shares; automatic currency exchange (nordnet.no/kundeservice/prisliste).
COURTAGE = 0.0015
COURTAGE_MIN = 29.0  # NOK
FX_SPREAD = 0.0025  # on each exchange
SE_DIVIDEND_TAX = 0.15

HOLD_RANK = 2  # long-term holdings stay while ranked among the best HOLD_RANK × positions
SHORT_HOLD = SHORT_HORIZON_DAYS  # trading days a short-term position is held
MAX_NEW_SHORT = 2  # new short-term trades an evening
ORDER_DAYS = 5  # an order lapses if its stock has not traded within this many of its market's trading days
AFTER_CLOSE = time(18, 0)  # Norwegian time: a snapshot from then on has the day's closing prices
EVENING = time(20, 45)  # UTC: the account decides after the nightly collection, which starts at 20:30 UTC
INTRADAY = timedelta(minutes=30)  # how often the account's stocks are fetched while a market is open


@dataclass(frozen=True)
class Market:
    name: str
    opens: time
    closes: time
    holidays: frozenset[date]
    half_days: frozenset[date]  # close at HALF_DAY_CLOSE


def _dates(text: str) -> frozenset[date]:
    return frozenset(date.fromisoformat(d) for d in text.split())


HALF_DAY_CLOSE = time(13, 0)
# Norwegian time; the two markets share a time zone. Holidays and half days from Euronext's calendar for Oslo in
# 2026 and Nasdaq's for Stockholm (nasdaq.com/european-market-activity/trading-hours); Oslo's 2027 dates are
# Nasdaq's Norwegian calendar, as Euronext had not published 2027 by October 2026. Add each new year's dates.
MARKETS = {
    "NO": Market("Oslo Børs", time(9, 0), time(16, 25),
                 _dates("2026-01-01 2026-04-02 2026-04-03 2026-04-06 2026-05-01 2026-05-14 2026-05-25 2026-12-24"
                        " 2026-12-25 2026-12-31 2027-01-01 2027-03-25 2027-03-26 2027-03-29 2027-05-06 2027-05-17"
                        " 2027-12-24 2027-12-31"),
                 _dates("2026-04-01 2027-03-24")),
    "SE": Market("Nasdaq Stockholm", time(9, 0), time(17, 30),
                 _dates("2026-01-01 2026-01-06 2026-04-03 2026-04-06 2026-05-01 2026-05-14 2026-06-19 2026-12-24"
                        " 2026-12-25 2026-12-31 2027-01-01 2027-01-06 2027-03-26 2027-03-29 2027-05-06 2027-06-25"
                        " 2027-12-24 2027-12-31"),
                 _dates("2026-01-05 2026-04-02 2026-04-30 2026-05-13 2026-10-30 2027-01-05 2027-03-25 2027-04-30"
                        " 2027-05-05 2027-11-05")),
}


def trading_hours(country: str, day: date) -> tuple[datetime, datetime] | None:
    """When the market trades on ``day``, or None if it is closed."""
    market = MARKETS[country]
    if day.weekday() >= 5 or day in market.holidays:
        return None
    closes = HALF_DAY_CLOSE if day in market.half_days else market.closes
    return datetime.combine(day, market.opens, NORDIC_TZ), datetime.combine(day, closes, NORDIC_TZ)


def market_status(country: str, now: datetime) -> dict[str, Any]:
    """Whether the market is open now, until when, and when it next opens."""
    local = now.astimezone(NORDIC_TZ)
    hours = trading_hours(country, local.date())
    is_open = hours is not None and hours[0] <= local < hours[1]
    next_open = None
    for ahead in range(15):
        later = trading_hours(country, local.date() + timedelta(days=ahead))
        if later and later[0] > local:
            next_open = later[0]
            break
    return {"country": country, "name": MARKETS[country].name, "open": is_open,
            "closes": hours[1] if is_open else None, "next_open": next_open}


def market_days(country: str, after: date, until: date) -> list[date]:
    """The market's trading days after ``after``, up to and including ``until``."""
    out, day = [], after
    while day < until:
        day += timedelta(days=1)
        if trading_hours(country, day):
            out.append(day)
    return out


def watched_symbols(store: Store, now: datetime | None = None) -> list[str]:
    """Yahoo symbols for the stocks the account holds or has orders waiting for, and SEK/NOK, while a market is open
    (none otherwise): fetched during the day, so an order fills soon after the opening and the account is valued at
    the latest prices instead of yesterday's closes."""
    now = now or utcnow()
    if not any(market_status(country, now)["open"] for country in MARKETS):
        return []
    state = account(store, now)
    stocks = {(s["symbol"], s["country"]) for s in (*state["positions"], *state["pending"])}
    symbols = sorted(yahoo_symbol(symbol, country) for symbol, country in stocks
                     if symbol and country in EXCHANGE_SUFFIX)
    return [*symbols, *FX_PAIRS.values()] if symbols else []


def next_evening(now: datetime) -> datetime | None:
    """When the account next decides: the evening of the next day either market trades."""
    for ahead in range(15):
        day = now.astimezone(NORDIC_TZ).date() + timedelta(days=ahead)
        evening = datetime.combine(day, EVENING, timezone.utc)
        if evening > now and any(trading_hours(country, day) for country in MARKETS):
            return evening
    return None


def next_opening(country: str, after: date) -> datetime | None:
    """When an order decided on the evening of ``after`` meets the market: its next opening."""
    days = market_days(country, after, after + timedelta(days=14))
    return trading_hours(country, days[0])[0] if days else None


def costs(value_nok: float, currency: str | None) -> tuple[float, float]:
    """Courtage and the currency exchange's cost of one trade, in NOK."""
    exchange = FX_SPREAD * value_nok if currency not in (None, "NOK") else 0.0
    return max(COURTAGE_MIN, COURTAGE * value_nok), exchange


def buy_room(currency: str | None) -> float:
    """What a buy costs per NOK of shares, above the minimum courtage: so the fees fit in the money set aside."""
    return 1 + COURTAGE + (FX_SPREAD if currency not in (None, "NOK") else 0.0)


# The account, worked out from the orders and the prices

@dataclass
class Lot:
    order: dict[str, Any]
    shares: int
    cost: float  # NOK, including courtage and currency exchange
    opened_on: date


def account(store: Store, now: datetime | None = None) -> dict[str, Any]:
    """Every order filled at its opening price in turn, dividends credited, and the value at each day's close."""
    now = now or utcnow()
    orders = _orders(store)
    if not orders:
        return _summary(START, {}, [], [], [], [], [], [], _closes({}), {})
    since = min(o["decided_on"] for o in orders)
    stocks = {o["instrument_id"]: o for o in orders}
    prices = _prices(store, stocks, since)
    close = _closes(prices)
    latest = max((d for series in prices.values() for d in series), default=since)
    fx = _fx(store)
    dividends = _dividends(store, stocks, since)

    by_day: dict[date, list[dict[str, Any]]] = defaultdict(list)
    pending, lapsed = [], []
    for o in orders:
        traded = sorted(d for d in prices.get(o["instrument_id"], {}) if d > o["decided_on"])
        window = market_days(o["country"], o["decided_on"], latest)[:ORDER_DAYS]
        if traded and (len(window) < ORDER_DAYS or traded[0] <= window[-1]):
            by_day[traded[0]].append(o)
        elif len(window) == ORDER_DAYS:
            lapsed.append({**o, "status": f"Bortfalt: aksjen ble ikke handlet på {ORDER_DAYS} handelsdager"})
        else:
            pending.append(o)

    cash, holdings, trades, received, history = START, {}, [], [], []
    paid_through: date = since
    for day in sorted({d for series in prices.values() for d in series if d > since}):
        for ex_date, instrument_id, amount, currency in dividends:
            lot = holdings.get(instrument_id)
            if paid_through < ex_date <= day and lot is not None:
                gross = lot.shares * amount * (_rate(fx, currency, day) or 0.0)
                tax = gross * SE_DIVIDEND_TAX if lot.order["country"] == "SE" else 0.0
                cash += gross - tax
                received.append({"day": ex_date, "instrument_id": instrument_id, "name": lot.order["name"],
                                 "symbol": lot.order["symbol"], "shares": lot.shares, "per_share": amount,
                                 "currency": currency, "nok": gross - tax, "tax": tax})
        paid_through = day
        # Sales first, so their money is there for the day's purchases (Nordnet lends against unsettled sales).
        for o in sorted(by_day.get(day, []), key=lambda o: (o["side"] != "sell", o["decided_at"], o["id"])):
            opening, closing = prices[o["instrument_id"]][day]
            price = opening or closing
            rate = _rate(fx, o["currency"], day)
            if rate is None:
                lapsed.append({**o, "status": f"Ikke utført: mangler valutakurs for {o['currency']}"})
                continue
            if o["side"] == "sell":
                lot = holdings.pop(o["instrument_id"], None)
                if lot is None:
                    lapsed.append({**o, "status": "Ikke solgt: aksjen var ikke i beholdningen"})
                    continue
                value = lot.shares * price * rate
                courtage, exchange = costs(value, o["currency"])
                cash += value - courtage - exchange
                trades.append(_trade(o, day, lot.shares, price, rate, value, courtage, exchange, opening is None,
                                     result=value - courtage - exchange - lot.cost, lot=lot))
            elif o["instrument_id"] in holdings:
                lapsed.append({**o, "status": "Ikke kjøpt: aksjen var allerede i beholdningen"})
            else:
                shares = _affordable(o["shares"], price * rate, o["currency"], cash)
                if shares == 0:
                    lapsed.append({**o, "status": "Ikke kjøpt: ikke nok penger"})
                    continue
                value = shares * price * rate
                courtage, exchange = costs(value, o["currency"])
                cash -= value + courtage + exchange
                holdings[o["instrument_id"]] = Lot(o, shares, value + courtage + exchange, day)
                trades.append(_trade(o, day, shares, price, rate, value, courtage, exchange, opening is None))
        worth = sum(lot.shares * close(i, day) * (_rate(fx, lot.order["currency"], day) or 0.0)
                    for i, lot in holdings.items())
        history.append((day, cash + worth, cash))
    return _summary(cash, holdings, trades, received, history, pending, lapsed, orders, close, fx)


def _summary(cash: float, holdings: dict[int, Lot], trades: list, received: list, history: list, pending: list,
             lapsed: list, orders: list, close: Callable[[int, date], float], fx: dict) -> dict[str, Any]:
    latest = history[-1][0] if history else None
    positions = []
    for instrument_id, lot in holdings.items():
        o = lot.order
        price = close(instrument_id, latest) if latest else None
        rate = _rate(fx, o["currency"], latest) if latest else None
        value = lot.shares * price * rate if price and rate else 0.0
        held = 1 + len(market_days(o["country"], lot.opened_on, latest)) if latest else 0  # the buying day is day 1
        positions.append({**o, "shares": lot.shares, "cost": lot.cost, "opened_on": lot.opened_on, "price": price,
                          "rate": rate, "value": value, "result": value - lot.cost,
                          "result_pct": value / lot.cost - 1 if lot.cost else None, "held_days": held})
    worth = sum(p["value"] for p in positions)
    equity = cash + worth
    sales = [t for t in trades if t["side"] == "sell"]
    return {
        "account": ACCOUNT, "start": START, "cash": cash, "positions_value": worth, "equity": equity,
        "result": equity / START - 1, "valued_on": latest,
        "positions": sorted(positions, key=lambda p: (p["sleeve"] != "long", -p["value"])),
        "trades": trades, "dividends": received, "pending": pending, "lapsed": lapsed, "orders": orders,
        "history": history,
        "courtage": sum(t["courtage"] for t in trades), "exchange": sum(t["exchange"] for t in trades),
        "dividends_nok": sum(d["nok"] for d in received),
        "sales": len(sales), "won": sum(t["result"] > 0 for t in sales),
        "started_on": min((o["decided_on"] for o in orders), default=None),
    }


def _trade(o: dict[str, Any], day: date, shares: int, price: float, rate: float, value: float, courtage: float,
           exchange: float, at_close: bool, *, result: float | None = None, lot: Lot | None = None) -> dict[str, Any]:
    total = value - courtage - exchange if o["side"] == "sell" else -(value + courtage + exchange)
    opens = MARKETS[o["country"]].opens if o["country"] in MARKETS else time(9, 0)
    return {"order_id": o["id"], "day": day, "at": datetime.combine(day, opens, NORDIC_TZ), "side": o["side"],
            "sleeve": o["sleeve"], "instrument_id": o["instrument_id"], "symbol": o["symbol"], "name": o["name"],
            "country": o["country"], "currency": o["currency"], "shares": shares, "price": price, "fx_rate": rate,
            "value": value, "courtage": courtage, "exchange": exchange, "cash": total, "reason": o["reason"],
            "signal_type": o["signal_type"], "at_close": at_close, "result": result,
            "bought_on": lot.opened_on if lot else None, "cost": lot.cost if lot else None,
            "result_pct": result / lot.cost if lot and lot.cost and result is not None else None}


def _affordable(shares: int, unit: float, currency: str | None, cash: float) -> int:
    """As many of ``shares`` as the cash pays for, fees included."""
    def total(n: int) -> float:
        value = n * unit
        return value + sum(costs(value, currency))
    if unit <= 0:
        return 0
    n = min(shares, math.floor(cash / (unit * buy_room(currency))))
    while n > 0 and total(n) > cash + 1e-9:  # the minimum courtage can make the estimate too high
        n -= 1
    return max(n, 0)


def _closes(prices: dict[int, dict[date, tuple]]) -> Callable[[int, date], float]:
    """A stock's latest closing price on or before a day: one that did not trade kept its price."""
    index = {i: (sorted(series), [series[d][1] for d in sorted(series)]) for i, series in prices.items()}

    def close(instrument_id: int, day: date) -> float:
        days, values = index.get(instrument_id, ([], []))
        k = bisect_right(days, day)
        return values[k - 1] if k else 0.0
    return close


def _rate(fx: dict[str, list[tuple[date, float]]], currency: str | None, day: date) -> float | None:
    """NOK per unit of ``currency`` at the latest daily close on or before ``day`` (the first one, before that)."""
    if currency in (None, "NOK"):
        return 1.0
    series = fx.get(currency) or []
    i = bisect_right(series, (day, math.inf))
    return series[i - 1][1] if i else (series[0][1] if series else None)


# Reading the stored data

def _orders(store: Store) -> list[dict[str, Any]]:
    t = store.table("paper_orders")
    return [{**r, "decided_at": _utc(r["decided_at"])}
            for r in store.query(select(t).where(t.c.account == ACCOUNT).order_by(t.c.decided_at, t.c.id))]


def _prices(store: Store, stocks: dict[int, dict[str, Any]], since: date) -> dict[int, dict[date, tuple]]:
    """(opening, closing) price per stock and trading day: Nordnet's snapshots after the close, as the advisor uses,
    with Yahoo's daily bars for days without one (a missed evening) and for a missing opening price."""
    out: dict[int, dict[date, tuple]] = defaultdict(dict)
    t = store.table("nordnet_observations")
    start = datetime.combine(since, time(0), NORDIC_TZ)
    for r in store.query(select(t.c.instrument_id, t.c.observed_at, t.c.tick_at, t.c.open, t.c.last)
                         .where(t.c.instrument_id.in_(list(stocks)), t.c.observed_at >= start, t.c.last > 0)
                         .order_by(t.c.observed_at)):
        day = trading_day(r["tick_at"], r["observed_at"])
        observed = _utc(r["observed_at"]).astimezone(NORDIC_TZ)
        if observed.date() > day or observed.time() >= AFTER_CLOSE:
            out[r["instrument_id"]][day] = (r["open"] or None, r["last"])
    symbols = {yahoo_symbol(s["symbol"], s["country"]): i for i, s in stocks.items()
               if s["symbol"] and s["country"] in EXCHANGE_SUFFIX}
    bars = store.table("price_bars")
    for r in store.query(select(bars.c.symbol, bars.c.ts, bars.c.open, bars.c.close)
                         .where(bars.c.symbol.in_(list(symbols)), bars.c.interval == "1d",
                                bars.c.ts >= int(start.timestamp()))):
        instrument_id, day = symbols[r["symbol"]], datetime.fromtimestamp(r["ts"], NORDIC_TZ).date()
        seen = out[instrument_id].get(day)
        if seen is None and r["close"]:
            out[instrument_id][day] = (r["open"] or None, r["close"])
        elif seen is not None and seen[0] is None and r["open"]:
            out[instrument_id][day] = (r["open"], seen[1])
    return out


def _fx(store: Store) -> dict[str, list[tuple[date, float]]]:
    bars = store.table("price_bars")
    out = {}
    for currency, symbol in FX_PAIRS.items():
        rows = store.query(select(bars.c.ts, bars.c.close).where(bars.c.symbol == symbol, bars.c.interval == "1d")
                           .order_by(bars.c.ts))
        # Yahoo stamps currency bars at midnight in London, which is the right day in Norwegian time too.
        out[currency] = [(datetime.fromtimestamp(r["ts"], NORDIC_TZ).date(), r["close"]) for r in rows if r["close"]]
    return out


def _dividends(store: Store, stocks: dict[int, dict[str, Any]], since: date) -> list[tuple[date, int, float, str]]:
    symbols = {yahoo_symbol(s["symbol"], s["country"]): (i, s["currency"]) for i, s in stocks.items()
               if s["symbol"] and s["country"] in EXCHANGE_SUFFIX}
    d = store.table("dividends")
    rows = store.query(select(d.c.symbol, d.c.ex_date, d.c.amount, d.c.currency)
                       .where(d.c.symbol.in_(list(symbols)), d.c.ex_date > since, d.c.amount > 0))
    return sorted((r["ex_date"], symbols[r["symbol"]][0], r["amount"], r["currency"] or symbols[r["symbol"]][1])
                  for r in rows)


# The evening's decisions

@dataclass
class Pick:
    """A stock as the advisor saw it tonight."""
    instrument_id: int
    symbol: str
    name: str
    country: str
    currency: str | None
    price: float | None  # tonight's closing price, in the stock's currency
    fx: float | None  # NOK per unit of that currency
    eligible: bool = True
    rank: int | None = None
    score: float | None = None
    exclusion: str | None = None
    signal_type: str | None = None
    reason: str | None = None


@dataclass
class Scan:
    recommendation_id: int | None
    picks: list[Pick]  # every stock considered: the long-term ranking (rebalance evenings only)
    signals: list[Pick]  # short-term buy candidates, best first


Scanner = Callable[[Store, Policy, bool], Scan]


def scan(store: Store, policy: Policy, rebalance: bool) -> Scan:
    """What the advisor says tonight. On a rebalance evening it is a whole recommendation, logged like any other,
    so the track record measures it; on the others only the short-term signals are worked out, and not stored."""
    if not rebalance:
        asof = utcnow()
        stocks = build_features(store, asof, policy.countries)
        scored = score_stocks(stocks, load_fx(store, asof), target_position=policy.target_position,
                              ask_only=policy.ask_only)
        signals, _ = short_sleeve(scored, policy)
        return Scan(None, [], [Pick(s.stock.instrument_id, s.stock.symbol, s.stock.name, s.stock.country,
                                    s.stock.currency, s.stock.price, s.scored.fx, score=s.scored.score,
                                    rank=s.scored.rank, signal_type=s.signal, reason=s.description)
                               for s in signals if s.direction > 0])
    rec_id = recommend.create(store, policy, origin=ORIGIN)
    recommend.run(store, rec_id)
    rec = store.get("recommendations", id=rec_id)
    if rec["status"] != "done":
        raise RuntimeError(f"anbefaling {rec_id} feilet: {rec['error']}")
    s, sig = store.table("scores"), store.table("short_signals")
    picks = {r["instrument_id"]: Pick(r["instrument_id"], r["symbol"], r["name"], r["country"], r["currency"],
                                      r["ref_price"], r["fx_rate"], bool(r["eligible"]), r["rank"], r["score"],
                                      r["exclusion"])
             for r in store.query(select(s).where(s.c.recommendation_id == rec_id))}
    signals = [replace(picks[r["instrument_id"]], signal_type=r["signal_type"], reason=r["description"])
               for r in store.query(select(sig).where(sig.c.recommendation_id == rec_id, sig.c.direction > 0))
               if r["instrument_id"] in picks]
    # As the advisor ranks them: new buyback programmes first, then the long-term score.
    signals.sort(key=lambda p: (p.signal_type != "buyback_start", -(p.score or 0)))
    return Scan(rec_id, list(picks.values()), signals)


def decide(store: Store, now: datetime | None = None, *, scanner: Scanner = scan) -> dict[str, Any]:
    """The evening's orders, for the next opening. Returns what happened; "ok" is False if it should be tried
    again later (tonight's closing prices are not in yet)."""
    now = now or utcnow()
    today = now.astimezone(NORDIC_TZ).date()
    if store.get("paper_days", account=ACCOUNT, decided_on=today):
        return {"ok": True, "note": "Allerede bestemt i kveld"}
    if not any(trading_hours(country, today) for country in MARKETS):
        return {"ok": True, "note": "Børsene var stengt i dag"}
    if not _closed_today(store, today):
        return {"ok": False, "note": "Mangler sluttkurser fra i dag"}
    state = account(store, now)
    rebalance = _rebalance_due(store, today)
    policy = Policy(account_value=state["equity"], **POLICY)
    tonight = scanner(store, policy, rebalance)
    orders, notes = _plan(state, policy, tonight, rebalance)
    _save(store, today, now, rebalance, tonight, state, orders, notes)
    return {"ok": True, "rebalance": rebalance, "orders": len(orders), "recommendation_id": tonight.recommendation_id,
            "notes": notes}


def _plan(state: dict[str, Any], policy: Policy, tonight: Scan,
          rebalance: bool) -> tuple[list[dict[str, Any]], list[str]]:
    held = {p["instrument_id"]: p for p in state["positions"]}
    taken = set(held) | {o["instrument_id"] for o in state["pending"]}
    orders: list[dict[str, Any]] = []
    notes: list[str] = []
    cash = state["cash"]

    def sell(position: dict[str, Any], reason: str, pick: Pick | None = None) -> None:
        nonlocal cash
        value = position["value"]
        cash += value - sum(costs(value, position["currency"]))
        orders.append({**{k: position[k] for k in ("instrument_id", "symbol", "name", "country", "currency")},
                       "side": "sell", "shares": position["shares"], "sleeve": position["sleeve"], "reason": reason,
                       "rank": pick.rank if pick else None, "score": pick.score if pick else None,
                       "ref_price": position["price"], "fx_rate": position["rate"],
                       "signal_type": position["signal_type"]})

    def buy(pick: Pick, sleeve: str, amount: float, reason: str) -> bool:
        nonlocal cash
        unit, room = (pick.price or 0) * (pick.fx or 0), buy_room(pick.currency)
        shares = math.floor(min(amount, cash) / (unit * room)) if unit > 0 else 0
        if shares == 0:
            return False
        cash -= shares * unit * room
        orders.append({"instrument_id": pick.instrument_id, "symbol": pick.symbol, "name": pick.name,
                       "country": pick.country, "currency": pick.currency, "side": "buy", "shares": shares,
                       "sleeve": sleeve, "reason": reason, "rank": pick.rank, "score": pick.score,
                       "ref_price": pick.price, "fx_rate": pick.fx, "signal_type": pick.signal_type})
        taken.add(pick.instrument_id)
        return True

    short_held = [p for p in held.values() if p["sleeve"] == "short"]
    for p in short_held:
        if p["held_days"] >= SHORT_HOLD:
            sell(p, f"Holdt i {SHORT_HOLD} handelsdager")
    selling = {o["instrument_id"] for o in orders}
    short_kept = [p for p in short_held if p["instrument_id"] not in selling]

    if rebalance:
        n = policy.position_count
        ranked = {p.instrument_id: p for p in tonight.picks}
        eligible = sorted((p for p in tonight.picks if p.eligible and p.rank), key=lambda p: p.rank)
        kept = 0
        for p in (p for p in held.values() if p["sleeve"] == "long"):
            pick = ranked.get(p["instrument_id"])
            if pick and pick.eligible and pick.rank and pick.rank <= HOLD_RANK * n:
                kept += 1
            elif pick and pick.eligible and pick.rank:
                sell(p, f"Falt til plass {pick.rank}; beholdes bare til og med plass {HOLD_RANK * n}", pick)
            else:
                sell(p, f"Ikke lenger kvalifisert: {pick.exclusion}" if pick and pick.exclusion
                     else "Ikke med i rådgiverens univers", pick)
        # The short-term part's money stays free for its own trades.
        reserve = max(0.0, policy.short_capital - sum(p["value"] for p in short_kept))
        cash -= reserve
        for pick in eligible:
            if kept >= n:
                break
            if pick.instrument_id not in taken and buy(pick, "long", policy.target_position,
                                                       f"Plass {pick.rank} av {len(eligible)} i rangeringen"):
                kept += 1
        cash += reserve
        if kept < n:
            notes.append(f"{kept} av {n} langsiktige posisjoner: for lite penger eller for få kvalifiserte aksjer.")

    slots = min(MAX_SHORT_POSITIONS, math.floor(policy.short_capital / policy.min_position))
    free, new = slots - len(short_kept), 0
    for pick in tonight.signals:
        if free <= 0 or new >= MAX_NEW_SHORT:
            break
        if pick.instrument_id not in taken and buy(pick, "short", policy.short_capital / slots,
                                                   pick.reason or "Kortsiktig signal"):
            free, new = free - 1, new + 1
    skipped = [p for p in tonight.signals if p.instrument_id not in taken]
    if skipped:
        notes.append(f"{len(skipped)} kortsiktige signaler ble ikke kjøpt: ingen ledig plass eller for lite penger.")
    return orders, notes


def _save(store: Store, today: date, now: datetime, rebalance: bool, tonight: Scan, state: dict[str, Any],
          orders: list[dict[str, Any]], notes: list[str]) -> None:
    with store.engine.begin() as conn:
        conn.execute(insert(store.table("paper_days")).values(
            account=ACCOUNT, decided_on=today, decided_at=now, rebalance=rebalance,
            recommendation_id=tonight.recommendation_id, model_version=MODEL_VERSION, equity=state["equity"],
            cash=state["cash"], orders=len(orders), notes=notes))
        if orders:
            conn.execute(insert(store.table("paper_orders")), [
                {**o, "account": ACCOUNT, "decided_on": today, "decided_at": now,
                 "recommendation_id": tonight.recommendation_id} for o in orders])


def _closed_today(store: Store, today: date) -> bool:
    """Whether a Nordnet snapshot taken after today's close shows trades from today."""
    t = store.table("nordnet_observations")
    after = datetime.combine(today, AFTER_CLOSE, NORDIC_TZ)
    tick = store.scalar(select(func.max(t.c.tick_at)).where(t.c.observed_at >= after))
    return tick is not None and trading_day(tick, after) == today


def _rebalance_due(store: Store, today: date) -> bool:
    d = store.table("paper_days")
    last = store.scalar(select(func.max(d.c.decided_on)).where(d.c.account == ACCOUNT, d.c.rebalance.is_(True)))
    return last is None or (last.year, last.month) != (today.year, today.month)


def days(store: Store, limit: int = 30) -> list[dict[str, Any]]:
    """The latest evenings' decisions, newest first."""
    d = store.table("paper_days")
    return [dict(r) for r in store.query(select(d).where(d.c.account == ACCOUNT)
                                         .order_by(d.c.decided_on.desc()).limit(limit))]


def _utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
