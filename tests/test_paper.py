"""The play-money Nordnet account: fills at the opening, Nordnet's fees, dividends, and the evening's decisions."""

import csv
import io
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from nordic_signals.advisor import paper
from nordic_signals.collectors.base import NORDIC_TZ

MON, TUE, WED, THU, FRI = (date(2026, 10, d) for d in (5, 6, 7, 8, 9))
NEXT_MON = date(2026, 10, 12)


def oslo(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), NORDIC_TZ)


def snapshot(store, instrument_id, day, opening, closing, *, traded=None):
    """Nordnet's stock list as the nightly run sees it on ``day``: after the close, with the last trade's time."""
    with store.engine.begin() as conn:
        conn.execute(store.table("nordnet_observations").insert().values(
            instrument_id=instrument_id, observed_at=oslo(day, 22, 30), tick_at=oslo(traded or day, 16, 20),
            open=opening, last=closing))


def sek_rate(store, day, rate):
    stamp = datetime.combine(day, time(0), ZoneInfo("Europe/London"))  # how Yahoo stamps currency bars
    with store.engine.begin() as conn:
        conn.execute(store.table("price_bars").insert().values(
            symbol="SEKNOK=X", interval="1d", ts=int(stamp.timestamp()), close=rate))


def order(store, decided_on, instrument_id, side, shares, *, sleeve="long", country="NO", currency="NOK",
          symbol=None, signal_type=None):
    with store.engine.begin() as conn:
        conn.execute(store.table("paper_orders").insert().values(
            account=paper.ACCOUNT, decided_on=decided_on, decided_at=oslo(decided_on, 22, 45),
            instrument_id=instrument_id, symbol=symbol or f"S{instrument_id}", name=f"Stock {instrument_id}",
            country=country, currency=currency, side=side, shares=shares, sleeve=sleeve, signal_type=signal_type,
            reason="test"))


def test_nordnets_fees():
    assert paper.costs(10_000, "NOK") == (29.0, 0.0)  # class Mini's minimum
    assert paper.costs(100_000, "NOK") == pytest.approx((150.0, 0.0))  # 0.15 %
    assert paper.costs(20_000, "SEK") == pytest.approx((30.0, 50.0))  # and 0.25 % to exchange the currency


def test_market_hours_and_holidays():
    assert paper.market_status("NO", oslo(MON, 10))["open"]
    oslo_closed = oslo(MON, 17)
    assert not paper.market_status("NO", oslo_closed)["open"] and paper.market_status("SE", oslo_closed)["open"]
    assert paper.market_status("SE", oslo_closed)["closes"] == oslo(MON, 17, 30)
    assert paper.market_status("NO", oslo(FRI, 20))["next_open"] == oslo(NEXT_MON, 9)  # over the weekend
    assert paper.trading_hours("NO", date(2026, 12, 24)) is None  # Christmas Eve
    assert paper.trading_hours("SE", date(2026, 10, 30))[1] == oslo(date(2026, 10, 30), 13)  # a half day
    assert paper.market_days("NO", date(2026, 12, 23), date(2027, 1, 4)) == [
        date(2026, 12, 28), date(2026, 12, 29), date(2026, 12, 30), date(2027, 1, 4)]


def test_orders_fill_at_the_next_opening_with_nordnets_fees(store):
    for day, (opening, closing) in ((MON, (99, 100)), (TUE, (102, 104)), (WED, (105, 103))):
        snapshot(store, 1, day, opening, closing)
    for day, (opening, closing) in ((MON, (49, 50)), (TUE, (51, 52)), (WED, (52, 55))):
        snapshot(store, 2, day, opening, closing)
    for day in (MON, TUE, WED):
        sek_rate(store, day, 0.95)
    order(store, MON, 1, "buy", 100)
    order(store, MON, 2, "buy", 200, country="SE", currency="SEK")

    account = paper.account(store)

    norwegian, swedish = account["trades"]
    assert (norwegian["day"], norwegian["price"], norwegian["shares"]) == (TUE, 102, 100)  # the opening price
    assert norwegian["at"] == oslo(TUE, 9) and norwegian["courtage"] == 29.0 and norwegian["exchange"] == 0.0
    value = 200 * 51 * 0.95
    assert swedish["value"] == pytest.approx(value) and swedish["exchange"] == pytest.approx(0.0025 * value)
    cash = paper.START - 100 * 102 - 29 - value * 1.0025 - 29
    assert account["cash"] == pytest.approx(cash)
    assert account["equity"] == pytest.approx(cash + 100 * 103 + 200 * 55 * 0.95)  # at the last close
    assert [day for day, _, _ in account["history"]] == [TUE, WED]
    assert account["courtage"] == 58.0 and account["valued_on"] == WED


