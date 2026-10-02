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

    r = pumpfun.results(store)
    assert r["measured"] == 3 and r["collapse_rate"] == pytest.approx(2 / 3)
    assert r["caught"] == 1.0 and r["kept"] == 1.0 and r["passed"] == 1 and r["passed_collapse_rate"] == 0.0
    passed_24h = r["returns"][0]["horizons"][2]
    assert passed_24h["median"] == pytest.approx(1.3 * (1 - pumpfun.FEE) ** 2 - 1)
    serial = next(w for w in r["warnings"] if w["key"] == "serial")
    assert (serial["n"], serial["collapse_with"], serial["collapse_without"]) == (2, 1.0, 0.0)


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
    assert r["incomplete"] == 1 and r["measured"] == 0


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
        assert "Ingen ferdige målinger ennå" in client.get("/pumpfun").text

    test_tokens_are_scored_followed_and_labelled(server, store)
    with TestClient(web.create_app(db_url)) as client:
        page = client.get("/pumpfun").text
    assert "Siste ferdige tokens" in page and "good coin" in page and "Kollapset" in page
    assert "Utstederen har lansert andre tokens det siste døgnet" in page
