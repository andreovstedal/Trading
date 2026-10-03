"""The pump.fun measurement: discovery, scoring, following the price, labels and results."""

import csv
import html
import io
import json
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import FakeServer
from sqlalchemy import select

from nordic_signals import cli, jobs, pumpfun
from nordic_signals.collectors.pumpfun import PumpFunCollector
from nordic_signals.web import app as web

COINS = "https://frontend-api-v3.pump.fun/coins"
DEX = "https://api.dexscreener.com/tokens/v1/solana/"
RPC = "https://api.mainnet-beta.solana.com/"
T0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
OLD_WALLET = [int((T0 - timedelta(days=30)).timestamp()), int((T0 - timedelta(days=29)).timestamp())]
P = 5e-8  # a price when scored, in SOL: 1.8 times pump.fun's launch price, so real money but not yet doubled


def coin(mint, creator, minutes_before=1, **extra):
    created = T0 - timedelta(minutes=minutes_before)
    return {"mint": mint, "name": f"{mint} coin", "symbol": mint.upper(), "creator": creator,
            "created_timestamp": int(created.timestamp() * 1000), "chain_id": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
            "market_cap": 30.0, "usd_market_cap": 3600.0, "ath_market_cap": 3600.0, "complete": False,
            "associated_bonding_curve": f"{mint}-curve", **extra}


class Market:
    """DexScreener and Solana RPC answers that a test can change between runs."""

    def __init__(self, server: FakeServer):
        self.prices: dict[str, float] = {}
        self.untraded: set[str] = set()  # no trades in the last 5 minutes
        self.profiles: set[str] = set()  # a paid DexScreener token profile
        self.boosts: dict[str, int] = {}  # active paid DexScreener boosts
        self.dex: dict[str, str] = {}
        self.wallets: dict[str, list[int]] = {}  # creator -> blockTimes of its transactions
        self.holders: dict[str, list[tuple[str, float]]] = {}
        server.add_prefix("GET", DEX, self.pairs)
        server.add("POST", RPC, self.rpc)
        server.add("POST", "https://rpc.example/", self.rpc)

    def pairs(self, request):
        mints = request.url.path.rsplit("/", 1)[-1].split(",")
        return httpx.Response(200, json=[{
            "chainId": "solana", "dexId": self.dex.get(m, "pumpfun"), "baseToken": {"address": m},
            "quoteToken": {"symbol": "SOL"}, "priceNative": str(self.prices[m]), "marketCap": 4000.0,
            "txns": {"m5": {"buys": 0, "sells": 0} if m in self.untraded else {"buys": 3, "sells": 1},
                     "h1": {"buys": 20, "sells": 9}},
            "volume": {"h1": 900.0, "h24": 2000.0},
            **({"info": {"socials": [{"type": "twitter", "url": "https://x.com/example"}]}} if m in self.profiles else {}),
            **({"boosts": {"active": self.boosts[m]}} if m in self.boosts else {}),
        } for m in mints if m in self.prices])

    def rpc(self, request):
        body = json.loads(request.content)
        method, params = body["method"], body["params"]
        if method == "getSignaturesForAddress":
            result = [{"signature": f"s{i}", "blockTime": t} for i, t in enumerate(self.wallets.get(params[0], []))]
        else:  # getTokenLargestAccounts
            accounts = self.holders.get(params[0], [])
            result = {"value": [{"address": a, "uiAmountString": str(amount)} for a, amount in accounts]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def run(server, store, at, sample=20):
    with server.client() as client:
        return PumpFunCollector(client, store).run(sample=sample, now=at, rng=random.Random(0))


def tokens(store):
    t = store.table("pf_tokens")
    return {r["mint"]: dict(r) for r in store.query(select(t))}


@pytest.fixture(autouse=True)
def public_rpc(monkeypatch):
    monkeypatch.delenv("SOLANA_RPC_URL", raising=False)


def test_discovery_samples_launches_and_keeps_the_rest(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[coin(f"m{i}", f"c{i % 3}") for i in range(6)]))
    Market(server)

    run(server, store, T0, sample=2)
    run(server, store, T0 + timedelta(minutes=5), sample=2)  # the same list again: nothing new

    rows = tokens(store)
    assert len(rows) == 6
    assert sorted(r["status"] for r in rows.values()) == ["new", "new", "skipped", "skipped", "skipped", "skipped"]
    assert all(r["peak_before"] == pytest.approx(3600 * 30 / 3600 / 1e9) for r in rows.values())


