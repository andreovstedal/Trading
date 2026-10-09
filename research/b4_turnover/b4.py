"""B4: trading less (pre-registered in research/PREREGISTRATION.md, "B4: trading less").

B2's book, data, costs, universe and benchmark, under three hold rules:
  current    keep a holding while it ranks in the top 24, check every month (B2's book);
  wide       keep it while it ranks in the top 36, check every month;
  quarterly  keep it while it ranks in the top 24, check in January, April, July and October only.

A check "in January" is the account's first trading evening of January; B2 stands for that by the December
month-end close and trades at the next opening, so here a book trades after a month-end only when the next month
is a check month.

Bar: a rule replaces current if its net return a year (B2's "Return a year": the compound annual rate) beats
current's over the whole period and in each half (return months April 2013 to December 2019, January 2020 to
September 2026). If both clear it, the one with the higher whole-period net return.

Run:  .venv/bin/python research/b4_turnover/b4.py [--cache DIR] [--offline]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
B2_DIR = HERE.parent / "b2_prices"
sys.path.insert(0, str(B2_DIR))

import backtest as bt  # noqa: E402
from b2 import DEFAULT_CACHE, download  # noqa: E402
from data import Downloader  # noqa: E402

log = logging.getLogger("b4")

EVERY_MONTH = tuple(range(1, 13))
QUARTERS = (1, 4, 7, 10)
# The three pre-registered rules: (hold rank, calendar months in which the book trades)
RULES = {"current": (24, EVERY_MONTH), "wide": (36, EVERY_MONTH), "quarterly": (24, QUARTERS)}
# Exploratory: the other two phases of a quarterly check (not part of the bar)
OTHER_PHASES = {"quarterly, Feb/May/Aug/Nov (exploratory)": (24, (2, 5, 8, 11)),
                "quarterly, Mar/Jun/Sep/Dec (exploratory)": (24, (3, 6, 9, 12))}
SPLIT = date(2019, 12, 31)  # the last return month of the first half
TOLERANCE = 1e-9  # the current rule must reproduce B2's published net book to this


@dataclass
class RuleBook(bt.Book):
    """B2's Book with its hold rank and its check months as parameters. Outside a check month nothing is traded:
    holdings stay whatever their rank, and cash (from a buy that could not fill) waits for the next check. The
    first month-end always buys (the starting book), which matters only for the exploratory quarterly phases:
    the pre-registered quarterly rule's first signal (March 2013, traded in April) is a check anyway."""

    hold: int = bt.HOLD
    check_months: tuple[int, ...] = EVERY_MONTH

    def rebalance(self, market: bt.Market, me: date, rows: list[bt.Row]) -> None:
        if self.held_log and (me + timedelta(days=1)).month not in self.check_months:
            self.turnover.append(0.0)
            self.trades.append(0)
            self.cost_by_month.append(0.0)
            self.held_log.append(sorted(self.units))
            return
        saved = bt.HOLD  # Book.rebalance sells a holding ranked below the module's HOLD
        bt.HOLD = self.hold
        try:
            super().rebalance(market, me, rows)
        finally:
            bt.HOLD = saved


def cagr_between(returns: list[float], months: list[date], lo: date | None, hi: date | None) -> float:
    return bt.cagr([r for r, m in zip(returns, months, strict=True)
                    if (lo is None or m > lo) and (hi is None or m <= hi)])


PERIODS: dict[str, tuple[date | None, date | None]] = {"whole": (None, None), "first half": (None, SPLIT),
                                                       "second half": (SPLIT, None)}  # (after, up to and including)


