from datetime import datetime, time, timedelta

import pytest
from conftest import seed_universe
from sqlalchemy import select

from nordic_signals.advisor import Policy, recommend
from nordic_signals.advisor.allocation import allocate_long, short_sleeve
from nordic_signals.advisor.evaluate import evaluate, spearman, track_record
from nordic_signals.advisor.features import build_features, buyback_start, insider_direction
from nordic_signals.advisor.scoring import percentile_ranks, score_stocks
from nordic_signals.collectors.base import NORDIC_TZ
from nordic_signals.http import FetchedResponse


def features_by_symbol(store, now):
    return {s.symbol: s for s in build_features(store, now)}


def test_features_from_each_source(store):
    now = seed_universe(store)
    stocks = features_by_symbol(store, now)

    aaa = stocks["AAA"].features
    assert aaa["earnings_yield"] == pytest.approx(1 / 8)
    assert aaa["roe"] == pytest.approx(1.5 / 8)
    assert aaa["momentum"] == pytest.approx(1.40 / 1.02 - 1)
    assert aaa["insider_buy_notices"] == 1  # direction read from the notice text
    assert aaa["short_pct"] == 2.2 and aaa["short_new"] is True  # Norway: history reaches back 60 days

    assert stocks["BBB"].features["buyback_start"] is True

    sec = stocks["SEC"].features
    assert (sec["insider_buyers"], sec["insider_recent_buyers"]) == (2, 2)
    assert sec["insider_buy_value"] == pytest.approx(20000 * 120 + 30000 * 119)

    seb = stocks["SEB"].features
    assert seb["short_pct"] == 3.0  # LEI mapped to ISIN through the insider register
    assert seb["short_new"] is False  # Sweden: one download only, so no "rose from zero"
    assert seb["insider_buyers"] == 0  # share-programme awards don't count


def test_stale_observations_are_left_out(store):
    now = seed_universe(store)
    assert build_features(store, now + timedelta(days=6)) == []


@pytest.mark.parametrize("text, expected", [
    ("The CEO has today purchased 10,000 shares", 1),
    ("Styreleder har kjøpt 5 000 aksjer", 1),
    ("The CFO has sold 2,000 shares", -1),
    ("Primærinnsider har solgt aksjer", -1),
    ("Allocation of shares under the incentive programme", 0),
    ("Bought 100 shares and sold 50 options", 0),
])
def test_insider_direction(text, expected):
    assert insider_direction(text) == expected


# Real titles from NewsWeb's own-shares category and MFN's repurchase tag, September-October 2026.
@pytest.mark.parametrize("title", [
    "Kitron ASA - Initiation of share buyback program",
    "AF Gruppen ASA initiates share buyback program",
    "Elopak ASA: Launch of share buy-back programme",
    "Iverksettelse av tilbakekjøpsprogram",
    "Solid Försäkringsaktiebolag inleder återköpsprogram av egna aktier",
    "Solid Försäkringsaktiebolag to repurchase shares",
    "Rusta’s board of directors has resolved to repurchase own shares",
    "Bilia beslutar om återköp av aktier",
    "Bilia decides to buy back own shares",
])
def test_a_new_buyback_programme_is_a_start(title):
    assert buyback_start(title)


@pytest.mark.parametrize("title", [
    "Share buyback programme - transactions in week 40",
    "Danske Bank share buy-back programme: transactions in week 40",
    "DNB Bank ASA - status for tilbakekjøpsprogram etter uke 40 2026",
    "Status of share buy-back programme after week 40",
    "Schouw & Co. share buy-back programme, week 40 2026",
    "STOREBRAND ASA: Status share buyback program",
    "Transactions carried out under the buy-back program",
    "DNB Bank ASA's share buy-back programme has been completed",
    "DNB Bank ASAs tilbakekjøpsprogram er avsluttet",
    "Moreld ASA: Share buy-back programme closed",
    "Equinor ASA: Share buy-back - third tranche for 2026",
    "Equinor ASA: Buy-back of shares to share programmes for employees",
    "Vend Marketplaces ASA: Repurchase of own shares",
    "Återköp av aktier i Bilia AB under  vecka 25, 2022",
    "Threshold exceeded for major shareholding notification due to buyback of own shares",
    "CORRECTION: Missing MAR label in earlier press release ”The Board of Bilia has decided to repurchase own shares”",
])
def test_a_report_on_a_running_programme_is_not(title):
    assert not buyback_start(title)