def test_tokens_are_scored_followed_and_labelled(server, store):
    day_ago = int((T0 - timedelta(days=30)).timestamp())
    server.add("GET", COINS, httpx.Response(200, json=[
        coin("good", "alice"), coin("dumpy", "bob"), coin("dumpy2", "bob", minutes_before=2)]))
    market = Market(server)
    market.wallets = {"alice": [day_ago, day_ago + 3600],  # an ordinary month-old wallet
                      "bob": [int((T0 - timedelta(hours=2)).timestamp())]}  # created two hours before the launch
    market.prices = {"good": P, "dumpy": P, "dumpy2": P}

    scored = T0 + timedelta(minutes=11)
    run(server, store, T0)
    run(server, store, scored)
    rows = tokens(store)
    assert rows["good"]["status"] == "tracking" and rows["good"]["passed"] is True and rows["good"]["warnings"] == []
    assert rows["dumpy"]["warnings"] == ["serial", "fresh_wallet"] and rows["dumpy"]["passed"] is False
    assert rows["dumpy"]["features"]["creator_age_h"] == pytest.approx(2 - 1 / 60, abs=0.01)

    for after, good, dumpy in ((timedelta(hours=1), 1.2 * P, 3.0 * P), (timedelta(hours=6), 1.5 * P, 0.5 * P),
                               (timedelta(hours=24), 1.3 * P, 0.2 * P)):
        market.prices = {"good": good, "dumpy": dumpy, "dumpy2": dumpy}
        run(server, store, scored + after)

    rows = tokens(store)
    assert rows["good"]["status"] == "done" and rows["good"]["collapsed"] is False
    assert (rows["good"]["price_1h"], rows["good"]["price_6h"], rows["good"]["price_24h"]) == (1.2 * P, 1.5 * P, 1.3 * P)
    assert rows["dumpy"]["collapsed"] is True  # 0.2 is at most 10 % of the 3.0 peak
    assert rows["dumpy"]["peak_after"] == 3.0 * P and rows["dumpy"]["low_after"] == 0.2 * P
    assert (rows["dumpy"]["peak_1h"], rows["dumpy"]["peak_6h"]) == (3.0 * P, 3.0 * P)

    r = pumpfun.results(store)
    one_hour, six_hours, day = r["horizons"]
    assert r["measured"] and one_hour["measured"] == six_hours["measured"] == day["measured"] == 3
    assert one_hour["collapse_rate"] == 0 and six_hours["collapse_rate"] == 0  # 0.5 is still above 10 % of 3.0
    assert day["collapse_rate"] == pytest.approx(2 / 3)
    assert day["caught"] == 1.0 and day["kept"] == 1.0 and day["passed"] == 1 and day["passed_collapse_rate"] == 0.0
    assert day["passed_returns"]["median"] == pytest.approx(1.3 * (1 - pumpfun.FEE) ** 2 - 1)
    assert r["warnings_horizon"] == "24 timer"
    serial = next(w for w in r["warnings"] if w["key"] == "serial")
    assert (serial["n"], serial["collapse_with"], serial["collapse_without"]) == (2, 1.0, 0.0)

    # The fake-money portfolio bought the one token that passed and sold it after 24 hours.
    p = pumpfun.paper(store)
    assert p["trades"] == 1 and p["open"] == [] and p["win_rate"] == 1.0
    assert p["equity"] == pytest.approx(10 - 0.1 + 0.1 * 1.3 * (1 - pumpfun.FEE) ** 2)
    assert len(pumpfun.equity_history(store)) == 4  # recorded after each run since it bought


def test_slow_phase_and_missing_prices(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[coin("a", "x"), coin("gone", "y")]))
    market = Market(server)
    market.wallets = {"x": OLD_WALLET, "y": OLD_WALLET}
    market.prices = {"a": P, "gone": P}
    scored = T0 + timedelta(minutes=10)
    run(server, store, T0)
    run(server, store, scored)

    market.prices = {"a": 2 * P}  # "gone" disappears from DexScreener
    for minutes in range(5, 65, 5):
        run(server, store, scored + timedelta(minutes=minutes))
    rows = tokens(store)
    assert rows["gone"]["status"] == "missing" and rows["gone"]["misses"] == 12
    assert rows["a"]["price_1h"] == 2 * P

    # After 6 hours a token is checked every 30 minutes, not every run.
    run(server, store, scored + timedelta(hours=6, minutes=1))
    checked = tokens(store)["a"]["last_checked_at"]
    run(server, store, scored + timedelta(hours=6, minutes=6))
    assert tokens(store)["a"]["last_checked_at"] == checked
    run(server, store, scored + timedelta(hours=6, minutes=31))
    assert tokens(store)["a"]["last_checked_at"] != checked


def test_a_dexscreener_outage_counts_against_no_token(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[coin("a", "x")]))
    market = Market(server)
    market.wallets = {"x": OLD_WALLET}
    market.prices = {"a": P}
    scored = T0 + timedelta(minutes=10)
    run(server, store, T0)
    run(server, store, scored)

    server.prefix_routes.clear()
    server.add_prefix("GET", DEX, lambda _r: httpx.Response(503))
    for minutes in range(5, 125, 5):
        summary = run(server, store, scored + timedelta(minutes=minutes))
    row = tokens(store)["a"]
    assert row["status"] == "tracking" and row["misses"] == 0
    assert any("503" in w for w in summary.warnings)


def test_a_failed_wallet_lookup_leaves_the_token_out(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[coin("a", "x")]))
    market = Market(server)
    market.prices = {"a": P}
    server.add("POST", RPC, lambda _r: httpx.Response(429))
    scored = T0 + timedelta(minutes=10)
    run(server, store, T0)
    run(server, store, scored)

    row = tokens(store)["a"]
    assert row["complete"] is False and row["passed"] is False and row["warnings"] == []
    market.prices = {"a": 1e-8}
    run(server, store, scored + timedelta(hours=24))
    r = pumpfun.results(store)
    assert r["incomplete"] == 1 and not r["measured"]