def test_sales_pay_for_the_days_buys_and_a_buy_is_cut_to_the_cash(store, monkeypatch):
    monkeypatch.setattr(paper, "START", 20_000.0)
    for day in (MON, TUE, WED, THU):
        snapshot(store, 1, day, 100, 100)
        snapshot(store, 2, day, 50, 50)
    order(store, MON, 1, "buy", 150)
    order(store, TUE, 1, "sell", 150)
    order(store, TUE, 2, "buy", 1_000)  # more than the account can pay for

    bought, sold, cut = paper.account(store)["trades"]

    assert (sold["side"], sold["day"], cut["day"]) == ("sell", WED, WED)  # the sale came first
    assert sold["result"] == pytest.approx(15_000 - 29 - 15_029)
    cash = 20_000 - 15_029 + 15_000 - 29
    assert cut["shares"] == 398 and 398 * 50 + 29.85 <= cash < 399 * 50  # as many as the cash pays for, fees in


def test_an_order_waits_for_its_stock_to_trade_and_lapses_after_five_trading_days(store):
    decided = date(2026, 12, 23)  # Oslo is closed on 24 and 25 December
    snapshot(store, 1, decided, 100, 100)
    snapshot(store, 2, decided, 50, 50)
    later = [date(2026, 12, 28), date(2026, 12, 29), date(2026, 12, 30), date(2027, 1, 4), date(2027, 1, 5)]
    for day in later:
        snapshot(store, 1, day, 101, 102)
        snapshot(store, 2, day, 50, 50, traded=decided)  # listed, but nobody traded it
    order(store, decided, 1, "buy", 10)
    order(store, decided, 2, "buy", 10)

    account = paper.account(store)

    assert [(t["instrument_id"], t["day"]) for t in account["trades"]] == [(1, date(2026, 12, 28))]
    assert [o["instrument_id"] for o in account["lapsed"]] == [2] and account["pending"] == []


def test_dividends_are_credited_on_the_ex_date(store):
    for instrument_id in (1, 2, 3):
        for day in (MON, TUE, WED, THU):
            snapshot(store, instrument_id, day, 100, 100)
    for day in (MON, TUE, WED, THU):
        sek_rate(store, day, 0.95)
    order(store, MON, 1, "buy", 100, symbol="AAA")
    order(store, MON, 2, "buy", 200, symbol="BBB", country="SE", currency="SEK")
    order(store, TUE, 3, "buy", 50, symbol="CCC")  # bought at Wednesday's opening, the ex-date: no dividend
    with store.engine.begin() as conn:
        conn.execute(store.table("dividends").insert(), [
            {"symbol": symbol, "ts": int(oslo(WED, 9).timestamp()), "ex_date": WED, "amount": amount,
             "currency": currency}
            for symbol, amount, currency in (("AAA.OL", 2.0, "NOK"), ("BBB.ST", 1.0, "SEK"), ("CCC.OL", 3.0, "NOK"))])

    account = paper.account(store)

    paid = {d["symbol"]: d for d in account["dividends"]}
    assert set(paid) == {"AAA", "BBB"} and paid["AAA"]["nok"] == 200.0 and paid["AAA"]["day"] == WED
    assert paid["BBB"]["nok"] == pytest.approx(200 * 0.95 * 0.85)  # after 15 % Swedish withholding tax
    assert account["dividends_nok"] == pytest.approx(200 + 200 * 0.95 * 0.85)


# The evening's decisions, with a stand-in for the advisor

def pick(instrument_id, rank, *, eligible=True, price=100.0, signal=None, exclusion=None):
    return paper.Pick(instrument_id, f"S{instrument_id}", f"Stock {instrument_id}", "NO", "NOK", price, 1.0,
                      eligible, rank if eligible else None, 1 - rank / 100 if rank else None, exclusion,
                      signal, "Nytt tilbakekjøpsprogram annonsert" if signal else None)


