"""The play-money crypto account: Firi's prices, the daily closes, the trend rule, rebalancing and the page."""

import csv
import io
import re
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from nordic_signals import crypto
from nordic_signals.collectors.crypto import CryptoCollector
from nordic_signals.web import app as web
from nordic_signals.web import crypto_page

T0 = crypto.STARTED_AT  # Tuesday 6 October 2026, 00:00 UTC
DEPTH = "https://api.firi.com/v2/markets/"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
SPREAD = 0.01  # between the best bid and ask
KEPT = 1 / ((1 + SPREAD / 2) * (1 + crypto.FEE))  # what a purchase is worth at the middle price, per krone spent


def mids(**changes):
    prices = {"BTCNOK": 800_000.0, "ETHNOK": 25_000.0, "XRPNOK": 14.0, "ADANOK": 2.5, "SOLNOK": 1_000.0}
    return {**prices, **{f"{symbol}NOK": price for symbol, price in changes.items()}}


def quotes(store, at, prices):
    with store.engine.begin() as conn:
        conn.execute(store.table("crypto_quotes").insert(), [
            {"market": m, "at": at, "bid": p * (1 - SPREAD / 2), "ask": p * (1 + SPREAD / 2)} for m, p in prices.items()])


def closes(store, symbol, last_day, values):
    """Daily closes in USD, the last on ``last_day``."""
    days = [last_day - timedelta(days=i) for i in range(len(values))][::-1]
    with store.engine.begin() as conn:
        conn.execute(store.table("price_bars").insert(), [
            {"symbol": symbol, "interval": "1d", "ts": int(datetime.combine(d, time(0), timezone.utc).timestamp()),
             "close": v, "currency": "USD"} for d, v in zip(days, values, strict=True)])


def rising(store, last_day, coins=crypto.COINS):
    """Closes rising steadily up to ``last_day``: well above their 200-day average."""
    for c in coins:
        closes(store, c.yahoo, last_day, [100.0 + i for i in range(240)])


def pump(store, *points, version="pf3"):
    """The pump.fun main account's value in SOL."""
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_equity").insert(), [
            {"at": at, "cash": equity, "positions": 0.0, "equity": equity, "open_positions": 0,
             "screen_version": v, "account": "take_profit_100"}
            for at, equity, v in ((p[0], p[1], p[2] if len(p) > 2 else version) for p in points)])


def trades(account, since=None):
    return [(t["side"], t["asset"]) for t in account["trades"] if since is None or t["at"] >= since]


# When it decides

def test_decisions_are_on_mondays_and_the_first_of_the_month():
    until = datetime(2026, 11, 3, tzinfo=timezone.utc)
    days = [(at.date(), kind) for at, kind in crypto.decisions(until, trend=True)]
    assert days == [(date(2026, 10, 6), "start"), (date(2026, 10, 12), "week"), (date(2026, 10, 19), "week"),
                    (date(2026, 10, 26), "week"), (date(2026, 11, 1), "month"), (date(2026, 11, 2), "week")]
    assert [kind for _, kind in crypto.decisions(until, trend=False)] == ["start", "month"]
    assert crypto.decisions(T0 - timedelta(hours=1), trend=True) == []
    assert crypto.upcoming(T0 - timedelta(hours=1)) == {"start": T0}
    assert crypto.upcoming(T0 + timedelta(hours=12)) == {"week": datetime(2026, 10, 12, tzinfo=timezone.utc),
                                                         "month": datetime(2026, 11, 1, tzinfo=timezone.utc)}


def test_the_trend_rule_compares_the_latest_close_with_its_200_day_average():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(201)]
    view = crypto.trend((days, [100.0] * 200 + [110.0]), date(2026, 12, 1))
    assert view["above"] and view["day"] == days[-1] and view["average"] == pytest.approx(100.05)
    assert crypto.trend((days, [100.0] * 200 + [90.0]), date(2026, 12, 1))["above"] is False
    assert crypto.trend((days, [100.0] * 200 + [500.0]), days[-1])["close"] == 100.0  # not that day's own close
    assert crypto.trend((days[:199], [100.0] * 199), date(2026, 12, 1)) is None and crypto.trend(None, T0) is None