def test_holder_concentration_needs_a_private_rpc(server, store, monkeypatch):
    monkeypatch.setenv("SOLANA_RPC_URL", "https://rpc.example/")
    server.add("GET", COINS, httpx.Response(200, json=[coin("whale", "w")]))
    market = Market(server)
    market.prices = {"whale": P}
    market.holders = {"whale": [("whale-curve", 600e6), ("big", 250e6), ("small", 100e6)]}  # the curve is not a holder

    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=10))

    row = tokens(store)["whale"]
    assert row["features"]["top10_share"] == pytest.approx(0.35)
    assert "concentrated" in row["warnings"]
    assert not any(r.url.host == "api.mainnet-beta.solana.com" for r in server.requests)


@pytest.mark.parametrize("features, expected", [
    ({"serial": 0, "creator_tx": 40, "creator_history_complete": True, "creator_age_h": 500, "creator_tx_per_h": 0.1,
      "price": P, "peak_before": P}, []),
    ({"serial": 3}, ["serial"]),
    ({"creator_tx": 12, "creator_history_complete": True, "creator_age_h": 3}, ["fresh_wallet"]),
    # A full page of transactions: the wallet's age is unknown, but its pace is a robot's.
    ({"creator_tx": 200, "creator_history_complete": False, "creator_age_h": 3, "creator_tx_per_h": 300},
     ["busy_wallet"]),
    ({"creator_tx": 8, "creator_history_complete": True, "creator_age_h": 30, "creator_tx_per_h": 80}, []),
    ({"top10_share": 0.31}, ["concentrated"]),
    ({"price": 0.5 * P, "peak_before": P}, ["dumped"]),
    ({"price": 1.99 * pumpfun.LAUNCH_PRICE}, []),
    ({"price": 2 * pumpfun.LAUNCH_PRICE}, ["pumped"]),  # already doubled since launch
    ({"price": 3 * pumpfun.LAUNCH_PRICE, "peak_before": 8 * pumpfun.LAUNCH_PRICE}, ["dumped", "pumped"]),
    ({"graduated": True}, ["instant_graduation"]),
])
def test_warning_signs(features, expected):
    assert pumpfun.warning_signs(features) == expected


def test_only_tokens_with_real_money_are_measured(server, store):
    """At pump.fun's launch price a token has had no net buying; such tokens are scored but not followed."""
    server.add("GET", COINS, httpx.Response(200, json=[coin("flat", "a"), coin("bought", "b"), coin("idle", "c")]))
    market = Market(server)
    market.wallets = {"a": OLD_WALLET, "b": OLD_WALLET, "c": OLD_WALLET}
    market.prices = {"flat": pumpfun.LAUNCH_PRICE * 1.02, "bought": pumpfun.LAUNCH_PRICE * 1.2,
                     "idle": pumpfun.LAUNCH_PRICE * 1.5}
    market.untraded = {"idle"}
    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=11))

    rows = tokens(store)
    assert (rows["bought"]["active"], rows["bought"]["passed"], rows["bought"]["status"]) == (True, True, "tracking")
    assert (rows["flat"]["active"], rows["flat"]["passed"], rows["flat"]["status"]) == (False, False, "scored")
    assert (rows["idle"]["active"], rows["idle"]["status"]) == (False, "scored")
    assert rows["flat"]["features"]["launch_multiple"] == pytest.approx(1.02)

    server.requests.clear()
    run(server, store, T0 + timedelta(minutes=16))
    followed = [m for r in server.requests if r.url.path.startswith("/tokens/v1/solana/")
                for m in r.url.path.rsplit("/", 1)[-1].split(",")]
    assert followed == ["bought"]
    r = pumpfun.results(store)
    assert r["inactive"] == 2 and r["status"]["scored"] == 2


def test_tokens_that_already_doubled_are_followed_but_not_bought(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[coin("calm", "a"), coin("doubled", "b")]))
    market = Market(server)
    market.wallets = {"a": OLD_WALLET, "b": OLD_WALLET}
    market.prices = {"calm": pumpfun.LAUNCH_PRICE * 1.9, "doubled": pumpfun.LAUNCH_PRICE * 2}
    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=11))

    rows = tokens(store)
    assert (rows["calm"]["passed"], rows["calm"]["warnings"]) == (True, [])
    assert (rows["doubled"]["passed"], rows["doubled"]["warnings"]) == (False, ["pumped"])
    assert rows["doubled"]["status"] == "tracking"  # still measured, so the page can show what the rule stopped
    assert [o["mint"] for o in pumpfun.paper(store)["open"]] == ["calm"]


