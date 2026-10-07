"""The play-money Nordnet account: fills at the opening, Nordnet's fees, dividends, and the evening's decisions."""

import csv
import io
import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from nordic_signals.advisor import paper
from nordic_signals.collectors.base import NORDIC_TZ
from nordic_signals.web import paper_page
from nordic_signals.web.app import fmt_day

MON, TUE, WED, THU, FRI = (date(2026, 10, d) for d in (5, 6, 7, 8, 9))
NEXT_MON = date(2026, 10, 12)


def oslo(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), NORDIC_TZ)


def snapshot(store, instrument_id, day, opening, closing, *, traded=None, country="NO"):
    """Nordnet's stock list as the nightly run sees it on ``day``: after the close, with the last trade's time."""
    instruments = store.table("instruments")
    with store.engine.begin() as conn:
        if not conn.execute(instruments.select().where(instruments.c.instrument_id == instrument_id)).first():
            conn.execute(instruments.insert().values(instrument_id=instrument_id, symbol=f"S{instrument_id}",
                                                     exchange_country=country))
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
    monkeypatch.setitem(paper.POLICY, "min_position", 10_000.0)  # a small account, so the cut buy is kept
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


def yahoo_bar(store, symbol, day, opening, closing):
    """Yahoo's daily bar, stamped at the opening as Yahoo stamps Oslo and Stockholm; during the day, the close is
    the latest price."""
    with store.engine.begin() as conn:
        conn.execute(store.table("price_bars").insert().values(
            symbol=symbol, interval="1d", ts=int(oslo(day, 9).timestamp()), open=opening, close=closing))


def test_an_order_fills_at_the_opening_during_the_day(store):
    snapshot(store, 1, MON, 99, 100)
    order(store, MON, 1, "buy", 100)
    assert paper.account(store)["pending"] != []  # nothing from Tuesday yet

    yahoo_bar(store, "S1.OL", TUE, 102, 103.5)  # fetched at 11:00, while Oslo is open
    during = paper.account(store)
    (bought,) = during["trades"]
    assert (bought["day"], bought["price"], bought["at_close"]) == (TUE, 102, False) and during["pending"] == []
    assert during["valued_on"] == TUE and during["positions"][0]["price"] == 103.5  # the latest price

    snapshot(store, 1, TUE, 102, 104)  # the evening's snapshot after the close takes over
    assert paper.account(store)["positions"][0]["price"] == 104


def test_the_stocks_are_watched_while_a_market_is_open(store):
    for day in (MON, TUE):
        snapshot(store, 1, day, 100, 100)
    order(store, MON, 1, "buy", 10)
    order(store, TUE, 2, "buy", 10, country="SE", currency="SEK")  # for Wednesday's opening
    assert paper.watched_symbols(store, oslo(WED, 10)) == ["S1.OL", "S2.ST", "SEKNOK=X"]
    assert paper.watched_symbols(store, oslo(WED, 17)) == ["S1.OL", "S2.ST", "SEKNOK=X"]  # Stockholm until 17:30
    assert paper.watched_symbols(store, oslo(WED, 18)) != []  # an hour after Stockholm's close, for its closing price
    assert paper.watched_symbols(store, oslo(WED, 18, 45)) == []
    assert paper.watched_symbols(store, oslo(NEXT_MON - timedelta(days=2), 12)) == []  # Saturday


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
    snapshot(store, 999, day, 50.0, 50.0, country="SE")  # Stockholm's closing prices are in too


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


def test_it_needs_both_markets_closing_prices(store):
    advisor = Advisor()
    snapshot(store, 1, MON, 100, 100)  # Oslo's pages are in, Stockholm's are not
    assert paper.decide(store, oslo(MON, 22, 45), scanner=advisor)["note"] == "Mangler sluttkurser fra i dag"
    snapshot(store, 2, MON, 50, 50, country="SE")
    assert paper.decide(store, oslo(MON, 22, 45), scanner=advisor)["ok"] and advisor.calls


def test_a_retry_after_midnight_belongs_to_the_evening_before(store):
    advisor = Advisor()
    trading_day(store, MON, [1])
    summary = paper.decide(store, oslo(TUE, 1, 5), scanner=advisor)  # behind the nightly price job
    assert summary["ok"] and store.get("paper_days", account=paper.ACCOUNT, decided_on=MON)
    assert paper.evening_of(oslo(TUE, 5, 59)) == MON and paper.evening_of(oslo(TUE, 6)) == TUE


