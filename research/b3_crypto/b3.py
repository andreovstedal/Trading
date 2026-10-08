"""B3: the crypto trade-or-hold decision, as pre-registered in research/PREREGISTRATION.md (8 October 2026).

Run:  .venv/bin/python research/b3_crypto/b3.py [--cache DIR] [--offline]

Eight rules against buy and hold on the account's coin book (31.25 % BTC and ETH, 12.5 % XRP, ADA and SOL), with
Firi's fee and the spreads seen in the account, the 20 % band, 22 % tax on realised gains with both books sold at
the end, and the three tests and the deflated Sharpe ratio of the bar. "Losses deductible" is read two ways: a
year's net loss refunded at 22 % in cash (deducted from other income), or carried forward to later gains (after the
check); a rule clears only if it clears in both. Writes results.json and results.md next to this file. The replay
is ``engine`` (checked against ``nordic_signals.crypto.account`` in ``crosscheck``).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import fmean, median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import crosscheck  # noqa: E402
import data  # noqa: E402
import engine  # noqa: E402
import report  # noqa: E402
import readme_check  # noqa: E402
import stats  # noqa: E402

log = logging.getLogger("b3")

CACHE = Path("/tmp/claude-0/-home-user-Trading/0a31d734-cb89-583d-8276-7cd774b8c998/scratchpad/data/b3_crypto")
YAHOO = {"BTC": "BTC-USD", "ETH": "ETH-USD", "XRP": "XRP-USD", "ADA": "ADA-USD", "SOL": "SOL-USD"}
WEIGHTS = {"BTC": 0.3125, "ETH": 0.3125, "XRP": 0.125, "ADA": 0.125, "SOL": 0.125}  # the 80 % of coins, to 100 %
SPREADS = {"BTC": 0.0033, "ETH": 0.015, "XRP": 0.010, "ADA": 0.007, "SOL": 0.011}  # each way, seen in the account
LAST = date(2026, 10, 7)  # the last day that is over
PERIODS = {"from 2018-07": date(2018, 7, 1), "from 2020-11": date(2020, 11, 1)}
WINDOW_MONTHS = 36
HOLDOUT = (date(2010, 7, 19), date(2018, 6, 30))  # Coin Metrics' first PriceUSD is 18 July 2010
TRIALS = len(engine.RULES)
FX = "NOK=X"  # NOK per USD


def load(cache: Path, offline: bool) -> tuple[dict[str, engine.Series], engine.Series, dict[date, float], dict]:
    dl = data.Downloader(cache, offline=offline)
    try:
        series, info = {}, {}
        for coin, symbol in YAHOO.items():
            closes = data.yahoo_closes(dl.yahoo(symbol), LAST)
            filled, gaps = data.fill(closes)
            series[coin] = engine.Series(filled)
            info[symbol] = data.describe(closes) | {"days_filled": len(gaps), "source": "Yahoo, interval=1d"}
        cm = data.coinmetrics_closes(dl.coinmetrics_btc(), date(2009, 1, 1), HOLDOUT[1])
        filled, gaps = data.fill(cm)
        btc = engine.Series(filled)
        info["BTC (holdout)"] = data.describe(cm) | {"days_filled": len(gaps),
                                                      "source": "Coin Metrics community data, csv/btc.csv, PriceUSD"}
        usdnok = data.fx_closes(dl.yahoo(FX), LAST)
        info[FX] = data.describe(usdnok) | {"source": "Yahoo, interval=1d (exploratory NOK run only)"}
        info["network_requests"] = dl.network_requests
        return series, btc, usdnok, info
    finally:
        dl.close()


def window_starts() -> list[date]:
    out, start = [], PERIODS["from 2018-07"]
    while engine.add_months(start, WINDOW_MONTHS) - timedelta(days=1) <= LAST:
        out.append(start)
        start = engine.add_months(start, 1)
    return out


def costs(r: engine.Result) -> dict:
    mean_value = fmean(v for _, v in r.curve)
    return {"trades_per_year": r.trades / r.years, "costs_per_year": (r.fees + r.spread) / mean_value / r.years,
            "fees": r.fees, "spread": r.spread}


def summary(r: engine.Result, pre: engine.Result, carry: engine.Result) -> dict:
    """``r`` with tax and net losses refunded, ``carry`` with them carried forward, ``pre`` the same book without
    tax: the worst fall, the daily returns, the trades and the costs are ``pre``'s (the taxed runs also sell to pay
    the tax)."""
    refunds = [s for s in r.settlements if s["tax"] < 0 and s["book"] > 0]
    big = min(refunds, key=lambda s: s["tax"] / s["book"], default=None)
    worst = min((s["net_gain"] for s in r.settlements), default=0.0)
    return {"start": r.start.isoformat(), "end": r.end.isoformat(), "years": r.years,
            "net_cagr": r.cagr(after_tax=True), "net_cagr_carry": carry.cagr(after_tax=True),
            "pre_tax_cagr": pre.cagr(after_tax=False),
            "final_after_tax": r.after_tax, "final_after_tax_carry": carry.after_tax, "final_pre_tax": pre.pre_tax,
            "tax_paid": r.tax_paid, "tax_paid_carry": carry.tax_paid, "max_drawdown": pre.max_drawdown(),
            **costs(pre), "with_tax_sales": costs(r),
            "largest_refund": big and {"day": big["day"], "amount": -big["tax"], "book": big["book"],
                                       "share_of_book": -big["tax"] / big["book"]},
            "largest_net_loss_over_start": max(0.0, -worst) / engine.START,
            "settlements": r.settlements, "settlements_carry": carry.settlements}


def run_all(rule: engine.Rule, series: dict[str, engine.Series], weights: dict[str, float],
            spreads: dict[str, float], start: date, end: date) -> tuple[engine.Result, engine.Result, engine.Result]:
    """With tax (losses refunded), without tax, and with tax (losses carried forward)."""
    return (engine.run(rule, series, weights, spreads, start, end),
            engine.run(rule, series, weights, spreads, start, end, tax=False),
            engine.run(rule, series, weights, spreads, start, end, losses="carry"))


def in_nok(series: dict[str, engine.Series], usdnok: dict[date, float]) -> dict:
    """Exploratory, not pre-registered: the coins' closes times USD/NOK (the last FX close on or before the day;
    an FX close is about 23:00 UTC), so cash is kroner and the tax is on gains in kroner, as on Firi."""
    fx = engine.Series(data.fill(usdnok)[0])
    nok = {}
    for c, s in series.items():
        days = [d for d in s.days if d >= fx.first]
        nok[c] = engine.Series({d: s.close(d) * fx.on_or_before(d) for d in days})
    rules = (engine.HOLD,) + engine.RULES
    out: dict = {"periods": {}, "windows_median": {}}
    for label, start in PERIODS.items():
        out["periods"][label] = {r.name: engine.run(r, nok, WEIGHTS, SPREADS, start, LAST).cagr() for r in rules}
    for r in rules:
        xs = [engine.run(r, nok, WEIGHTS, SPREADS, st, engine.add_months(st, WINDOW_MONTHS) - timedelta(days=1)).cagr()
              for st in window_starts()]
        out["windows_median"][r.name] = median(xs)
    return out


def deferred_cagr(r: engine.Result) -> float:
    """After tax as if it were all paid at the end, from a run without tax: start + 78 % of the gain."""
    final = r.pre_tax - engine.TAX * (r.pre_tax - engine.START)
    return (final / engine.START) ** (1 / r.years) - 1


def tax_timing(series: dict[str, engine.Series]) -> dict:
    """Exploratory, not pre-registered: tests 1 and 2 with the tax settled on 1 June of the next year (about when
    Norway's assessment comes) and with all of it deferred to the end (not how Norway taxes; a bound)."""
    rules = (engine.HOLD,) + engine.RULES
    out: dict = {}
    for variant in ("1 June next year", "all at the end"):
        def cagr(rule: engine.Rule, start: date, end: date, variant: str = variant) -> float:
            if variant == "all at the end":
                return deferred_cagr(engine.run(rule, series, WEIGHTS, SPREADS, start, end, tax=False))
            return engine.run(rule, series, WEIGHTS, SPREADS, start, end, tax_month=6).cagr()
        res: dict = {"periods": {}, "windows_median": {}}
        for label, start in PERIODS.items():
            res["periods"][label] = {r.name: cagr(r, start, LAST) for r in rules}
        for r in rules:
            res["windows_median"][r.name] = median(
                cagr(r, st, engine.add_months(st, WINDOW_MONTHS) - timedelta(days=1)) for st in window_starts())
        hold = engine.HOLD.name
        res["tests_1_and_2_pass"] = [
            r.name for r in engine.RULES
            if all(res["periods"][k][r.name] > res["periods"][k][hold] for k in PERIODS)
            and res["windows_median"][r.name] > res["windows_median"][hold]]
        out[variant] = res
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", type=Path, default=CACHE, help="where downloads are kept (default: %(default)s)")
    ap.add_argument("--offline", action="store_true", help="use only the cache")
    ap.add_argument("--out", type=Path, default=HERE)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    series, btc, usdnok, info = load(args.cache, args.offline)
    rules = (engine.HOLD,) + engine.RULES
    out: dict = {"data": info, "weights": WEIGHTS, "spreads": SPREADS, "fee": engine.FEE, "tax": engine.TAX,
                 "band": engine.TOLERANCE, "last_close": LAST.isoformat()}

    log.info("cross-check against crypto.py")
    out["crosscheck"] = crosscheck.compare(series, WEIGHTS, SPREADS, PERIODS["from 2020-11"], LAST)

    log.info("test 1: the two periods")
    periods: dict[str, dict[str, tuple[engine.Result, engine.Result, engine.Result]]] = {}
    for label, start in PERIODS.items():
        periods[label] = {r.name: run_all(r, series, WEIGHTS, SPREADS, start, LAST) for r in rules}
    out["periods"] = {label: {name: summary(*rr) for name, rr in res.items()} for label, res in periods.items()}
    for label, res in periods.items():
        hold = res[engine.HOLD.name][1].daily_returns()
        for rule in engine.RULES:
            out["periods"][label][rule.name]["vs_hold_pre_tax"] = stats.difference(
                res[rule.name][1].daily_returns(), hold)

    log.info("test 2: 3-year windows")
    starts = window_starts()

    def window_cagrs(losses: str) -> dict[str, list[float]]:
        return {r.name: [engine.run(r, series, WEIGHTS, SPREADS, s, engine.add_months(s, WINDOW_MONTHS)
                                    - timedelta(days=1), losses=losses).cagr() for s in starts] for r in rules}

    windows, windows_carry = window_cagrs("refund"), window_cagrs("carry")
    hold_w = windows[engine.HOLD.name]
    out["windows"] = {"starts": [s.isoformat() for s in starts], "count": len(starts),
                      "independent": (LAST - starts[0]).days / 365.25 / 3, "net_cagr": windows,
                      "net_cagr_carry": windows_carry, "summary": {}}
    for name, xs in windows.items():
        q1, q2, q3 = stats.quartiles(xs)
        diffs = [a - b for a, b in zip(xs, hold_w, strict=True)]
        out["windows"]["summary"][name] = {"median": q2, "q1": q1, "q3": q3, "min": min(xs), "max": max(xs),
                                           "median_carry": median(windows_carry[name]),
                                           "median_difference": median(diffs),
                                           "share_beating_hold": sum(d > 0 for d in diffs) / len(diffs)}

    log.info("test 3: Bitcoin alone, 2010-2018 holdout")
    holdout_rules = (engine.HOLD,) + tuple(r for r in engine.RULES if r.kind in ("sma", "mom"))
    hold_out = {r.name: run_all(r, {"BTC": btc}, {"BTC": 1.0}, {"BTC": SPREADS["BTC"]}, *HOLDOUT)
                for r in holdout_rules}
    out["holdout"] = {name: summary(*rr) for name, rr in hold_out.items()}
    for rule in holdout_rules[1:]:
        out["holdout"][rule.name]["vs_hold_pre_tax"] = stats.difference(
            hold_out[rule.name][1].daily_returns(), hold_out[engine.HOLD.name][1].daily_returns())

    log.info("deflated Sharpe ratio")
    main_period = periods["from 2018-07"]
    out["dsr"] = {"period": "from 2018-07", "trials": TRIALS,
                  "returns": "daily, net of costs, before tax",
                  "rules": stats.deflated({r.name: main_period[r.name][1].daily_returns() for r in engine.RULES})}
    out["dsr"]["hold"] = stats.moments(main_period[engine.HOLD.name][1].daily_returns())
    out["dsr"]["hold"]["sr_annual"] = out["dsr"]["hold"]["sr"] * math.sqrt(365)

    log.info("the bar")
    bar = {}
    hold = engine.HOLD.name
    for rule in engine.RULES:
        dsr = out["dsr"]["rules"][rule.name]["dsr"]
        needs3 = rule.kind in ("sma", "mom")
        b: dict = {"dsr": dsr, "dsr_ok": dsr >= 0.95}
        for reading, cagr, med in (("refund", "net_cagr", "median"), ("carry", "net_cagr_carry", "median_carry")):
            t1 = all(out["periods"][k][rule.name][cagr] > out["periods"][k][hold][cagr] for k in PERIODS)
            w = out["windows"]["summary"]
            t2 = w[rule.name][med] > w[hold][med]
            t3 = (out["holdout"][rule.name][cagr] > out["holdout"][hold][cagr]) if needs3 else None
            b[reading] = {"test1_periods": t1, "test2_windows": t2, "test3_holdout": t3,
                          "clears": t1 and t2 and (t3 if needs3 else True) and dsr >= 0.95}
        # the refund reading's tests at the top level, as before the check
        b |= {k: b["refund"][k] for k in ("test1_periods", "test2_windows", "test3_holdout")}
        b["clears"] = b["refund"]["clears"] and b["carry"]["clears"]
        bar[rule.name] = b
    out["bar"] = bar
    cleared = [name for name, b in bar.items() if b["clears"]]
    if cleared:
        best = max(cleared, key=lambda n: out["windows"]["summary"][n]["median"])
        out["decision"] = {"cleared": cleared, "main_account": best, "yardstick": engine.HOLD.name}
    else:
        out["decision"] = {"cleared": [], "main_account": engine.HOLD.name,
                           "comparison": "200-day average"}

    log.info("exploratory: when the tax is paid")
    out["exploratory_tax_timing"] = tax_timing(series)

    log.info("exploratory: the same book in NOK")
    out["exploratory_nok"] = in_nok(series, usdnok)

    log.info("the README's backtest, step by step")
    out["readme_check"] = readme_check.decompose(series, SPREADS)

    (args.out / "results.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    (args.out / "results.md").write_text(report.markdown(out))
    log.info("decision: %s", out["decision"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