def book_block(book: RuleBook, months: list[date], idx_nok: dict[str, list[float]]) -> dict[str, Any]:
    out: dict[str, Any] = {"hold_rank": book.hold, "check_months": list(book.check_months)}
    out["return_a_year"] = {p: cagr_between(book.returns, months, lo, hi) for p, (lo, hi) in PERIODS.items()}
    out["mean_return_a_year"] = {p: 12 * statistics.mean(r for r, m in zip(book.returns, months, strict=True)
                                                         if (lo is None or m > lo) and (hi is None or m <= hi))
                                 for p, (lo, hi) in PERIODS.items()}
    out["whole_period"] = bt.summary(book.returns)  # cagr, vol, max_drawdown, 12 × mean
    out["turnover_a_month_one_way"] = statistics.mean(book.turnover)
    out["turnover_a_year_one_way"] = 12 * out["turnover_a_month_one_way"]
    out["trades_a_year"] = 12 * statistics.mean(book.trades)
    out["cost_a_year"] = 12 * statistics.mean(book.cost_by_month)
    total = sum(book.cost_parts.values())
    out["cost_parts_a_year"] = {k: out["cost_a_year"] * v / total if total else 0.0 for k, v in book.cost_parts.items()}
    out["cost_a_year_by_half"] = {p: 12 * statistics.mean(c for c, m in zip(book.cost_by_month, months, strict=True)
                                                          if (lo is None or m > lo) and (hi is None or m <= hi))
                                  for p, (lo, hi) in PERIODS.items() if p != "whole"}
    # Months a position is held: a held month counts once per holding; ends = one per sale (and the open ones)
    held_months = sum(len(h) for h in book.held_log)
    sales = sum(1 for prev, cur in zip(book.held_log, book.held_log[1:], strict=False) for y in prev if y not in cur)
    out["mean_holding_months"] = held_months / (sales + len(book.held_log[-1]))
    out["mean_positions"] = statistics.mean(len(h) for h in book.held_log)
    bench = bt.blend(book, idx_nok)
    out["vs_index"] = bt.stats([a - b for a, b in zip(book.returns, bench, strict=True)])
    out["final_value_nok"] = book.equity[-1]
    return out


def paired(rule: RuleBook, base: RuleBook, months: list[date]) -> dict[str, Any]:
    """The monthly net-return difference rule − current: mean, SE = sd/√n, t (and Newey–West, 6 lags), by period."""
    d = [a - b for a, b in zip(rule.returns, base.returns, strict=True)]
    out = {}
    for p, (lo, hi) in PERIODS.items():
        x = [v for v, m in zip(d, months, strict=True) if (lo is None or m > lo) and (hi is None or m <= hi)]
        s = bt.stats(x)
        s["se_month"] = statistics.stdev(x) / math.sqrt(len(x))
        s["share_months_above"] = sum(v > 0 for v in x) / len(x)
        s["share_months_equal"] = sum(abs(v) < 1e-12 for v in x) / len(x)
        out[p] = s
    return out


def reproduce(current: RuleBook, b2_results: dict[str, Any], idx_nok: dict[str, list[float]]) -> dict[str, Any]:
    """The current rule against B2's published net book: every monthly return and the headline numbers."""
    pub = b2_results["books"]["net"]
    published_monthly = [m["net"] for m in b2_results["monthly"]]
    worst = max(abs(a - b) for a, b in zip(current.returns, published_monthly, strict=True))
    vs_index = bt.stats([a - b for a, b in zip(current.returns, bt.blend(current, idx_nok), strict=True)])
    pairs = {"cagr": (bt.cagr(current.returns), pub["book"]["cagr"]),
             "cost_a_year": (12 * statistics.mean(current.cost_by_month), pub["cost_a_year"]),
             "turnover_a_month": (statistics.mean(current.turnover), pub["monthly_turnover_one_way"]),
             "net_vs_index_a_year": (vs_index["excess_a_year"], pub["vs_index"]["excess_a_year"]),
             "final_value_nok": (current.equity[-1], pub["final_value_nok"])}
    ok = worst < TOLERANCE and all(abs(a - b) <= TOLERANCE * max(1.0, abs(b)) for a, b in pairs.values())
    return {"reproduces_b2": ok, "max_abs_monthly_difference": worst,
            "ours_vs_published": {k: list(v) for k, v in pairs.items()}}