def test_orders_waiting_for_a_holiday_are_not_ordered_again(store):
    advisor = Advisor()
    advisor.signals = [pick(300 + i, 50 + i, signal="buyback_start") for i in range(3)]
    for day in (MON, TUE):
        trading_day(store, day, [1, 2])
    order(store, MON, 1, "buy", 100, sleeve="short", signal_type="buyback_start")
    order(store, MON, 2, "buy", 100, sleeve="short", signal_type="buyback_start")
    order(store, TUE, 1, "sell", 100, sleeve="short")  # its market is closed on Wednesday: still waiting
    order(store, TUE, 3, "buy", 100, sleeve="short", signal_type="buyback_start")
    state = paper.account(store)
    assert [o["instrument_id"] for o in state["pending"]] == [1, 3]

    with store.engine.begin() as conn:  # Wednesday evening: no new snapshot of stock 1, so its sale still waits
        conn.execute(store.table("paper_days").insert().values(
            account=paper.ACCOUNT, decided_on=MON, decided_at=oslo(MON, 22, 45), rebalance=True, equity=paper.START,
            cash=paper.START, orders=2, notes=[]))
    policy = paper.Policy(account_value=state["equity"], **paper.POLICY)
    orders, _ = paper._plan({**state, "positions": [{**p, "held_days": 5} for p in state["positions"]]}, policy,
                            paper.Scan(None, [], advisor.signals), False)
    # Stock 1's sale is already ordered; stock 2's is due; the pending buy of stock 3 holds the other slot.
    assert [(o["side"], o["instrument_id"]) for o in orders] == [("sell", 2), ("buy", 300)]


def test_a_buy_cut_below_the_smallest_position_lapses(store, monkeypatch):
    monkeypatch.setattr(paper, "START", 50_000.0)
    for day in (MON, TUE):
        snapshot(store, 1, day, 100, 100)
        snapshot(store, 2, day, 100, 100)
    order(store, MON, 1, "buy", 300)  # 30 000 NOK
    order(store, MON, 2, "buy", 240)  # 24 000 NOK, but only about 19 950 is left

    account = paper.account(store)

    assert [t["instrument_id"] for t in account["trades"]] == [1]
    assert account["lapsed"][0]["status"] == ("Ikke kjøpt: pengene som var igjen ved åpningen, ga en posisjon "
                                              "under 20 000 NOK")


def test_a_small_cut_from_a_higher_opening_is_kept(store, monkeypatch):
    monkeypatch.setattr(paper, "START", 20_100.0)
    snapshot(store, 1, MON, 100, 100)
    snapshot(store, 1, TUE, 101, 101)
    order(store, MON, 1, "buy", 200)  # 20 000 NOK at Monday's close

    (bought,) = paper.account(store)["trades"]

    assert bought["shares"] == 198 and bought["value"] < paper.POLICY["min_position"]  # 2 shares short: kept


def test_short_term_buys_fill_first_so_a_long_term_buy_takes_a_higher_opening(store, monkeypatch):
    monkeypatch.setattr(paper, "START", 62_500.0)
    snapshot(store, 1, MON, 100, 100)
    snapshot(store, 2, MON, 100, 100)
    snapshot(store, 1, TUE, 106, 106)  # opens 6 % higher
    snapshot(store, 2, TUE, 100, 100)
    order(store, MON, 1, "buy", 374)  # 37 400 NOK at Monday's close, planned first
    order(store, MON, 2, "buy", 249, sleeve="short", signal_type="buyback_start")  # 24 900 NOK

    short, long = paper.account(store)["trades"]

    assert (short["instrument_id"], short["shares"]) == (2, 249)  # all of it
    assert long["instrument_id"] == 1 and 0.9 * 374 < long["shares"] < 374  # cut, and still well above 20 000 NOK


def test_the_evening_orders_no_position_below_the_smallest(store):
    policy = paper.Policy(account_value=paper.START, **paper.POLICY)
    signals = [pick(300 + i, 50 + i, signal="buyback_start") for i in range(2)]

    placed, notes = paper._plan({"cash": 35_000.0, "positions": [], "pending": []}, policy,
                                paper.Scan(None, [], signals), False)

    # The first signal gets its 25 000 NOK slot; the 10 000 NOK left would be half the smallest position.
    assert [(o["instrument_id"], o["shares"]) for o in placed] == [(300, 249)]
    assert notes == ["1 kortsiktige signaler ble ikke kjøpt: ingen ledig plass eller for lite penger."]