# The account

def test_the_start_buys_each_part_at_firis_prices(store):
    rising(store, date(2026, 10, 5))
    pump(store, (T0 - timedelta(minutes=10), 10.0), (T0 + timedelta(minutes=30), 12.0))
    quotes(store, T0 + timedelta(minutes=5), mids())
    quotes(store, T0 + timedelta(hours=1), mids())

    a = crypto.account(store, T0 + timedelta(hours=2))

    assert a["started_at"] == T0 + timedelta(minutes=5) and a["pending"] == []
    assert trades(a) == [("buy", "BTC"), ("buy", "ETH"), ("buy", "XRP"), ("buy", "ADA"), ("buy", "SOL"),
                         ("buy", "pump.fun")]
    btc = a["trades"][0]
    assert btc["cash"] == pytest.approx(-25_000) and btc["price"] == 800_000 * (1 + SPREAD / 2)
    assert btc["qty"] == pytest.approx(25_000 / (800_000 * (1 + SPREAD / 2) * (1 + crypto.FEE)))
    assert btc["fee"] == pytest.approx(btc["value"] * crypto.FEE) and btc["spread"] == pytest.approx(btc["qty"] * 4_000)
    assert btc["reason"] == "Start: 25 % av kontoen"
    sol = 20_000 / (1_005 * (1 + crypto.FEE))
    assert a["trades"][-1]["qty"] == pytest.approx(sol) and a["withdrawals"] == pytest.approx(crypto.SOL_WITHDRAWAL * 1_000)
    assert a["cash"] == pytest.approx(0, abs=1e-6)
    # The pump.fun part is the SOL that reached the wallet, and has risen 20 % with the pump.fun account since.
    assert a["pumpfun"]["sol"] == pytest.approx((sol - crypto.SOL_WITHDRAWAL) * 1.2)
    coins = {c["symbol"]: c for c in a["coins"]}
    assert coins["BTC"]["value"] == pytest.approx(25_000 * KEPT) and coins["XRP"]["value"] == pytest.approx(10_000 * KEPT)
    assert coins["BTC"]["result"] == pytest.approx(25_000 * KEPT - 25_000) and coins["BTC"]["wanted"] is True
    assert [p["key"] for p in a["parts"]] == ["big", "small", "pumpfun"]
    assert a["parts"][0]["value"] == pytest.approx(50_000 * KEPT)
    assert [at for at, _ in a["history"]] == [T0 + timedelta(minutes=5), T0 + timedelta(hours=1)]
    assert a["costs"] == pytest.approx(a["fees"] + a["spread"] + a["withdrawals"])


def test_without_prices_after_a_decision_it_waits(store):
    rising(store, date(2026, 10, 5))
    quotes(store, T0 - timedelta(minutes=10), mids())  # before the start: shown, but not traded at
    a = crypto.account(store, T0 + timedelta(hours=1))
    assert a["pending"] == [(T0, "start")] and a["trades"] == [] and a["started_at"] is None
    assert a["equity"] == crypto.START and a["valued_at"] == T0 - timedelta(minutes=10)
    assert a["coins"][0]["price"] == 800_000 and a["history"] == []