def test_percentile_ranks_share_ties():
    assert percentile_ranks({"a": 1, "b": 2, "c": 2, "d": 3, "e": None}) == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 1.0}
    assert percentile_ranks({"a": 5}) == {"a": 0.5}


def scored_universe(store, **kwargs):
    now = seed_universe(store)
    stocks = build_features(store, now)
    return {s.stock.symbol: s for s in score_stocks(stocks, {"NOK": 1.0, "SEK": 0.95}, target_position=20_000,
                                                    **kwargs)}


def test_eligibility_rules(store):
    scored = scored_universe(store)

    assert scored["CCC"].exclusion == "Aksjekurs under 5 NOK"
    assert scored["DDD"].exclusion == "Ikke positivt resultat (mangler P/E)"
    assert scored["EEE"].exclusion.startswith("For lav omsetning")
    assert scored["SEA A"].exclusion == "En annen aksjeklasse (SEA B) er mer likvid"
    assert scored["GRW"].eligible  # MTF listings are fine outside an ASK
    assert {s for s, item in scored.items() if item.eligible} == {"AAA", "BBB", "GRW", "SEA B", "SEB", "SEC"}
    ranks = sorted(item.rank for item in scored.values() if item.eligible)
    assert ranks == [1, 2, 3, 4, 5, 6]


def test_ask_accounts_only_get_regulated_markets(store):
    scored = scored_universe(store, ask_only=True)
    assert scored["GRW"].exclusion == "Ikke notert på regulert marked (ikke tillatt på ASK)"


def test_windfalls_stay_out_of_the_long_term_sleeve(store):
    """Model v2: a P/E below 4 or a rise of more than 300 % in a year (Hunter Group, October 2026)."""
    now = seed_universe(store)
    stocks = features_by_symbol(store, now)
    stocks["AAA"].features.update(pe=2.2, earnings_yield=1 / 2.2)  # earnings from contracts that end soon
    stocks["BBB"].features.update(ret_1y=13.0)  # +1 300 %
    stocks["SEB"].features.update(pe=4.0, earnings_yield=1 / 4.0)  # exactly at the limit is fine

    scored = {s.stock.symbol: s for s in score_stocks(list(stocks.values()), {"NOK": 1.0, "SEK": 0.95},
                                                      target_position=20_000)}

    assert scored["AAA"].exclusion.startswith("P/E under 4 ")
    assert scored["BBB"].exclusion.startswith("Steget over 300\u00a0% på 12 mnd.")
    assert scored["SEB"].eligible
    assert {s for s, item in scored.items() if item.eligible} == {"GRW", "SEA B", "SEB", "SEC"}


def test_overlays(store):
    scored = scored_universe(store)
    assert "insider" not in scored["SEC"].overlays  # v4: Swedish insiders buying earns no bonus
    assert scored["AAA"].overlays["insider"] == 0.03  # a Norwegian purchase notice still does
    assert scored["AAA"].overlays["short"] == pytest.approx(-0.10)  # above 2% and just increased
    assert "buyback" not in scored["BBB"].overlays  # v4: nor does a buyback
    assert "Shortandel 2,2\u00a0%, nylig økt" in scored["AAA"].reasons


def test_value_is_sales_and_book_to_price_without_earnings(store):
    """Model v4: earnings count once, in quality; value is two thirds sales/price, one third book/price."""
    now = seed_universe(store)
    stocks = features_by_symbol(store, now)
    for symbol, ps in (("SEA B", 0.5), ("SEB", 1.0), ("SEC", 4.0)):
        stocks[symbol].features.update(ps=ps, sales_to_price=1 / ps)

    def score() -> dict:
        return {s.stock.symbol: s for s in score_stocks(list(stocks.values()), {"NOK": 1.0, "SEK": 0.95},
                                                        target_position=20_000)}

    scored = score()
    book = percentile_ranks({sym: scored[sym].stock.features["book_to_price"] for sym in ("SEA B", "SEB", "SEC")})
    sales = {"SEA B": 1.0, "SEB": 0.5, "SEC": 0.0}  # the highest sales/price ranks first
    for sym in ("SEA B", "SEB", "SEC"):
        assert scored[sym].themes["value"] == pytest.approx((2 * sales[sym] + book[sym]) / 3)

    # Peak earnings: a much lower P/E lifts SEC's quality, and leaves its value where it was.
    pb = stocks["SEC"].features["pb"]
    stocks["SEC"].features.update(pe=5.0, earnings_yield=1 / 5.0, roe=pb / 5.0)
    again = score()
    assert again["SEC"].themes["value"] == pytest.approx(scored["SEC"].themes["value"])
    assert again["SEC"].themes["quality"] > scored["SEC"].themes["quality"]


