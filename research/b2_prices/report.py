"""results.md from results.json: short, with tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# The key numbers of the run before the review (results.json of 8 October 2026, 10:15), for "Changed after the check"
BEFORE_CHECK = {"net_vs_index": 0.0065, "net_vs_index_t": 0.2378, "cost_a_year": 0.0388,
                "half_spread_cost_a_year": 0.0195, "ew_universe_cagr": 0.1265, "net_vs_ew_book_mix": -0.0018,
                "ic_momentum_pooled": 0.0335, "ic_momentum_pooled_t": 3.0335, "ic_momentum_stockholm_t": 2.1856,
                "ic_low_vol_pooled": 0.0731, "ic_low_vol_pooled_t": 6.099, "bottom_quintile": 0.0139}
REPAIR_LABELS = {"split_price": "w/o 1", "oslo_ex_dates": "w/o 2", "edge_sign": "w/o 3"}  # w/o 4: no change
Z_POWER = 1.96 + 0.84  # a two-sided 5 % test with 80 % power


def pct(x: float | None, d: int = 1, signed: bool = False) -> str:
    if x is None:
        return "–"
    s = f"{100 * x:+.{d}f}" if signed else f"{100 * x:.{d}f}"
    return s.replace("-", "−") + " %"


def num(x: float | None, d: int = 2) -> str:
    return "–" if x is None else f"{x:.{d}f}".replace("-", "−")


def verdict(t: float) -> str:
    if abs(t) < 2:
        return "not distinguishable from zero"
    return "positive" if t > 0 else "negative"


def write_report(r: dict[str, Any], path: Path) -> None:  # noqa: PLR0915
    b = r["books"]
    net, fees, gross = b["net"], b["fees only"], b["gross"]
    hi, lo = b["net, half-spread |EDGE| (high end)"], b["net, half-spread signed bucket mean (low end)"]
    u, p, ic, per, ck = r["universe"], r["parameters"], r["rank_ic"], r["period"], r["checks"]
    out: list[str] = []
    add = out.append
    add("# B2: the score's price-only part")
    add("")
    add("Pre-registered: the book vs the index blend, momentum's direction, turnover, costs; no bar. "
        f"The rest, in *italics*, is exploratory. {per['months']} months, April 2013 to September 2026. "
        "`.venv/bin/python research/b2_prices/b2.py [--cache DIR] [--offline]`.")
    add("")
    gone = [y for y, v in ck["delisted_examples_on_yahoo"].items() if v.startswith("missing")]
    add("**Survivorship:** the universe is today's Nordnet list. Missing failures flatter the EW universe and the "
        f"bottom quintile; missing takeover targets (Yahoo has nothing for {', '.join(gone)}), low-volatility names "
        "the book would often have held, cost it their bid premiums. Against the indices the direction is unknown.")
    add("")
    add("## Method")
    add("")
    early = u["nordnet_instruments_kept"] - u["yahoo_missing"] - u["yahoo_history_starts_after_2012_03"]
    add(f"- **Universe:** {u['nordnet_instruments_kept']} shares ({u['by_country']['NO']} Oslo, "
        f"{u['by_country']['SE']} Stockholm); Yahoo has {u['nordnet_instruments_kept'] - u['yahoo_missing']}, "
        f"{early} from early 2012. Eligible: quoted price ≥ {p['min_price_nok']:.0f} NOK (close × later splits), "
        "12 months of prices, 12-month rise ≤ 300 %, volume on ≥ 10 of 20 sessions, median turnover ≥ "
        f"{p['min_adv_nok'] / 1e6:.3f} mill. NOK, one share class per issuer; no market-cap or P/E filter.")
    add("- **Score** (`scoring.py`): mom = (1 + r₁₂ₘ)/(1 + r₁ₘ) − 1; vol = sd(log total returns, last 61 closes) × √252; "
        "ranks within country; score = mean(rank_mom, 1 − rank_vol).")
    add(f"- **Book:** signal at the month-end close, trade at the next opening (the paper account: a trading day "
        f"later); top {p['n_positions']} bought, kept while ≤ {p['hold_rank']}.")
    add(f"- **Costs:** `paper.costs` plus an EDGE half-spread (`bidask.edge(sign=True)`, {p['edge_window_days']} "
        "days, negatives as 0, cap 5 %).")
    add("- **Statistics:** a year = 12 × mean monthly excess; SE = 12 × sd/√n; t = mean/(sd/√n).")
    add("")
    add("## Results")
    add("")
    add("| | Book net | Gross | Index blend | *EW universe* |")
    add("|---|---|---|---|---|")
    for label, key in [("Return a year", "cagr"), ("Volatility", "vol"), ("Max drawdown", "max_drawdown")]:
        add(f"| {label} | {pct(net['book'][key])} | {pct(gross['book'][key])} | "
            f"{pct(net['index_blend'][key])} | {pct(net['ew_universe'][key])} |")
    add("")
    add("| Excess a year | Net | Fees only | Gross |")
    add("|---|---|---|---|")
    for label, key in [("vs index blend", "vs_index"), ("*vs EW universe, book's country mix*", "vs_ew_universe_book_mix")]:
        add(f"| {label} | " + " | ".join(f"{pct(x[key]['excess_a_year'], signed=True)} ({num(x[key]['t'])})"
                                         for x in (net, fees, gross)) + " |")
    s = net["vs_index"]
    add("")
    add(f"t in brackets. Net vs index: SE {pct(s['se_a_year'])}, Newey–West (6 lags) t {num(s['t_newey_west'])}. All books pay 15 % "
        "Swedish withholding; indices and EW universe are untaxed.")
    add("")
    add("## Turnover and costs")
    add("")
    cp = net["cost_parts_a_year"]
    bk = u["edge_half_spread_by_bucket"]
    neg = sum(v["share_negative"] * v["n"] for v in bk.values()) / sum(v["n"] for v in bk.values())
    liquid = [v["share_negative"] for k, v in bk.items() if k.endswith("over 50 mill. NOK")]
    fl = ck["net_book_fills"]
    add(f"Turnover {pct(net['monthly_turnover_one_way'], 0)} a month, one way. Costs {pct(net['cost_a_year'], 2)} a "
        f"year: courtage {pct(cp['courtage'], 2)}, FX {pct(cp['fx'], 2)}, half-spread {pct(cp['spread'], 2)}, an "
        f"estimate: {pct(lo['cost_parts_a_year']['spread'], 2)} with each bucket's mean signed estimate, "
        f"{pct(hi['cost_parts_a_year']['spread'], 2)} with |estimate| (net vs index "
        f"{pct(lo['vs_index']['excess_a_year'], signed=True)}, {pct(hi['vs_index']['excess_a_year'], signed=True)}). "
        f"{pct(neg, 0)} of estimates are negative ({pct(min(liquid), 0)[:-2]}–{pct(max(liquid), 0)} over 50 mill. NOK "
        f"a day): there EDGE is mostly noise. {pct(fl['buy']['share_opening_equals_previous_close'], 0)} "
        f"of buys and {pct(fl['sell']['share_opening_equals_previous_close'], 0)} of sells fill at an opening equal to "
        f"the previous close, probably Yahoo's filler (mean gaps {pct(fl['buy']['mean_gap_previous_close_to_fill'], 2, True)}"
        f", {pct(fl['sell']['mean_gap_previous_close_to_fill'], 2, True)}: no bias); EDGE without them: "
        f"{pct(fl['edge_on_buys']['mean_with_filled_openings_missing'], 2)} on the buys, not "
        f"{pct(fl['edge_on_buys']['mean_half_spread_charged'], 2)}.")
    add("")
    add("## Rank IC")
    add("")
    add("Spearman per month and country vs the next month's return from the next opening; pooled weights by stocks.")
    add("")
    add("| Theme | Oslo IC (t) | Stockholm | Pooled |")
    add("|---|---|---|---|")
    for theme, label in [("momentum", "Momentum 12-1"), ("low_vol", "*Low volatility*"), ("score", "*Score*")]:
        d = ic[theme]
        cells = [f"{num(d[c]['mean_ic'], 3)} ({num(d[c]['t'])})" if c in d else "–" for c in ("NO", "SE", "pooled")]
        add(f"| {label} | {' | '.join(cells)} |")
    add("")
    add("## Reading")
    add("")
    mom = ic["momentum"]
    add(f"- Net excess over the index blend {pct(s['excess_a_year'], signed=True)} a year (t {num(s['t'])}): "
        f"{verdict(s['t'])}. An observed edge needs about {pct(2 * s['se_a_year'])} a year for t = 2; a true edge below "
        f"about {pct(Z_POWER * s['se_a_year'])} is missed more often than 1 time in 5.")
    add(f"- Momentum's direction is {'positive' if mom['pooled']['mean_ic'] > 0 else 'negative'} ("
        f"{pct(mom['pooled']['share_positive'], 0)} of months above zero); Stockholm alone: t {num(mom['SE']['t'])}.")
    h = net["halves_vs_index"]
    h0, h1 = list(h)
    q = r["score_quintiles_a_year"]
    add(f"- *Exploratory:* net vs index {h0[:4]}–{h0[-7:-3]} {pct(h[h0]['excess_a_year'], signed=True)} (t "
        f"{num(h[h0]['t'])}), {h1[:4]}–{h1[-7:-3]} {pct(h[h1]['excess_a_year'], signed=True)} (t {num(h[h1]['t'])}). "
        f"Score quintiles (EW gross, best first): {', '.join(pct(x, 1) for x in q)}.")
    add("")
    add("## Repairs and gaps")
    add("")
    od = ck["oslo_dividends"]
    yb, yc = (od["median_fall_by_year_n_on_ex_date_day_before_yahoo"],
              od["median_fall_by_year_n_on_ex_date_day_before_corrected"])

    def rng(d: dict[str, list[float]], years: range, k: int) -> str:
        vals = [d[str(y)][k] for y in years if str(y) in d]
        return f"{num(min(vals))}…{num(max(vals))}"

    add(f"- Yahoo's Oslo ex-dates {od['window'][0][:7]} to {od['window'][1][:7]} are a trading day late: median fall "
        f"(in dividends) on Yahoo's date / the day before, 2012–20 {rng(yb, range(2012, 2021), 1)} / "
        f"{rng(yb, range(2012, 2021), 2)}, 2021–23 {rng(yb, range(2021, 2024), 1)} / {rng(yb, range(2021, 2024), 2)}. "
        f"{od['moved_a_trading_day_earlier']} moved a day earlier (after: {rng(yc, range(2021, 2025), 1)} / "
        f"{rng(yc, range(2021, 2025), 2)}); volatility uses our total return.")
    add(f"- {u['one_day_spikes_repaired'] + u['fx_spikes_repaired']} one-day spikes, "
        f"{u['bad_opens_replaced_by_previous_close']} openings outside the day's range, {u['bad_dividends_dropped']} "
        "dividends over 20 % without a price drop. Not modelled: tax, price impact, waiting orders.")
    add("")
    add("## Changed after the check")
    add("")
    pf, fz = ck["price_floor"], ck["frozen_series"]
    add(f"A review found four real errors, fixed: (1) the 5 NOK floor used the split-adjusted close, admitting "
        f"{pf['rows_under_5_nok_quoted_but_not_split_adjusted']} stock-months quoted under 5 NOK (BNOR: 35 500 for "
        f"3.55); (2) the late ex-dates; (3) negative EDGE estimates charged as positive (costs were "
        f"{pct(BEFORE_CHECK['cost_a_year'], 2)}); (4) frozen series (BNOR ranked 1st, volatility 0): the volume "
        f"rule drops {fz['of_which_turnover_passed']} eligible stock-months. Added: book-mix EW, cost ranges; "
        "reworded survivorship, labels, power. Each w/o turns one repair off (`--undo`):")
    add("")
    ca = r.get("changed_after_check")
    if ca:
        cols = [BEFORE_CHECK, ca["with_all_repairs"], *[ca["without_one_repair"][k] for k in REPAIR_LABELS]]
        add("| | Before | After | " + " | ".join(REPAIR_LABELS.values()) + " |")
        add("|---" * (len(cols) + 1) + "|")
        rows = [("Net vs index, %", "net_vs_index"), ("*EW universe, %*", "ew_universe_cagr"),
                ("Momentum IC, t", "ic_momentum_pooled_t"), ("*Low-vol IC*", "ic_low_vol_pooled"),
                ("*Bottom quintile, %*", "bottom_quintile")]
        for label, key in rows:
            cells = [num(c[key]) if key.endswith("_t") else num(c[key], 3) if key.startswith("ic_")
                     else pct(c[key], 1, signed=key.startswith("net"))[:-2] for c in cols]
            add(f"| {label} | " + " | ".join(cells) + " |")
        add("")
        moves = max(abs(ca["with_all_repairs"]["net_vs_index"] - c["net_vs_index"]) for c in cols[2:])
        add(f"Each repair moves the book's excess by at most {100 * moves:.1f} points, inside its SE.")
    path.write_text("\n".join(out) + "\n")