def test_tokens_nobody_traded_after_scoring_are_quiet(store):
    add_token(store, "still", T0, "done", price_1h=1.0, peak_1h=1.0, price_24h=1.0, peak_after=1.0)
    add_token(store, "traded", T0, "done", price_1h=1.3, peak_1h=1.5, price_24h=1.2, peak_after=1.6)
    add_token(store, "rugged", T0, "done", price_1h=0.05, peak_1h=2.0, price_24h=0.01, peak_after=2.0, passed=False,
              collapsed=True)

    r = pumpfun.results(store)

    one_hour = r["horizons"][0]
    assert one_hour["measured"] == 3 and one_hour["collapse_rate"] == pytest.approx(1 / 3)
    assert one_hour["quiet_rate"] == pytest.approx(1 / 3)
    assert one_hour["kept"] == 1.0 and one_hour["caught"] == 1.0  # of the tokens that held up and were traded
    assert {t["mint"]: t["quiet"] for t in r["recent"]} == {"still": True, "traded": False, "rugged": False}


def test_each_screen_version_has_its_own_account_history(store):
    with store.engine.begin() as conn:  # an earlier version's portfolio
        conn.execute(store.table("pf_equity").insert().values(at=T0 - timedelta(hours=1), cash=5.0, positions=0.0,
                                                               equity=5.0, open_positions=0, screen_version="pf1"))
    add_token(store, "a", T0, "tracking", last_price=1.0)
    pumpfun.snapshot(store, T0)
    assert [v for _, v in pumpfun.equity_history(store)] == [pytest.approx(10 - 0.1 + 0.1 * (1 - pumpfun.FEE) ** 2)]


def test_cli_runs_and_logs_the_collector(server, db_url, monkeypatch):
    server.add("GET", COINS, httpx.Response(200, json=[coin("a", "x")]))
    Market(server)
    monkeypatch.setattr(cli, "PoliteClient", server.client)

    assert jobs.options_for(None, "pumpfun", {}) == {"sample": 50}  # every new launch in the list
    assert cli.main(["--db", db_url, "collect", "pumpfun", "--sample", "1"]) == 0
    from nordic_signals.store import Store
    with Store(db_url) as store:
        (run_row,) = store.last_runs()
        assert run_row["source"] == "pumpfun" and run_row["ok"] is True
        assert run_row["summary"]["tables"]["pf_tokens"]["inserted"] == 1


def test_measurement_page(server, store, db_url, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.setenv("SCHEDULER", "off")
    with TestClient(web.create_app(db_url)) as client:
        page = client.get("/pumpfun").text
    assert "Ingen målinger ennå" in page and "Ingen bags akkurat nå" in page and 'class="degen"' in page

    test_tokens_are_scored_followed_and_labelled(server, store)
    with TestClient(web.create_app(db_url)) as client:
        page = client.get("/pumpfun?periode=alt").text  # all of the account's history, whatever the date
    assert "Siste ferdig målte tokens" in page and "good coin" in page and "Kollapset" in page
    assert "Utstederen har lansert andre tokens det siste døgnet" in page
    assert "Siste salg" in page and 'class="chart spark spark-mini"' in page and "Lenker ved lanseringen" in page
    assert page.count("<svg") == 3  # account value, the sold position's path and results per trade


def add_token(store, mint, scored, status, *, price_24h=None, last_price=None, last_checked=None, passed=True,
              **columns):
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_tokens").insert().values(
            mint=mint, name=f"{mint} coin", symbol=mint.upper(), creator="c", created_at=scored, discovered_at=scored,
            sampled=True, status=status, scored_at=scored, screen_version=pumpfun.SCREEN_VERSION, active=True,
            complete=True, passed=passed, warnings=[], price_t=1.0, price_24h=price_24h, last_price=last_price,
            last_checked_at=last_checked, misses=0, **columns))


def test_paper_portfolio_replays_the_tokens_that_passed(store, monkeypatch):
    monkeypatch.setattr(pumpfun, "PAPER_START", 0.3)  # room for three positions
    add_token(store, "won", T0, "done", price_24h=2.0)
    add_token(store, "lost", T0 + timedelta(hours=1), "missing", last_checked=T0 + timedelta(hours=3))
    add_token(store, "open", T0 + timedelta(hours=2), "tracking", last_price=0.5)
    add_token(store, "late", T0 + timedelta(hours=2, minutes=30), "tracking", last_price=1.0)  # no cash left
    add_token(store, "stopped", T0, "done", price_24h=9.0, passed=False)  # never bought

    p = pumpfun.paper(store)

    kept = (1 - pumpfun.FEE) ** 2
    won = next(c for c in p["closed"] if c["mint"] == "won")
    assert won["result"] == pytest.approx(2.0 * kept - 1)
    lost = next(c for c in p["closed"] if c["mint"] == "lost")
    assert lost["lost"] and lost["result"] == -1.0
    assert [o["mint"] for o in p["open"]] == ["open"] and p["open"][0]["result"] == pytest.approx(0.5 * kept - 1)
    assert p["skipped"] == 1 and p["trades"] == 2 and p["win_rate"] == 0.5
    assert p["cash"] == pytest.approx(0.1 * 2.0 * kept)
    assert p["equity"] == pytest.approx(0.1 * 2.0 * kept + 0.1 * 0.5 * kept)
    counts = {b["label"]: b["count"] for b in p["bins"]}
    assert counts["≤ −90"] == 1 and counts["+50…+100"] == 1 and sum(counts.values()) == 2