def test_the_trend_rule_sells_below_the_average_and_buys_back(store):
    last = date(2026, 10, 18)
    btc = [100.0 + i for i in range(240)]
    btc[-8:-1] = [50.0] * 7  # 11 to 17 October: under its average
    btc[-1] = 1_000.0  # Sunday 18 October: above again
    closes(store, "BTC-USD", last, btc)
    rising(store, last, coins=crypto.COINS[1:])
    for at, prices in ((T0 + timedelta(minutes=5), mids()),
                       (datetime(2026, 10, 12, 0, 5, tzinfo=timezone.utc), mids(BTC=700_000.0)),
                       (datetime(2026, 10, 19, 0, 5, tzinfo=timezone.utc), mids(BTC=900_000.0))):
        quotes(store, at, prices)

    books = crypto.accounts(store, datetime(2026, 10, 20, tzinfo=timezone.utc))

    main, hold = books["trend"], books["hold"]
    sold, bought = main["trades"][6:]
    assert (sold["side"], sold["asset"], sold["kind"]) == ("sell", "BTC", "week")
    assert sold["at"] == datetime(2026, 10, 12, 0, 5, tzinfo=timezone.utc) and sold["price"] == 700_000 * (1 - SPREAD / 2)
    assert sold["reason"].startswith("Under snittet for 200 dager (-")
    assert sold["result"] == pytest.approx(sold["cash"] - 25_000)
    assert (bought["side"], bought["asset"]) == ("buy", "BTC") and bought["reason"].startswith("Over snittet for 200 dager igjen (+")
    assert bought["cash"] == pytest.approx(-sold["cash"])  # all the money waiting for it: less than its 25 % now
    assert [c["kind"] for c in main["checks"]] == ["start", "week", "week"]
    assert main["checks"][1]["wanted"]["BTC"] is False and main["checks"][1]["trades"] == 1
    assert {c["symbol"]: c["wanted"] for c in main["coins"]}["BTC"] is True
    assert trades(hold) == trades(main)[:6] and [c["kind"] for c in hold["checks"]] == ["start"]  # the yardstick holds on


def test_the_month_rebalances_what_is_more_than_a_fifth_off(store):
    rising(store, date(2026, 10, 31))
    pump(store, (T0 - timedelta(hours=1), 10.0), (datetime(2026, 10, 31, tzinfo=timezone.utc), 5.0))
    quotes(store, T0 + timedelta(minutes=5), mids())
    month = datetime(2026, 11, 1, 0, 5, tzinfo=timezone.utc)
    quotes(store, month, mids(BTC=1_600_000.0))  # Bitcoin has doubled, the pump.fun part halved

    a = crypto.account(store, month + timedelta(hours=1))

    # The weekly checks found nothing to do and waited for prices with the month's; Ether and the smaller coins are
    # within a fifth of their share, so only Bitcoin and the pump.fun part are moved.
    assert [c["kind"] for c in a["checks"]] == ["start", "week", "week", "week", "month"]
    assert trades(a, since=month) == [("sell", "BTC"), ("buy", "pump.fun")]
    trim, top_up = a["trades"][-2:]
    assert trim["reason"].startswith("Månedlig rebalansering fra 4") and top_up["withdrawal"] == pytest.approx(50.0)
    shares = {c["symbol"]: c["share"] for c in a["coins"]}
    assert shares["BTC"] == pytest.approx(0.25, abs=0.002) and shares["ETH"] == pytest.approx(0.217, abs=0.002)
    assert a["pumpfun"]["share"] == pytest.approx(0.2, abs=0.002) and a["cash"] > 0


def test_the_pump_fun_index_carries_on_across_versions(store):
    pump(store, (T0, 10.0), (T0 + timedelta(hours=1), 12.0),
         (T0 + timedelta(hours=2), 10.0, "pf4"), (T0 + timedelta(hours=3), 5.0, "pf4"))
    times, index = crypto._pump_index(store, T0 - timedelta(days=1))
    assert index == pytest.approx([1.0, 1.2, 1.2, 0.6]) and times[-1] == T0 + timedelta(hours=3)


# Collecting the prices

def depth(bid, ask):
    """A Firi order book, best prices not first."""
    return {"bids": [[f"{bid * 0.99:.2f}", "2.0"], [f"{bid:.2f}", "1.0"]],
            "asks": [[f"{ask * 1.01:.2f}", "2.0"], [f"{ask:.2f}", "1.0"]]}