def apply_bar(blocks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cur = blocks["current"]["return_a_year"]
    tests = {}
    for name in ("wide", "quarterly"):
        own = blocks[name]["return_a_year"]
        beats = {p: own[p] > cur[p] for p in ("whole", "first half", "second half")}
        tests[name] = {"beats_current": beats, "clears_bar": all(beats.values())}
    cleared = [n for n, t in tests.items() if t["clears_bar"]]
    winner = max(cleared, key=lambda n: blocks[n]["return_a_year"]["whole"]) if cleared else "current"
    out = {"tests": tests, "cleared": cleared, "next_stock_account_rule": winner}
    if len(cleared) == 2:  # the tie-break: the higher whole-period net return a year, and by how much
        a, b = (blocks[n]["return_a_year"]["whole"] for n in cleared)
        out["tie_break_margin_a_year"] = abs(a - b)
    return out


def run(dl: Downloader, stocks: list, out_dir: Path) -> dict[str, Any]:
    market, _ = bt.load(dl, stocks)
    signals = bt.month_ends(bt.FIRST_SIGNAL, bt.LAST_SIGNAL)
    log.info("scoring %d month-ends over %d stocks", len(signals), len(market.stocks))
    scored = {me: bt.score_month(market, me) for me in signals}
    months = signals[1:]
    idx_nok = bt.index_nok(market, signals)

    def make(name: str, hold: int, check: tuple[int, ...], **kw: Any) -> RuleBook:
        return RuleBook(name, hold=hold, check_months=check, **kw)

    books = {n: make(n, h, c) for n, (h, c) in RULES.items()}
    gross = {n: make(f"{n}, gross", h, c, fees=False, spread=False) for n, (h, c) in RULES.items()}
    phases = {n: make(n, h, c) for n, (h, c) in OTHER_PHASES.items()}
    current = books["current"]
    bt.run_books(market, signals, scored, [current])
    b2_results = json.loads((B2_DIR / "results.json").read_text())
    check = reproduce(current, b2_results, idx_nok)
    log.info("current vs B2: %s", check)
    if not check["reproduces_b2"]:
        raise SystemExit(f"the current rule does not reproduce B2's published net book: {check}")
    others = [b for n, b in books.items() if n != "current"] + list(gross.values()) + list(phases.values())
    bt.run_books(market, signals, scored, others)

    blocks = {n: book_block(b, months, idx_nok) for n, b in books.items()}
    results: dict[str, Any] = {
        "period": {"first_signal": signals[0].isoformat(), "first_return_month_end": months[0].isoformat(),
                   "last_return_month_end": months[-1].isoformat(), "months": len(months),
                   "halves": {"first half": [months[0].isoformat(), SPLIT.isoformat()],
                              "second half": [(SPLIT + timedelta(days=31)).isoformat(), months[-1].isoformat()]},
                   "months_by_half": {p: sum(1 for m in months if (lo is None or m > lo) and (hi is None or m <= hi))
                                      for p, (lo, hi) in PERIODS.items()}},
        "rules": {n: {"hold_rank": h, "check_months": list(c)} for n, (h, c) in RULES.items()},
        "bar_measure": "compound annual net return (B2's 'Return a year'), whole period and each half",
        "reproduction_of_b2": check,
        "books": blocks,
        "difference_from_current": {n: paired(b, current, months) for n, b in books.items() if n != "current"},
    }
    results["bar"] = apply_bar(blocks)
    results["exploratory"] = {
        "gross_books": {n: {"return_a_year": {p: cagr_between(b.returns, months, lo, hi)
                                              for p, (lo, hi) in PERIODS.items()},
                            "turnover_a_year_one_way": 12 * statistics.mean(b.turnover)}
                        for n, b in gross.items()},
        "gross_difference_from_current": {n: paired(b, gross["current"], months) for n, b in gross.items()
                                          if n != "current"},
        "other_quarterly_phases": {n: {**book_block(b, months, idx_nok), "difference_from_current":
                                       paired(b, current, months)} for n, b in phases.items()},
    }
    results["monthly"] = [{"month_end": m.isoformat(), **{n: b.returns[k] for n, b in books.items()},
                           **{f"{n} turnover": b.turnover[k] for n, b in books.items()}}
                          for k, m in enumerate(months)]
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, default=str))
    write_report(results, out_dir / "results.md")
    log.info("wrote %s", out_dir)
    return results