def test_account_value_is_recorded_and_thinned_for_the_chart(store):
    pumpfun.snapshot(store, T0)
    assert pumpfun.equity_history(store) == []  # nothing bought yet, nothing recorded
    add_token(store, "a", T0, "tracking", last_price=1.0)
    for minutes in range(0, 50, 5):
        pumpfun.snapshot(store, T0 + timedelta(minutes=minutes))
    history = pumpfun.equity_history(store, points=4)
    assert len(history) <= 5 and history[-1][0] == T0 + timedelta(minutes=45)
    assert history[0][1] == pytest.approx(10 - 0.1 + 0.1 * (1 - pumpfun.FEE) ** 2)


def test_new_columns_are_added_to_an_existing_table(db_url):
    from nordic_signals.store import Store
    with Store(db_url) as store, store.engine.begin() as conn:
        conn.exec_driver_sql('ALTER TABLE pf_tokens DROP COLUMN peak_6h')
    with Store(db_url) as store:
        from sqlalchemy import inspect
        assert "peak_6h" in {c["name"] for c in inspect(store.engine).get_columns("pf_tokens")}


def test_charts():
    from nordic_signals.web import charts

    assert charts.account_chart([(T0, 10.0)], 10.0) == ""
    svg = charts.account_chart([(T0, 10.0), (T0 + timedelta(hours=1), 9.5), (T0 + timedelta(hours=2), 10.4)], 10.0)
    assert 'class="line up"' in svg and "data-points" in svg and "10,400\u00a0SOL" in svg and 'class="ref"' in svg
    assert 'clip-path="url(#acct-down)"' in svg
    live = charts.account_chart([(T0, 10.0), (T0 + timedelta(hours=1), 9.5)], 10.0, live=True)
    tooltips = json.loads(html.unescape(re.search(r"data-points='([^']*)'", live).group(1)))
    assert tooltips[-1]["t"] == "nå · 9,500\u00a0SOL" and ">nå</text>" in live and 'class="dot down"' in live

    path = [(T0, -0.025), (T0 + timedelta(hours=1), 0.4), (T0 + timedelta(hours=2), -0.3)]
    card = charts.sparkline(path, opened=T0, until=T0 + timedelta(hours=24), key="abc")
    assert 'class="chart spark spark-card"' in card and 'id="card-abc-up"' in card and 'class="dot down"' in card
    assert "nå -30\u00a0%, høyeste +40\u00a0%, laveste -30\u00a0%" in card and "data-points" in card
    mini = charts.sparkline(path[:2], opened=T0, until=T0 + timedelta(hours=24), key="abc", size="mini", closed=True)
    assert "endte på +40\u00a0%" in mini and "data-points" not in mini and 'id="mini-abc-up"' in mini
    assert charts.sparkline([], opened=T0, until=T0 + timedelta(hours=24), key="x") == ""
    bars = charts.result_bars(pumpfun._bins([-1.0, -0.95, 0.0, 0.7]))
    assert [bars.count(f'class="bar {kind}"') for kind in ("neg", "mid", "pos")] == [1, 1, 1]
    assert "2 handler" in bars


def prices(store):
    p = store.table("pf_prices")
    return [dict(r) for r in store.query(select(p).order_by(p.c.at))]


def test_prices_of_tokens_that_passed_are_kept_for_a_week(server, store):
    test_tokens_are_scored_followed_and_labelled(server, store)
    rows = prices(store)
    assert {r["mint"] for r in rows} == {"good"}  # the others did not pass
    assert [r["price"] for r in rows] == [P, 1.2 * P, 1.5 * P, 1.3 * P]  # when scored and at each check

    run(server, store, T0 + timedelta(days=9))
    assert prices(store) == [] and tokens(store)["good"]["price_24h"] == 1.3 * P  # the checkpoints stay


def held_and_other(server, store):
    """Two tokens scored at T0 + 11 minutes: "held" passes and is bought, "other" (a fresh wallet) does not."""
    month_ago = int((T0 - timedelta(days=30)).timestamp())
    server.add("GET", COINS, httpx.Response(200, json=[coin("held", "alice"), coin("other", "bob")]))
    market = Market(server)
    market.wallets = {"alice": [month_ago, month_ago + 3600], "bob": [int((T0 - timedelta(hours=2)).timestamp())]}
    market.prices = {"held": P, "other": P}
    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=11))
    return market


def quote(server, store, at):
    with server.client() as client:
        return PumpFunCollector(client, store).quote(at)