class Advisor:
    def __init__(self):
        self.picks, self.signals, self.calls = [], [], []

    def __call__(self, store, policy, rebalance):
        self.calls.append((policy.account_value, rebalance))
        return paper.Scan(7 if rebalance else None, self.picks if rebalance else [], self.signals)


def trading_day(store, day, instruments, price=100.0):
    for instrument_id in instruments:
        snapshot(store, instrument_id, day, price, price)


def orders(store):
    t = store.table("paper_orders")
    return [dict(r) for r in store.query(t.select().order_by(t.c.id))]


def test_the_first_evening_buys_the_top_twelve_and_two_short_term_signals(store):
    advisor = Advisor()
    advisor.picks = [pick(100 + i, i + 1) for i in range(15)]
    advisor.signals = [pick(200 + i, 50 + i, signal="buyback_start") for i in range(3)]
    trading_day(store, MON, [100])

    summary = paper.decide(store, oslo(MON, 22, 45), scanner=advisor)

    assert summary["ok"] and summary["rebalance"] and summary["orders"] == 14
    assert advisor.calls == [(paper.START, True)]
    placed = orders(store)
    long_term = [o for o in placed if o["sleeve"] == "long"]
    assert [o["instrument_id"] for o in long_term] == [100 + i for i in range(12)]  # ranks 1-12
    assert all(o["shares"] == math.floor(37_500 / (100 * 1.0015)) for o in long_term)  # 450 000 / 12
    short_term = [o for o in placed if o["sleeve"] == "short"]
    assert [o["instrument_id"] for o in short_term] == [200, 201]  # two slots of 25 000 NOK
    assert short_term[0]["shares"] == math.floor(25_000 / (100 * 1.0015))
    assert short_term[0]["signal_type"] == "buyback_start" and placed[0]["recommendation_id"] == 7
    day = store.get("paper_days", account=paper.ACCOUNT, decided_on=MON)
    assert day["rebalance"] and day["orders"] == 14 and day["recommendation_id"] == 7
    assert any("1 kortsiktige signaler" in note for note in day["notes"])

    assert paper.decide(store, oslo(MON, 23), scanner=advisor)["note"] == "Allerede bestemt i kveld"


def test_it_waits_for_closing_prices_and_rests_on_holidays(store):
    advisor = Advisor()
    snapshot(store, 1, FRI, 100, 100)  # Friday's prices, seen again on Monday evening: nothing traded today
    with store.engine.begin() as conn:
        conn.execute(store.table("nordnet_observations").insert().values(
            instrument_id=1, observed_at=oslo(MON, 22, 30), tick_at=oslo(FRI, 16, 20), last=100))
    assert paper.decide(store, oslo(MON, 22, 45), scanner=advisor) == {"ok": False,
                                                                       "note": "Mangler sluttkurser fra i dag"}
    christmas = paper.decide(store, oslo(date(2026, 12, 25), 22, 45), scanner=advisor)
    assert christmas == {"ok": True, "note": "Børsene var stengt i dag"} and advisor.calls == []


def test_short_term_positions_are_sold_after_five_trading_days(store):
    advisor = Advisor()
    advisor.signals = [pick(200, 30, signal="insider_cluster")]
    trading_day(store, MON, [1])
    paper.decide(store, oslo(MON, 22, 45), scanner=advisor)  # also the first rebalance, with nothing to buy
    advisor.signals = []
    for day in (TUE, WED, THU, FRI):
        trading_day(store, day, [1, 200])
        assert paper.decide(store, oslo(day, 22, 45), scanner=advisor)["orders"] == 0
    trading_day(store, NEXT_MON, [1, 200])

    paper.decide(store, oslo(NEXT_MON, 22, 45), scanner=advisor)

    (sell,) = [o for o in orders(store) if o["side"] == "sell"]
    assert sell["instrument_id"] == 200 and sell["reason"] == "Holdt i 5 handelsdager"
    assert advisor.calls[-1] == (pytest.approx(paper.account(store)["equity"]), False)  # not a rebalance evening