def test_at_most_three_positions_from_one_sector(store):
    scored = list(scored_universe(store).values())
    eligible = sorted((s for s in scored if s.eligible), key=lambda s: s.rank)
    for item in eligible[:4]:
        item.stock.features["sector"] = "Energy"
    for item in eligible[4:]:
        item.stock.features["sector"] = None

    positions, notes = allocate_long(scored, Policy(account_value=200_000, max_positions=5, min_position=20_000))

    assert [p.stock.symbol for p in positions] == [s.stock.symbol for s in [*eligible[:3], *eligible[4:6]]]
    assert any(eligible[3].stock.symbol in n and "sektoren" in n for n in notes)
    assert any("mangler sektor" in n for n in notes)


def test_allocation_in_whole_shares(store):
    scored = list(scored_universe(store).values())
    policy = Policy(account_value=100_000, long_pct=80, short_pct=15, cash_pct=5, max_positions=3, min_position=20_000)

    positions, notes = allocate_long(scored, policy)

    assert len(positions) == 3  # 80 000 NOK / 20 000 NOK minimum = 4, capped at 3
    for p in positions:
        price_nok = p.stock.price * p.scored.fx
        assert p.shares == int((80_000 / 3) // price_nok)
        assert p.amount == pytest.approx(p.shares * price_nok)
    assert [p.scored.rank for p in positions] == [1, 2, 3]
    assert any("tynn spredning" in n for n in notes)


def test_small_sleeves_are_flagged(store):
    scored = list(scored_universe(store).values())
    positions, notes = allocate_long(scored, Policy(account_value=15_000, min_position=20_000))
    assert positions == [] and "indeksfond" in notes[0]


def test_short_sleeve_candidates_and_avoid_flags(store):
    scored = list(scored_universe(store).values())
    signals, notes = short_sleeve(scored, Policy(account_value=400_000, long_pct=80, short_pct=15, cash_pct=5))

    by_type = {(s.stock.symbol, s.signal) for s in signals}
    assert ("BBB", "buyback_start") in by_type
    assert ("SEC", "insider_cluster") not in by_type  # v4: no longer a signal
    assert ("AAA", "short_increase") in by_type
    first = signals[0]
    assert first.signal == "buyback_start" and first.paper and first.shares > 0
    assert any(n.startswith("Kun på papir") for n in notes)


@pytest.mark.parametrize("bad", [
    {"account_value": 0},
    {"account_value": 100_000, "long_pct": 90, "short_pct": 20, "cash_pct": 5},
    {"account_value": 100_000, "max_positions": 0},
])
def test_policy_validation(bad):
    with pytest.raises(ValueError):
        Policy(**bad)


def test_recommendation_is_logged_end_to_end(store):
    now = seed_universe(store)
    rec_id = recommend.create(store, Policy(account_value=200_000, max_positions=4))
    recommend.run(store, rec_id)

    rec = store.get("recommendations", id=rec_id)
    assert rec["status"] == "done", rec["error"]
    assert rec["summary"]["universe"] == 10 and rec["summary"]["eligible"] == 6
    lines = {line["symbol"]: line for line in _lines(store, rec_id)}
    assert len(lines) == 10  # every stock, eligible or not, so the ranking can be scored later
    held = [line for line in lines.values() if line["long_shares"]]
    assert len(held) == 4
    total = sum(line["long_amount"] for line in held)
    assert rec["summary"]["cash"] == pytest.approx(200_000 - total)
    assert lines["CCC"]["exclusion"] == "Aksjekurs under 5 NOK"
    assert lines["AAA"]["features"]["short_new"] is True
    assert rec["data_cutoff"] == {}  # no collector runs in this test
    del now


def test_failed_recommendations_record_the_error(store):
    rec_id = recommend.create(store, Policy(account_value=200_000))
    recommend.run(store, rec_id)  # empty database
    rec = store.get("recommendations", id=rec_id)
    assert rec["status"] == "failed" and "Ingen ferske data fra Nordnet" in rec["error"]


def test_outcomes_and_track_record(store):
    now = seed_universe(store)
    rec_id = recommend.create(store, Policy(account_value=200_000, max_positions=4))
    recommend.run(store, rec_id)
    assert evaluate(store) == 0  # nothing has matured yet

    # 25 later evening snapshots; returns rise with the rank so the ranking looks good.
    lines = {line["instrument_id"]: line for line in _lines(store, rec_id) if line["eligible"]}
    rows = []
    for day in range(1, 26):
        for instrument_id, line in lines.items():
            growth = 1 + 0.002 * day * (7 - line["rank"])
            rows.append({"instrument_id": instrument_id, "observed_at": _local_time(now, day, 22, 30),
                         "tick_at": _local_time(now, day, 16, 25), "last": line["ref_price"] * growth})
    store.upsert("nordnet_observations", rows, fetch_id=_fetch(store, now))

    assert evaluate(store) == 6 * 4  # six eligible stocks x horizons 1, 2, 5 and 20
    assert evaluate(store) == 0  # idempotent
    record = track_record(store)
    long_20 = next(r for r in record["long"] if r["horizon"] == 20)
    assert long_20["recommendations"] == 1
    assert long_20["ic"] is None  # fewer than 10 stocks is too few for a rank correlation
    assert long_20["excess"] > 0  # the four picks are the four best-ranked
    assert {r["signal_type"] for r in record["short"]} == {"buyback_start", "short_increase"}


def test_outcomes_use_closing_prices_only(store):
    now = seed_universe(store)
    rec_id = recommend.create(store, Policy(account_value=200_000, max_positions=4))
    recommend.run(store, rec_id)

    eligible = [(line["instrument_id"], line["ref_price"]) for line in _lines(store, rec_id) if line["eligible"]]

    def snapshot(hour, minute, tick_hour, tick_minute, **prices):
        store.upsert("nordnet_observations", [
            {"instrument_id": i, "observed_at": _local_time(now, 1, hour, minute),
             "tick_at": _local_time(now, 1, tick_hour, tick_minute),
             **{field: ref * factor for field, factor in prices.items()}}
            for i, ref in eligible], fetch_id=_fetch(store, now))

    snapshot(7, 0, 6, 30, last=0.0, close=1.0)  # after Nordnet's morning reset: no trades yet
    snapshot(12, 0, 11, 59, last=1.5)  # intraday: the price is still moving
    assert evaluate(store) == 0  # e.g. "Oppdater utfall nå" pressed at lunch

    snapshot(22, 30, 16, 25, last=1.1)  # after the close
    assert evaluate(store) == 6  # the one-day horizon for each of the six eligible stocks
    outcomes = store.query(select(store.table("outcomes")))
    assert [round(o["ret"], 6) for o in outcomes] == [0.1] * 6


def test_prices_before_the_open_use_the_previous_close(store):
    now = seed_universe(store)
    # Just after Nordnet's morning reset AAA shows last = 0 and turnover = 0, with yesterday's price in "close".
    store.upsert("nordnet_observations", [{
        "instrument_id": 1, "observed_at": now - timedelta(minutes=30), "last": 0.0, "close": 101.0,
        "turnover": 0.0, "market_cap": 10e9, "pe": 8.0, "pb": 1.5, "dividend_yield": 5.0, "yield_1y": 40.0,
        "yield_1m": 2.0, "number_of_owners": 1000,
    }], fetch_id=_fetch(store, now))

    stock = next(s for s in build_features(store, now) if s.symbol == "AAA")
    assert stock.price == 101.0
    assert stock.features["adv"] == 50e6  # from the turnover history, not today's zero
    scored = {s.stock.symbol: s for s in score_stocks([stock], {"NOK": 1.0}, target_position=20_000)}
    assert scored["AAA"].eligible


def test_spearman():
    assert spearman([(i, i * 2) for i in range(12)]) == pytest.approx(1.0)
    assert spearman([(i, -i) for i in range(12)]) == pytest.approx(-1.0)
    assert spearman([(1, 1)] * 3) is None


def _lines(store, rec_id):
    scores = store.table("scores")
    return store.query(select(scores).where(scores.c.recommendation_id == rec_id))


def _local_time(now, days_later, hour, minute):
    """A wall-clock time in Oslo, ``days_later`` days after ``now``."""
    day = now.astimezone(NORDIC_TZ).date() + timedelta(days=days_later)
    return datetime.combine(day, time(hour, minute), NORDIC_TZ)


def _fetch(store, now):
    return store.record_fetch("test", FetchedResponse("GET", "https://example.test/", 200, "", b"x", now))