def test_quotes_move_the_open_positions_but_not_the_measurement(server, store):
    market = held_and_other(server, store)
    scored = T0 + timedelta(minutes=11)
    market.prices = {"held": 2 * P, "other": 5 * P}
    server.requests.clear()
    assert quote(server, store, scored + timedelta(minutes=1)) == 1
    assert [r.url.path.rsplit("/", 1)[-1] for r in server.requests] == ["held"]  # only what the portfolio holds
    assert quote(server, store, scored + timedelta(minutes=2)) == 0  # unchanged: nothing new to store
    market.prices["held"] = 3 * P
    assert quote(server, store, scored + timedelta(minutes=3)) == 1

    (position,) = pumpfun.paper(store)["open"]
    assert position["price"] == 3 * P and position["price_at"] == scored + timedelta(minutes=3)
    assert position["result"] == pytest.approx(3 * (1 - pumpfun.FEE) ** 2 - 1)
    row = tokens(store)["held"]  # the measurement keeps to the collector's own checks
    assert row["last_price"] == P and row["peak_after"] == P
    assert pumpfun._aware(row["last_checked_at"]) == scored


def test_position_histories(store):
    now = T0 + timedelta(hours=3)
    sold_at = T0 - timedelta(days=2)
    add_token(store, "open", T0, "tracking", last_price=1.5, last_checked=T0 + timedelta(hours=2))
    add_token(store, "won", sold_at, "done", price_24h=2.0)
    add_token(store, "old", T0 - timedelta(hours=10), "tracking", last_price=0.5,  # from before pf_prices
              last_checked=T0 - timedelta(hours=9))
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_prices").insert(), [
            *({"mint": "open", "at": T0 + timedelta(minutes=m), "price": 1 + m / 100} for m in range(1, 121)),
            *({"mint": "won", "at": sold_at + timedelta(hours=h), "price": 1 + h / 10} for h in range(1, 24))])

    p = pumpfun.paper(store)
    paths = pumpfun.histories(store, [*p["open"], *p["closed"]], now, slices=10)

    kept = (1 - pumpfun.FEE) ** 2
    opened = paths["open"]
    assert opened[0] == (T0, pytest.approx(kept - 1))  # just bought: down by the fees
    assert opened[-1] == (now, pytest.approx(2.2 * kept - 1))  # the latest price, until now
    assert len(opened) <= 2 * 10 + 2 and max(v for _, v in opened) == pytest.approx(2.2 * kept - 1)
    assert paths["won"][-1] == (sold_at + timedelta(hours=24), pytest.approx(2.0 * kept - 1))
    assert [t for t, _ in paths["old"]] == [T0 - timedelta(hours=10), T0 - timedelta(hours=9), now]


def test_the_stamp_changes_with_runs_and_quotes(store):
    first, updated = pumpfun.freshness(store)
    assert updated is None
    run_id = store.start_run("pumpfun")
    started, _ = pumpfun.freshness(store)
    store.finish_run(run_id, ok=True, summary={})
    finished, updated = pumpfun.freshness(store)
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_prices").insert().values(mint="a", at=updated + timedelta(minutes=1), price=1.0))
    quoted, latest = pumpfun.freshness(store)
    assert len({first, started, finished, quoted}) == 4 and latest == updated + timedelta(minutes=1)


def measured_tokens(store, n=80):
    """``n`` tokens measured at 24 hours: the 30 with the lowest market value collapsed, the rest rose 50 %."""
    rows = [dict(mint=f"t{i:03}", creator="c", created_at=T0, discovered_at=T0, sampled=True, status="done",
                 scored_at=T0, screen_version=pumpfun.SCREEN_VERSION, active=True, complete=True, passed=i % 2 == 0,
                 warnings=[], features={"market_cap_usd": 1000 + i * 100, "trades_5m": 5}, price_t=1.0,
                 price_1h=1.0, price_6h=1.0, price_24h=0.05 if i < 30 else 1.5, peak_1h=1.0, peak_6h=1.0,
                 peak_after=1.0 if i < 30 else 2.0, misses=0) for i in range(n)]
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_tokens").insert(), rows)


def test_patterns_split_each_feature_into_quarters(store):
    assert pumpfun.patterns(store) == {"label": None, "populations": {}}
    measured_tokens(store)

    found = pumpfun.patterns(store)

    assert found["label"] == "24 timer"
    every = found["populations"]["all"]
    assert every["n"] == 80 and every["collapse_rate"] == pytest.approx(30 / 80)
    market = every["features"][0]  # the feature whose quarters differ most comes first
    assert market["key"] == "market_cap_usd" and market["spread"] == 1.0
    assert [q["n"] for q in market["quarters"]] == [20, 20, 20, 20]
    assert [q["collapse_rate"] for q in market["quarters"]] == [1.0, 0.5, 0.0, 0.0]
    assert market["quarters"][3]["median_return"] == pytest.approx(1.5 * (1 - pumpfun.FEE) ** 2 - 1)
    same = next(f for f in every["features"] if f["key"] == "trades_5m")  # every token had 5 trades
    assert same["spread"] is None and [q["collapse_rate"] for q in same["quarters"]][:3] == [None] * 3
    missing = next(f for f in every["features"] if f["key"] == "top10_share")
    assert missing["n"] == 0 and missing["quarters"] == [] and every["features"][-1]["spread"] is None
    assert found["populations"]["passed"]["n"] == 40