class Sources:
    """Firi's order books and Yahoo's daily bars, as of ``now``."""

    def __init__(self, server, now):
        self.now, self.empty, self.ranges = now, set(), []
        server.add_prefix("GET", DEPTH, self.depth)
        server.add_prefix("GET", CHART, self.chart)

    def depth(self, request):
        market = request.url.path.split("/")[-2]
        if market in self.empty:
            return httpx.Response(200, json={"bids": [["1.0", "1.0"]], "asks": []})
        price = mids()[market]
        return httpx.Response(200, json=depth(price * 0.995, price * 1.005))

    def chart(self, request):
        symbol, days = request.url.path.rsplit("/", 1)[-1], {"5d": 5, "1y": 365}[request.url.params["range"]]
        self.ranges.append((symbol, request.url.params["range"]))
        today = datetime.combine(self.now.date(), time(0), timezone.utc)  # its bar is not over yet
        stamps = [int((today - timedelta(days=i)).timestamp()) for i in range(days)][::-1]
        prices = [100.0 + i for i in range(days)]
        return httpx.Response(200, json={"chart": {"error": None, "result": [{
            "meta": {"symbol": symbol, "currency": "USD", "dataGranularity": "1d"}, "timestamp": stamps,
            "indicators": {"quote": [{"open": prices, "high": prices, "low": prices, "close": prices,
                                      "volume": [0] * days}]}}]}})


def collect(server, store, now):
    with server.client() as client:
        return CryptoCollector(client, store).run(now=now)


def bar_count(store, symbol):
    bars = store.table("price_bars")
    return store.scalar(select(func.count()).select_from(bars).where(bars.c.symbol == symbol))


def test_the_collector_stores_firis_best_prices_and_finished_days(server, store):
    now = T0 + timedelta(minutes=5)
    sources = Sources(server, now)
    sources.empty = {"ADANOK"}

    summary = collect(server, store, now)

    q = store.table("crypto_quotes")
    rows = {r["market"]: r for r in store.query(select(q))}
    assert sorted(rows) == ["BTCNOK", "ETHNOK", "SOLNOK", "XRPNOK"] and summary.warnings == ["ADANOK: ingen kurs fra Firi"]
    assert (rows["BTCNOK"]["bid"], rows["BTCNOK"]["ask"]) == (796_000.0, 804_000.0)
    assert sources.ranges == [(c.yahoo, "1y") for c in crypto.COINS]  # no history yet: a year
    assert bar_count(store, "BTC-USD") == 364  # today's bar is not over, so it is not kept

    sources.ranges.clear()
    collect(server, store, now + timedelta(minutes=15))
    assert sources.ranges == []  # yesterday's close is in
    sources.now = now + timedelta(days=1)
    collect(server, store, sources.now)
    assert sources.ranges == [(c.yahoo, "5d") for c in crypto.COINS] and bar_count(store, "BTC-USD") == 365


def test_old_snapshots_keep_the_first_complete_run_of_each_hour(server, store):
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    hour = now - timedelta(days=8)
    every = mids()
    some = {m: p for m, p in every.items() if m != "ADANOK"}
    for minutes, prices in ((0, some), (15, every), (30, every), (60, every), (75, some)):
        quotes(store, hour + timedelta(minutes=minutes), prices)
    quotes(store, now - timedelta(days=1), every)
    quotes(store, now - timedelta(days=1) + timedelta(minutes=15), every)  # recent: all kept

    with server.client() as client:
        CryptoCollector(client, store)._thin(now)

    q = store.table("crypto_quotes")
    left = sorted({crypto._aware(r["at"]) for r in store.query(select(q.c.at))})
    assert left == [hour + timedelta(minutes=15), hour + timedelta(minutes=60),
                    now - timedelta(days=1), now - timedelta(days=1) + timedelta(minutes=15)]


# The page

def page_client(db_url, monkeypatch, now):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.setenv("SCHEDULER", "off")
    monkeypatch.setattr(crypto_page, "utcnow", lambda: now)
    return TestClient(web.create_app(db_url))


def test_the_page_before_the_start(store, db_url, monkeypatch):
    with page_client(db_url, monkeypatch, T0 - timedelta(hours=1)) as client:
        page = client.get("/krypto").text
        version = client.get("/krypto/version").json()
    assert "Kontoen starter" in page and "ikke kjøpt ennå" in page and 'href="/krypto" class="active"' in page
    assert 'id="pf-tape" class="tape" data-live aria-hidden="true" hidden' in page  # no prices yet
    assert version == {"v": "0.0", "updated": None}