# The report

def pct(x: float, d: int = 1, signed: bool = False) -> str:
    s = f"{100 * x:+.{d}f}" if signed else f"{100 * x:.{d}f}"
    return s.replace("-", "−") + " %"


def num(x: float, d: int = 2) -> str:
    return f"{x:.{d}f}".replace("-", "−")


def write_report(r: dict[str, Any], path: Path) -> None:  # noqa: PLR0915
    b, diff, bar, ex = r["books"], r["difference_from_current"], r["bar"], r["exploratory"]
    rc, halves = r["reproduction_of_b2"], r["period"]["months_by_half"]
    names = list(r["rules"])
    out: list[str] = []
    add = out.append
    add("# B4: trading less")
    add("")
    add("Pre-registered (`research/PREREGISTRATION.md`, \"B4\"); *italics* are exploratory. B2's book, data, costs, "
        "universe (today's Nordnet list: delisted stocks missing) and benchmark; "
        f"{r['period']['months']} months, April 2013 to September 2026. "
        "`.venv/bin/python research/b4_turnover/b4.py --offline`.")
    add("")
    add("- **current:** keep a holding while it ranks in the top 24, check every month (B2's book).")
    add("- **wide:** top 36, every month.")
    add("- **quarterly:** top 24, check in January, April, July and October only (B2's December, March, June and "
        "September month-end signals); no trades in other months.")
    add("")
    same = "identical to" if rc["max_abs_monthly_difference"] == 0 else "within 1e-9 of"
    add(f"**Check:** *current*'s 162 monthly returns, costs and turnover are {same} B2's published net book "
        f"({'passed' if rc['reproduces_b2'] else 'FAILED'}).")
    add("")
    add("## The bar")
    add("")
    add("Net return a year (compound, as B2's \"Return a year\"); a rule must beat *current* in all three. Halves: "
        f"April 2013–December 2019 ({halves['first half']} months), January 2020–September 2026 "
        f"({halves['second half']}).")
    add("")
    add("| Rule | Whole period | 2013–2019 | 2020–2026 | Beats current in all three |")
    add("|---|---|---|---|---|")
    for n in names:
        ra = b[n]["return_a_year"]
        verdict = "–" if n == "current" else ("yes" if bar["tests"][n]["clears_bar"] else "no")
        add(f"| {n} | {pct(ra['whole'], 2)} | {pct(ra['first half'], 2)} | {pct(ra['second half'], 2)} | {verdict} |")
    add("")
    winner = bar["next_stock_account_rule"]
    if len(bar["cleared"]) == 2:
        other = next(n for n in bar["cleared"] if n != winner)
        add(f"**Outcome:** both clear the bar. By the tie-break (higher whole-period net return) **{winner}** replaces "
            f"*current* in the next stock account: {pct(b[winner]['return_a_year']['whole'], 3)} against {other}'s "
            f"{pct(b[other]['return_a_year']['whole'], 3)}, a margin of {100 * bar['tie_break_margin_a_year']:.3f} "
            "percentage points a year.")
    elif bar["cleared"]:
        add(f"**Outcome:** {winner} clears the bar and replaces *current* in the next stock account.")
    else:
        add("**Outcome:** neither rule clears the bar; *current* stays in the next stock account.")
    for n in ("wide", "quarterly"):
        failed = [p for p, ok in bar["tests"][n]["beats_current"].items() if not ok]
        if failed:
            add(f"- {n} fails in: {', '.join(failed)}.")
    add("")
    add("## Difference from current")
    add("")
    add("Rule's net monthly return minus *current*'s. SE = sd/√n; a year = 12 × a month.")
    add("")
    add("| Rule, period | Mean a month (SE) | A year (SE) | t |")
    add("|---|---|---|---|")
    for n in ("wide", "quarterly"):
        for p, label in (("whole", "whole"), ("first half", "2013–19"), ("second half", "2020–26")):
            s = diff[n][p]
            add(f"| {n}, {label} | {pct(s['mean_month'], 3, True)} ({pct(s['se_month'], 3)}) | "
                f"{pct(s['excess_a_year'], 2, True)} ({pct(s['se_a_year'], 2)}) | {num(s['t'])} |")
    add("")
    add("## Turnover and costs")
    add("")
    add("| | current | wide | quarterly |")
    add("|---|---|---|---|")
    rows = [("Turnover a year, one way", lambda x: pct(x["turnover_a_year_one_way"], 0)),
            ("Trades a year", lambda x: num(x["trades_a_year"], 0)),
            ("Costs a year", lambda x: pct(x["cost_a_year"], 2)),
            ("– courtage", lambda x: pct(x["cost_parts_a_year"]["courtage"], 2)),
            ("– currency exchange", lambda x: pct(x["cost_parts_a_year"]["fx"], 2)),
            ("– half-spread (estimate)", lambda x: pct(x["cost_parts_a_year"]["spread"], 2)),
            ("*Months a position is held*", lambda x: num(x["mean_holding_months"], 1)),
            ("*Volatility*", lambda x: pct(x["whole_period"]["vol"], 1)),
            ("*Max drawdown*", lambda x: pct(x["whole_period"]["max_drawdown"], 1))]
    for label, f in rows:
        add(f"| {label} | " + " | ".join(f(b[n]) for n in names) + " |")
    add("")
    g, gd = ex["gross_books"], ex["gross_difference_from_current"]
    cut = {n: b["current"]["cost_a_year"] - b[n]["cost_a_year"] for n in ("wide", "quarterly")}
    add("## Reading")
    add("")
    add("- Costs fall by " + " and ".join(f"{pct(cut[n], 2)} a year ({n})" for n in cut) + ". *Before costs, "
        "compound a year: " + ", ".join(f"{n} {pct(g[n]['return_a_year']['whole'], 2)}" for n in names)
        + "; difference from current " + ", ".join(
            f"{n} {pct(gd[n]['whole']['excess_a_year'], 2, True)} a year (t {num(gd[n]['whole']['t'])})"
            for n in ("wide", "quarterly")) + ": the gross return is about kept.*")
    t_max = max(abs(diff[n][p]["t"]) for n in diff for p in PERIODS)
    add(f"- The largest |t| of the net differences above is {num(t_max)}: "
        + ("none is distinguishable from zero. " if t_max < 2 else "")
        + "The bar asks for point estimates only, and the gap between wide and quarterly is far inside the noise.")
    add("")
    add("*The quarterly check's other two phases (not part of the bar), net:*")
    add("")
    add("| *Check months* | *Whole* | *2013–19* | *2020–26* | *Vs current a year (t)* | *Costs* |")
    add("|---|---|---|---|---|---|")
    for n, x in ex["other_quarterly_phases"].items():
        ra, d = x["return_a_year"], x["difference_from_current"]["whole"]
        label = n.split(", ")[1].split(" (")[0]
        add(f"| *{label}* | {pct(ra['whole'], 2)} | {pct(ra['first half'], 2)} | {pct(ra['second half'], 2)} | "
            f"{pct(d['excess_a_year'], 2, True)} ({num(d['t'])}) | {pct(x['cost_a_year'], 2)} |")
    add("")
    add("## Caveats")
    add("")
    add("- The account ranks on the whole score (value and quality too), which B4 cannot test; its turnover will "
        "differ. The direction carries over, not the size.")
    add("- B2's caveats apply: survivorship, the half-spread is an estimate, no price impact or tax, 15 % Swedish "
        "withholding in every book.")
    path.write_text("\n".join(out) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="B2's download cache")
    ap.add_argument("--offline", action="store_true", help="use only the cache; fail on anything missing")
    ap.add_argument("--out", type=Path, default=HERE, help="where results.json and results.md go")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    dl = Downloader(args.cache, offline=args.offline)
    try:
        stocks, _ = download(dl)
        args.out.mkdir(parents=True, exist_ok=True)
        run(dl, stocks, args.out)
    finally:
        dl.close()


if __name__ == "__main__":
    main()