def page_client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.delenv("APP_PASSWORD", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT_ID", raising=False)
    monkeypatch.setenv("SCHEDULER", "off")
    return TestClient(web.create_app(db_url))


def test_the_log_downloads(server, store, db_url, monkeypatch):
    test_tokens_are_scored_followed_and_labelled(server, store)
    with page_client(db_url, monkeypatch) as client:
        spreadsheet = client.get("/pumpfun/export.csv")
        everything = client.get("/pumpfun/export.json")

    assert re.fullmatch(r'attachment; filename="pumpfun-logg-\d{4}-\d\d-\d\d-\d{4}\.csv"',
                        spreadsheet.headers["content-disposition"])
    assert spreadsheet.text.startswith("﻿Token (adresse);Navn;")
    header, *rows = csv.reader(io.StringIO(spreadsheet.text.lstrip("﻿")), delimiter=";")
    assert len(rows) == 3  # every sampled token
    good = dict(zip(header, next(r for r in rows if r[0] == "good"), strict=True))
    assert good["Bestod filteret"] == "ja" and good["Kollapset etter 24 t"] == "nei"
    assert good["Markedsverdi ved vurdering (SOL)"] == "50,000"  # a price of 5e-8 SOL times a billion tokens
    assert good["Avkastning etter 24 t (%)"] == f"{(1.3 * (1 - pumpfun.FEE) ** 2 - 1) * 100:.2f}".replace(".", ",")
    assert good["Fiktiv handel"] == "kjøpt og solgt" and good["Lansert (norsk tid)"] == "2026-10-02 13:59:00"
    dumpy = dict(zip(header, next(r for r in rows if r[0] == "dumpy"), strict=True))
    assert dumpy["Varseltegn"].startswith("Utstederen har lansert") and dumpy["Fiktiv handel"] == ""

    data = everything.json()
    assert list(data) == ["meta", "tokens", "trades", "equity", "price_history"]
    assert [t["mint"] for t in data["tokens"]] == ["dumpy2", "dumpy", "good"]  # oldest first
    token = data["tokens"][2]
    assert token["paper"] == "sold" and token["collapsed_24h"] is False and token["features"]["trades_5m"] == 4
    assert token["return_24h"] == pytest.approx(1.3 * (1 - pumpfun.FEE) ** 2 - 1)
    assert data["trades"][0]["mint"] == "good" and data["trades"][0]["sell_price"] == 1.3 * P
    assert len(data["equity"]) == 4 and len(data["price_history"]) == 4
    assert data["meta"]["screen_version"] == pumpfun.SCREEN_VERSION


def test_the_live_page(server, store, db_url, monkeypatch):
    market = held_and_other(server, store)
    with page_client(db_url, monkeypatch) as client:
        page = client.get("/pumpfun").text
        stamp = client.get("/pumpfun/version").json()["v"]
        market.prices["held"] = 2 * P
        quote(server, store, T0 + timedelta(minutes=12))
        moved = client.get("/pumpfun/version").json()["v"]
        six_hours = client.get("/pumpfun?periode=6t").text
        unknown = client.get("/pumpfun?periode=1y").text
        assets = [client.get(path) for path in ("/static/live.js", "/static/pumpfun-hero.webp")]

    assert 'class="degen"' in page and 'data-live-page data-version="' in page and "/static/live.js" in page
    assert page.count('class="chart spark spark-card"') == 1 and "$HELD" in page and 'id="pf-tape"' in page
    assert page.count("data-live") >= 8 and "Mønstre i galskapen" in page and "/pumpfun/export.json" in page
    assert moved != stamp
    assert 'data-periode="6t" class="on"' in six_hours and 'data-periode="24t" class="on"' in unknown
    assert [a.status_code for a in assets] == [200, 200] and assets[1].headers["content-type"] == "image/webp"


def test_the_cliff_is_recorded_once_by_follows_and_quotes(server, store):
    market = held_and_other(server, store)  # "held" passed at T0 + 11 minutes, at P
    scored = T0 + timedelta(minutes=11)
    market.prices = {"held": 0.6 * P, "other": 0.4 * P}
    run(server, store, scored + timedelta(minutes=5))
    rows = tokens(store)
    assert rows["held"]["cliff_at"] is None  # down 40 %: not yet halved
    assert pumpfun._aware(rows["other"]["cliff_at"]) == scored + timedelta(minutes=5)  # every measured token
    assert rows["other"]["cliff_price"] == 0.4 * P

    market.prices["held"] = 0.45 * P
    quote(server, store, scored + timedelta(minutes=7))  # the quotes catch it between runs
    market.prices["held"] = 0.1 * P
    run(server, store, scored + timedelta(minutes=10))
    held = tokens(store)["held"]
    assert pumpfun._aware(held["cliff_at"]) == scored + timedelta(minutes=7) and held["cliff_price"] == 0.45 * P


def test_cliffs_are_found_in_the_price_history_of_older_positions(server, store):
    add_token(store, "fell", T0, "tracking", last_price=0.3, low_after=0.3)
    add_token(store, "fine", T0, "tracking", last_price=0.9, low_after=0.8)
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_prices").insert(), [
            {"mint": "fell", "at": T0 + timedelta(minutes=m), "price": price}
            for m, price in ((5, 0.8), (20, 0.45), (40, 0.3))])
    with server.client() as client:
        PumpFunCollector(client, store)._backfill_cliffs(T0 + timedelta(hours=1))
    rows = tokens(store)
    assert pumpfun._aware(rows["fell"]["cliff_at"]) == T0 + timedelta(minutes=20) and rows["fell"]["cliff_price"] == 0.45
    assert rows["fine"]["cliff_at"] is None