def test_the_page_and_its_log(store, db_url, monkeypatch):
    rising(store, date(2026, 10, 5))
    pump(store, (T0 - timedelta(minutes=10), 10.0))
    quotes(store, T0 + timedelta(minutes=5), mids())
    quotes(store, T0 + timedelta(hours=1), mids(BTC=820_000.0))
    with page_client(db_url, monkeypatch, T0 + timedelta(minutes=70)) as client:  # the last prices are 10 minutes old
        page = client.get("/krypto").text
        spreadsheet = client.get("/krypto/export.csv")
        everything = client.get("/krypto/export.json")

    assert '<body class="degen">' in page and 'data-version-url="/krypto/version"' in page
    assert '<span class="state">Live</span>' in page and 'id="pf-tape" class="tape" data-live aria-hidden="true">' in page
    assert "📈 Trendregelen" in page and "💎 Kjøp og hold" in page and "🎰 pump.fun-delen" in page
    assert page.count('<article class="pos ') == 6 and "$BTC · Store mynter" in page and "SOL i lommebok" in page
    assert '<span class="chip owned">eies</span>' in page and "Start: 25 % av kontoen" in page
    assert 'class="chart' in page and "Ukesjekk" in page and "/krypto/export.json" in page
    assert 'data-periode="alt" class="on"' in page and 'href="/pumpfun" class=' not in page  # no pump.fun tab
    assert re.fullmatch(r'attachment; filename="krypto-\d{4}-\d\d-\d\d-\d{4}\.csv"',
                        spreadsheet.headers["content-disposition"])
    header, *rows = csv.reader(io.StringIO(spreadsheet.text.lstrip("﻿")), delimiter=";")
    assert header[:3] == ["Konto", "Tidspunkt (norsk tid)", "Bestemt (norsk tid)"] and len(rows) == 12
    first = dict(zip(header, rows[0], strict=True))
    assert first["Konto"] == "Trendregelen" and first["Mynt"] == "BTC" and first["Tidspunkt (norsk tid)"] == "2026-10-06 02:05:00"
    assert first["Beløp på kontoen (NOK)"] == "-25000,00"
    data = everything.json()
    assert list(data) == ["meta", "trend", "hold"] and list(data["trend"]) == ["summary", "trades", "checks", "equity"]
    assert len(data["trend"]["trades"]) == 6 and len(data["trend"]["equity"]) == 2
    assert data["meta"]["fees"]["trade"] == crypto.FEE and data["trend"]["checks"][0]["views"]["BTC"]["above"] is True


def test_the_version_changes_with_new_prices(store):
    assert crypto.freshness(store) == ("0.0", None)
    quotes(store, T0, mids())
    first, updated = crypto.freshness(store)
    pump(store, (T0 + timedelta(minutes=5), 10.0))
    second, later = crypto.freshness(store)
    assert first != second and updated == T0 and later == T0 + timedelta(minutes=5)


def test_the_cards_show_each_coin_over_the_last_day(store):
    rising(store, date(2026, 10, 6))
    pump(store, (T0 - timedelta(minutes=10), 10.0), (T0 + timedelta(hours=20), 15.0))
    quotes(store, T0 + timedelta(minutes=5), mids())
    quotes(store, T0 + timedelta(hours=25), mids(BTC=880_000.0, SOL=900.0))

    ctx = crypto_page.context(store, "alt", T0 + timedelta(hours=25, minutes=5))

    cards = {c["symbol"]: c for c in ctx["cards"]}
    assert list(cards) == ["BTC", "ETH", "XRP", "ADA", "SOL", "pump.fun"]
    assert cards["BTC"]["day"] == pytest.approx(0.10) and cards["ETH"]["day"] == pytest.approx(0)
    assert cards["pump.fun"]["day"] == pytest.approx(1.5 * 0.9 - 1)  # the pump.fun account and SOL's price
    assert cards["BTC"]["since_start"] == pytest.approx(0.10) and 'class="chart spark spark-card"' in cards["BTC"]["chart"]
    assert [t["symbol"] for t in ctx["tape"][:6]] == list(cards) and ctx["held"] == 5
    assert crypto_page.context(store, "24t", T0 + timedelta(hours=25, minutes=5))["history"] == [
        (T0 + timedelta(hours=25), ctx["a"]["equity"])]  # one point in the last 24 hours: no chart
