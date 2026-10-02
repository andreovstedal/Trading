"""The pump.fun measurement: discovery, scoring, following the price, labels and results."""

import json
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from conftest import FakeServer
from sqlalchemy import select

from nordic_signals import cli, pumpfun
from nordic_signals.collectors.pumpfun import PumpFunCollector
from nordic_signals.web import app as web

COINS = "https://frontend-api-v3.pump.fun/coins"
DEX = "https://api.dexscreener.com/tokens/v1/solana/"
RPC = "https://api.mainnet-beta.solana.com/"
T0 = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


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
            "txns": {"m5": {"buys": 3, "sells": 1}, "h1": {"buys": 20, "sells": 9}},
            "volume": {"h1": 900.0, "h24": 2000.0},
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
    market.prices = {"good": 1.0e-7, "dumpy": 1.0e-7, "dumpy2": 1.0e-7}

    scored = T0 + timedelta(minutes=11)
    run(server, store, T0)
    run(server, store, scored)
    rows = tokens(store)
    assert rows["good"]["status"] == "tracking" and rows["good"]["passed"] is True and rows["good"]["warnings"] == []
    assert rows["dumpy"]["warnings"] == ["serial", "fresh_wallet"] and rows["dumpy"]["passed"] is False
    assert rows["dumpy"]["features"]["creator_age_h"] == pytest.approx(2 - 1 / 60, abs=0.01)

    for after, good, dumpy in ((timedelta(hours=1), 1.2e-7, 3.0e-7), (timedelta(hours=6), 1.5e-7, 0.5e-7),
                               (timedelta(hours=24), 1.3e-7, 0.2e-7)):
        market.prices = {"good": good, "dumpy": dumpy, "dumpy2": dumpy}
        run(server, store, scored + after)

    rows = tokens(store)
    assert rows["good"]["status"] == "done" and rows["good"]["collapsed"] is False
    assert (rows["good"]["price_1h"], rows["good"]["price_6h"], rows["good"]["price_24h"]) == (1.2e-7, 1.5e-7, 1.3e-7)
    assert rows["dumpy"]["collapsed"] is True  # 0.2 is at most 10 % of the 3.0 peak
    assert rows["dumpy"]["peak_after"] == 3.0e-7 and rows["dumpy"]["low_after"] == 0.2e-7
    assert (rows["dumpy"]["peak_1h"], rows["dumpy"]["peak_6h"]) == (3.0e-7, 3.0e-7)

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
    market.prices = {"a": 1e-7, "gone": 1e-7}
    scored = T0 + timedelta(minutes=10)
    run(server, store, T0)
    run(server, store, scored)

    market.prices = {"a": 2e-7}  # "gone" disappears from DexScreener
    for minutes in range(5, 65, 5):
        run(server, store, scored + timedelta(minutes=minutes))
    rows = tokens(store)
    assert rows["gone"]["status"] == "missing" and rows["gone"]["misses"] == 12
    assert rows["a"]["price_1h"] == 2e-7

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
    market.prices = {"a": 1e-7}
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
    market.prices = {"a": 1e-7}
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
    market.prices = {"whale": 1e-7}
    market.holders = {"whale": [("whale-curve", 600e6), ("big", 250e6), ("small", 100e6)]}  # the curve is not a holder

    run(server, store, T0)
    run(server, store, T0 + timedelta(minutes=10))

    row = tokens(store)["whale"]
    assert row["features"]["top10_share"] == pytest.approx(0.35)
    assert "concentrated" in row["warnings"]
    assert not any(r.url.host == "api.mainnet-beta.solana.com" for r in server.requests)


@pytest.mark.parametrize("features, expected", [
    ({"serial": 0, "creator_tx": 40, "creator_history_complete": True, "creator_age_h": 500, "creator_tx_per_h": 0.1,
      "price": 1, "peak_before": 1}, []),
    ({"serial": 3}, ["serial"]),
    ({"creator_tx": 12, "creator_history_complete": True, "creator_age_h": 3}, ["fresh_wallet"]),
    # A full page of transactions: the wallet's age is unknown, but its pace is a robot's.
    ({"creator_tx": 200, "creator_history_complete": False, "creator_age_h": 3, "creator_tx_per_h": 300},
     ["busy_wallet"]),
    ({"creator_tx": 8, "creator_history_complete": True, "creator_age_h": 30, "creator_tx_per_h": 80}, []),
    ({"top10_share": 0.31}, ["concentrated"]),
    ({"price": 0.5, "peak_before": 1.0}, ["dumped"]),
    ({"graduated": True}, ["instant_graduation"]),
])
def test_warning_signs(features, expected):
    assert pumpfun.warning_signs(features) == expected


def test_cli_runs_and_logs_the_collector(server, db_url, monkeypatch):
    server.add("GET", COINS, httpx.Response(200, json=[coin("a", "x")]))
    Market(server)
    monkeypatch.setattr(cli, "PoliteClient", server.client)

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
    assert "Ingen målinger ennå" in page and "Ingen åpne posisjoner" in page

    test_tokens_are_scored_followed_and_labelled(server, store)
    with TestClient(web.create_app(db_url)) as client:
        page = client.get("/pumpfun").text
    assert "Siste ferdig målte tokens" in page and "good coin" in page and "Kollapset" in page
    assert "Utstederen har lansert andre tokens det siste døgnet" in page
    assert "Siste lukkede handler" in page and page.count("<svg") == 2  # account value and results per trade


def add_token(store, mint, scored, status, *, price_24h=None, last_price=None, last_checked=None, passed=True):
    with store.engine.begin() as conn:
        conn.execute(store.table("pf_tokens").insert().values(
            mint=mint, name=f"{mint} coin", symbol=mint.upper(), creator="c", created_at=scored, discovered_at=scored,
            sampled=True, status=status, scored_at=scored, screen_version=pumpfun.SCREEN_VERSION, active=True,
            complete=True, passed=passed, warnings=[], price_t=1.0, price_24h=price_24h, last_price=last_price,
            last_checked_at=last_checked, misses=0))


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
    assert 'class="line"' in svg and "data-points" in svg and "10,40\u00a0SOL" in svg and 'class="ref"' in svg
    bars = charts.result_bars(pumpfun._bins([-1.0, -0.95, 0.0, 0.7]))
    assert [bars.count(f'class="bar {kind}"') for kind in ("neg", "mid", "pos")] == [1, 1, 1]
    assert "2 handler" in bars