def test_the_stup_account_sells_at_the_cliff_and_buys_again(store, monkeypatch):
    monkeypatch.setattr(pumpfun, "PAPER_START", 0.26)  # two positions, and a little cash left over
    add_token(store, "a", T0, "tracking", last_price=0.2, cliff_at=T0 + timedelta(minutes=30), cliff_price=0.5)
    add_token(store, "b", T0 + timedelta(minutes=10), "tracking", last_price=1.0)
    add_token(store, "c", T0 + timedelta(hours=1), "tracking", last_price=1.2)

    hold, stup = pumpfun.paper(store), pumpfun.paper(store, cliff=True)

    kept = (1 - pumpfun.FEE) ** 2
    assert sorted(o["mint"] for o in hold["open"]) == ["a", "b"] and hold["skipped"] == 1  # no cash for "c"
    (sold,) = stup["closed"]
    assert sold["mint"] == "a" and sold["cliff"] and sold["result"] == pytest.approx(0.5 * kept - 1)
    assert sorted(o["mint"] for o in stup["open"]) == ["b", "c"]  # the sale paid for "c"
    assert stup["cliff_sales"] == 1 and stup["cliff_minutes"] == 30
    assert stup["equity"] > hold["equity"]


def test_hype_is_recorded_when_scored(server, store):
    server.add("GET", COINS, httpx.Response(200, json=[
        coin("loud", "a", twitter="https://x.com/loud", telegram="https://t.me/loud"), coin("calm", "b")]))
    market = Market(server)
    market.wallets = {"a": OLD_WALLET, "b": OLD_WALLET}
    market.prices = {"loud": P, "calm": P}
    market.profiles, market.boosts = {"loud"}, {"loud": 10}
    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=11))
    loud, calm = (tokens(store)[m]["features"] for m in ("loud", "calm"))
    assert (loud["links"], loud["dex_profile"], loud["boosts"]) == (2, True, 10)
    assert (calm["links"], calm["dex_profile"], calm["boosts"]) == (0, False, 0)


def test_hype_groups_in_the_patterns(store):
    measured_tokens(store)  # no launch links, and scored before DexScreener promotion was recorded
    every = pumpfun.patterns(store)["populations"]["all"]
    links, profile, boosts = every["hype"]
    assert [(g["label"], g["n"]) for g in links["groups"]] == [("Ingen", 80), ("1", 0), ("2–3", 0)]
    assert links["groups"][0]["collapse_rate"] == pytest.approx(30 / 80) and links["groups"][1]["collapse_rate"] is None
    assert [g["n"] for g in profile["groups"]] == [0, 0] and [g["n"] for g in boosts["groups"]] == [0, 0]


def test_the_page_compares_the_stup_account(server, store, db_url, monkeypatch):
    market = held_and_other(server, store)
    market.prices["held"] = 0.45 * P
    quote(server, store, T0 + timedelta(minutes=20))
    with page_client(db_url, monkeypatch) as client:
        page = client.get("/pumpfun").text
    assert "Med stup-regelen" in page and "1 solgt ved stup" in page and "⛔ stup" in page


def test_the_small_analysis_log(server, store, db_url, monkeypatch):
    test_tokens_are_scored_followed_and_labelled(server, store)
    with store.engine.begin() as conn:  # a dead token: scored but never measured
        conn.execute(store.table("pf_tokens").insert().values(
            mint="dead", creator="c", created_at=T0, discovered_at=T0, sampled=True, status="scored", scored_at=T0,
            screen_version=pumpfun.SCREEN_VERSION, active=False, complete=True, passed=False, price_t=1.0, misses=0))
    with page_client(db_url, monkeypatch) as client:
        small = client.get("/pumpfun/export-analyse.json")
        full = client.get("/pumpfun/export.json")

    assert re.fullmatch(r'attachment; filename="pumpfun-analyse-\d{4}-\d\d-\d\d-\d{4}\.json"',
                        small.headers["content-disposition"])
    data = small.json()
    assert list(data) == ["meta", "funnel", "tokens", "trades", "equity"]
    assert [t["mint"] for t in data["tokens"]] == ["dumpy2", "dumpy", "good"]  # measured only, oldest first
    assert all("launch" not in t and t["links"] == 0 for t in data["tokens"])
    dead = [f for f in data["funnel"] if f["status"] == "scored"]
    assert dead == [{"screen_version": pumpfun.SCREEN_VERSION, "status": "scored", "active": False, "complete": True,
                     "passed": False, "tokens": 1}]
    assert sum(f["tokens"] for f in data["funnel"]) == 4
    assert [t["mint"] for t in data["trades"]["hold"]] == ["good"] and data["trades"]["stup"][0]["cliff"] is False
    assert len(small.content) < len(full.content)