def test_the_monthly_rebalance_keeps_holdings_still_near_the_top(store):
    advisor = Advisor()
    advisor.picks = [pick(100 + i, i + 1) for i in range(12)]
    trading_day(store, date(2026, 10, 30), [*range(100, 112)])
    paper.decide(store, oslo(date(2026, 10, 30), 22, 45), scanner=advisor)
    november = date(2026, 11, 2)
    trading_day(store, november, [*range(100, 112)])
    advisor.picks = [
        *(pick(300 + i, i + 1) for i in range(3)),  # new names at the top
        pick(100, 20),  # down, but still among the best 24: kept
        pick(101, 30),  # below 24: sold
        pick(102, None, eligible=False, exclusion="P/E under 4"),  # no longer eligible: sold
        *(pick(103 + i, 4 + i) for i in range(9)),
    ]

    summary = paper.decide(store, oslo(november, 22, 45), scanner=advisor)

    assert summary["rebalance"]
    placed = [o for o in orders(store) if o["decided_on"] == november]
    sold = {o["instrument_id"]: o["reason"] for o in placed if o["side"] == "sell"}
    assert sold == {101: "Falt til plass 30; beholdes bare til og med plass 24",
                    102: "Ikke lenger kvalifisert: P/E under 4"}
    assert [o["instrument_id"] for o in placed if o["side"] == "buy"] == [300, 301]  # back to 12 positions


def test_the_page_and_the_logs(store, make_client):
    for day in (MON, TUE, WED):
        snapshot(store, 1, day, 100, 101)
        snapshot(store, 2, day, 50, 52)
        sek_rate(store, day, 0.95)
    order(store, MON, 1, "buy", 100)
    order(store, MON, 2, "buy", 200, country="SE", currency="SEK", sleeve="short", signal_type="insider_cluster")
    order(store, WED, 1, "sell", 100)  # still waiting for Thursday's opening
    with store.engine.begin() as conn:
        conn.execute(store.table("paper_days").insert().values(
            account=paper.ACCOUNT, decided_on=MON, decided_at=oslo(MON, 22, 45), rebalance=True,
            recommendation_id=None, model_version="v2", equity=paper.START, cash=paper.START, orders=2,
            notes=["Første kveld"]))

    with make_client() as client:
        page = client.get("/lekepenger").text
        spreadsheet = client.get("/lekepenger/export.csv")
        log = client.get("/lekepenger/export.json")

    assert "Lekepenger" in page and "Stock 1" in page and "Første kveld" in page and "Oslo Børs" in page
    assert "Venter på åpningen" in page and "Kortsiktig" in page and page.count("<svg") == 1
    header, *rows = csv.reader(io.StringIO(spreadsheet.text.lstrip("﻿")), delimiter=";")
    assert len(rows) == 2 and "Kurtasje (NOK)" in header
    assert spreadsheet.headers["content-disposition"].startswith('attachment; filename="lekepenger-')
    data = log.json()
    assert list(data) == ["meta", "days", "orders", "trades", "positions", "dividends", "equity"]
    assert data["meta"]["fees"]["courtage_min_nok"] == 29.0 and len(data["equity"]) == 2
    assert [o["status"] for o in data["orders"]] == ["utført", "utført", "venter"]


@pytest.fixture
def make_client(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    from nordic_signals.web import app as web

    def make():
        for name in ("APP_PASSWORD", "RAILWAY_ENVIRONMENT_ID", "SECRET_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("SCHEDULER", "off")
        return TestClient(web.create_app(db_url))
    return make


def test_the_play_moneys_recommendations_stay_off_the_advice_page(store):
    from nordic_signals.advisor import recommend
    from nordic_signals.advisor.allocation import Policy
    from nordic_signals.web import queries

    mine = recommend.create(store, Policy(200_000))
    recommend.create(store, Policy(paper.START, **paper.POLICY), origin=paper.ORIGIN)
    assert [r["id"] for r in queries.recent_recommendations(store)] == [mine]
    assert queries.last_policy(store)["account_value"] == 200_000


def test_weekends_are_not_trading_days():
    assert paper.market_days("SE", FRI, NEXT_MON + timedelta(days=1)) == [NEXT_MON, NEXT_MON + timedelta(days=1)]