def waiting_buy(instrument_id, sleeve, shares):
    return {"instrument_id": instrument_id, "side": "buy", "sleeve": sleeve, "shares": shares, "ref_price": 100.0,
            "fx_rate": 1.0, "currency": "NOK"}


def test_a_waiting_long_buy_counts_toward_the_twelve(store):
    policy = paper.Policy(account_value=paper.START, **paper.POLICY)
    state = {"cash": 374 * 100.15 + 50_000 + 40_000,  # the waiting buy, the short-term part, and 40 000 more
             "positions": [{"instrument_id": 100 + i, "sleeve": "long", "value": 37_500.0} for i in range(11)],
             "pending": [waiting_buy(111, "long", 374)]}

    placed, notes = paper._plan(state, policy, paper.Scan(7, [pick(100 + i, i + 1) for i in range(14)], []), True)

    assert placed == [] and notes == []  # eleven held and one on its way: twelve


def test_a_waiting_short_buys_money_is_not_held_back_twice(store):
    policy = paper.Policy(account_value=paper.START, **paper.POLICY)
    state = {"cash": 450_000 + 250 * 100.15,  # the long part's money, and the waiting short-term buy's
             "positions": [{"instrument_id": 50, "sleeve": "short", "value": 25_000.0, "held_days": 1}],
             "pending": [waiting_buy(51, "short", 250)]}

    placed, notes = paper._plan(state, policy, paper.Scan(7, [pick(100 + i, i + 1) for i in range(12)], []), True)

    # The short-term part is full, one held and one on its way, so all of the rest buys the twelve.
    assert [o["shares"] for o in placed] == [374] * 12 and notes == []


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


def test_the_page_and_the_logs(store, make_client, monkeypatch):
    for day in (MON, TUE, WED):
        snapshot(store, 1, day, 100, 101)
        snapshot(store, 2, day, 50, 52)
        snapshot(store, 3, day, 100, 100)
        sek_rate(store, day, 0.95)
    order(store, MON, 1, "buy", 100)
    order(store, MON, 2, "buy", 200, country="SE", currency="SEK", sleeve="short", signal_type="insider_cluster")
    order(store, WED, 1, "sell", 100)  # still waiting for Thursday's opening
    order(store, MON, 3, "buy", 10_000)  # far more than the cash left: cut at the opening
    with store.engine.begin() as conn:
        conn.execute(store.table("paper_days").insert().values(
            account=paper.ACCOUNT, decided_on=MON, decided_at=oslo(MON, 22, 45), rebalance=True,
            recommendation_id=None, model_version="v2", equity=paper.START, cash=paper.START, orders=2,
            notes=["Første kveld"]))

    monkeypatch.setattr(paper_page, "utcnow", lambda: oslo(WED, 23))
    with make_client() as client:
        page = client.get("/lekepenger").text
        spreadsheet = client.get("/lekepenger/export.csv")
        log = client.get("/lekepenger/export.json")
        monkeypatch.setattr(paper_page, "utcnow", lambda: oslo(THU, 11))  # Oslo is open, Thursday's price not in
        opened = client.get("/lekepenger").text

    assert "Lekepenger" in page and "Stock 1" in page and "Første kveld" in page and "Oslo Børs" in page
    assert "Venter på åpningen" in page and "Kortsiktig" in page and page.count("<svg") == 1
    assert f"til sluttkurs {fmt_day(WED)}" in page
    assert "Utført ved åpningen, venter på kursen" in opened and "Venter på åpningen" not in opened
    assert "utført ved åpningen" in opened and "til sluttkurs" in opened  # Thursday is not priced yet
    header, *rows = csv.reader(io.StringIO(spreadsheet.text.lstrip("﻿")), delimiter=";")
    assert len(rows) == 3 and "Kurtasje (NOK)" in header
    assert "planlagt" in page and "90&nbsp;% av aksjene, faller" in page
    assert spreadsheet.headers["content-disposition"].startswith('attachment; filename="lekepenger-')
    data = log.json()
    assert list(data) == ["meta", "days", "orders", "trades", "positions", "dividends", "equity"]
    assert data["meta"]["fees"]["courtage_min_nok"] == 29.0 and len(data["equity"]) == 2
    assert [o["status"] for o in data["orders"]] == ["utført", "utført", "delvis utført", "venter"]  # by evening
    assert data["orders"][2]["note"].endswith("aksjer: ikke nok penger ved åpningen")


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
