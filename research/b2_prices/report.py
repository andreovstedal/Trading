"""results.md from results.json: short, with tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
    net, fees, gross, cap = (b["net"], b["fees only"], b["gross"], b["net, sector cap 3 (exploratory)"])
    u, p, ic = r["universe"], r["parameters"], r["rank_ic"]
    per = r["period"]
    lines: list[str] = []
    add = lines.append
    add("# B2: the score's price-only part")
    add("")
    add(f"Pre-registered in `research/PREREGISTRATION.md`; it sets no bar and moves no money. "
        f"{per['months']} months, April 2013 to September 2026. Run: `.venv/bin/python research/b2_prices/b2.py` "
        f"(`--cache DIR`, `--offline`).")
    add("")
    add("**Survivorship, stated with every number below:** the universe is today's Nordnet list, so every stock "
        "that was delisted between 2013 and 2026 (bankruptcies, takeovers, mergers, moves abroad) is missing. "
        "Those are disproportionately the losers, so the equal-weighted universe and the book look better than "
        "they were, and the comparison with the indices, which held those stocks, is biased in the book's favour. "
        "The comparison with the equal-weighted universe shares the bias, which falls more on the losing, "
        "volatile stocks the score avoids; if anything that understates the book's edge over its own universe.")
    add("")
    add("## What ran")
    add("")
    add(f"- **Universe:** {u['nordnet_instruments_kept']} shares on Nordnet's list on 8 Oct 2026 "
        f"({u['by_country']['NO']} Oslo, {u['by_country']['SE']} Stockholm; shares in other currencies dropped, "
        f"as `scoring.py` has no rate for them). Yahoo has no history for {u['yahoo_missing']}. "
        f"Eligible each month-end, from prices alone: price ≥ {p['min_price_nok']:.0f} NOK, at least 12 months of "
        f"prices, 12-month rise ≤ 300 %, median daily turnover (Yahoo close × volume, last 20 days) ≥ "
        f"{p['min_adv_nok'] / 1e6:.3f} mill. NOK (50 × the {p['target_position_nok']:,.0f} NOK position), "
        "one share class per issuer (the most liquid). Not applied, for want of history: market cap ≥ 500 mill. "
        "NOK, positive P/E ≥ 4, so loss-makers are in.".replace(",", " "))
    add("- **Score** (as `features.py`/`scoring.py`): momentum = (1 + r₁₂ₘ)/(1 + r₁ₘ) − 1 on Yahoo's close; "
        "volatility = stdev of daily log returns of the last 61 adjusted closes within 100 days × √252 (≥ 40 "
        "returns); percentile ranks within country (ties averaged); score = mean(rank_mom, 1 − rank_vol).")
    add(f"- **Book:** at each month-end close, buy the best-ranked until {p['n_positions']} are held, keep "
        f"while ranked ≤ {p['hold_rank']}, trade at each stock's next opening; sales' cash is split equally "
        "between the buys (fully invested; held positions drift). Dividends at the ex-date, Swedish ones after "
        "15 % withholding. Start 450 000 NOK.")
    add(f"- **Costs:** `paper.costs` (0.15 %, min 29 NOK; 0.25 % currency exchange each way in Stockholm) plus a "
        f"half-spread from the EDGE estimator (Ardia, Guidotti & Kroencke 2024) on the last {p['edge_window_days']} "
        "days of OHLC, capped at 5 %; a missing estimate takes its country and liquidity bucket's median. "
        "`edge.py` is a pure-Python port of `bidask.edge` 2.1.0 (`check_edge.py`: identical on 300 windows).")
    add("- **Benchmarks:** OSEBX GI and OMXSBGI (× SEK/NOK) weighted by the book's country mix each month; the "
        "equal-weighted eligible universe (gross, no costs).")
    add("")
    add("## Results")
    add("")
    add("| | Book, net | Fees only | Gross | Index blend | EW universe |")
    add("|---|---|---|---|---|---|")
    rows = [("Return a year (CAGR)", "cagr"), ("Volatility", "vol"), ("Max drawdown", "max_drawdown")]
    for label, key in rows:
        add(f"| {label} | {pct(net['book'][key])} | {pct(fees['book'][key])} | {pct(gross['book'][key])} | "
            f"{pct(net['index_blend'][key])} | {pct(net['ew_universe'][key])} |")
    add("")
    add("Excess = book − benchmark, monthly. Excess a year = 12 × mean; SE = 12 × sd/√n; t = mean/(sd/√n) "
        "(Newey–West, 6 lags, beside it); tracking error = sd × √12; Sharpe of excess = excess a year / TE.")
    add("")
    add("| Book vs benchmark | Excess a year | SE | t (NW) | Tracking error | Sharpe of excess |")
    add("|---|---|---|---|---|---|")
    for label, book, key in [("Net vs index blend", net, "vs_index"), ("Fees only vs index", fees, "vs_index"),
                             ("Gross vs index", gross, "vs_index"), ("Net vs EW universe", net, "vs_ew_universe"),
                             ("Net vs EW universe, book's country mix", net, "vs_ew_universe_book_mix"),
                             ("*Exploratory:* sector cap 3, net vs index", cap, "vs_index")]:
        s = book[key]
        add(f"| {label} | {pct(s['excess_a_year'], signed=True)} | {pct(s['se_a_year'])} | "
            f"{num(s['t'])} ({num(s['t_newey_west'])}) | {pct(s['tracking_error'])} | {num(s['sharpe_of_excess'])} |")
    add("")
    halves = net["halves_vs_index"]
    hk = list(halves)
    add(f"Net vs index by half: {hk[0]} {pct(halves[hk[0]]['excess_a_year'], signed=True)} (t {num(halves[hk[0]]['t'])}), "
        f"{hk[1]} {pct(halves[hk[1]]['excess_a_year'], signed=True)} (t {num(halves[hk[1]]['t'])}). "
        f"Worst relative drawdown against the index blend: {pct(net['relative_max_drawdown_vs_index'])}. "
        f"The book held {pct(net['mean_se_share'], 0)} in Stockholm on average.")
    add("")
    add("## Turnover and costs")
    add("")
    cp = net["cost_parts_a_year"]
    drag = r["cost_drag_a_year"]
    add("| Monthly turnover (one way) | Trades a month | Costs a year | of which courtage / FX / half-spread | "
        "Cost drag (gross − net CAGR) | Half-spread paid, median |")
    add("|---|---|---|---|---|---|")
    add(f"| {pct(net['monthly_turnover_one_way'])} | {num(net['trades_a_month'], 1)} | {pct(net['cost_a_year'], 2)} | "
        f"{pct(cp['courtage'], 2)} / {pct(cp['fx'], 2)} / {pct(cp['spread'], 2)} | {pct(drag['gross_minus_net_cagr'], 2)} | "
        f"{pct(net.get('half_spread_paid_median'), 2)} |")
    add("")
    add("EDGE half-spreads of eligible stock-months, median by liquidity: " + "; ".join(
        f"{k} {pct(v['median'], 2)} (n {v['n']})" for k, v in u["edge_half_spread_median_by_bucket"].items()) + ".")
    add("")
    add("## Rank IC of each theme")
    add("")
    add("Spearman correlation, each month and country, of the theme's rank with the next month's local total "
        "return from the next opening; pooled = the two countries weighted by stocks; t = mean/(sd/√months).")
    add("")
    add("| Theme | Oslo: mean IC (t) | Stockholm: mean IC (t) | Pooled: mean IC (t) | Months |")
    add("|---|---|---|---|---|")
    for theme, label in [("momentum", "Momentum 12-1"), ("low_vol", "Low volatility"), ("score", "Score (both)")]:
        d = ic[theme]
        cells = [f"{num(d[c]['mean_ic'], 3)} ({num(d[c]['t'])})" if c in d else "–" for c in ("NO", "SE", "pooled")]
        add(f"| {label} | {' | '.join(cells)} | {d['pooled']['months'] if 'pooled' in d else '–'} |")
    add("")
    add("## Reading")
    add("")
    s = net["vs_index"]
    mom = ic["momentum"]["pooled"]
    add(f"- Net of costs the book's excess over the index blend was {pct(s['excess_a_year'], signed=True)} a year, "
        f"t = {num(s['t'])}: {verdict(s['t'])}. With {per['months']} months and a tracking error of "
        f"{pct(s['tracking_error'])}, the standard error is {pct(s['se_a_year'])} a year, so only an edge above "
        f"about {pct(2 * s['se_a_year'], 0)} a year could have shown at t = 2. Survivorship inflates this comparison.")
    e = net["vs_ew_universe"]
    add(f"- Against its own (equally survivor-biased) universe: {pct(e['excess_a_year'], signed=True)} a year, "
        f"t = {num(e['t'])}: {verdict(e['t'])}.")
    add(f"- Momentum's direction: pooled rank IC {num(mom['mean_ic'], 3)} (t {num(mom['t'])}), positive in "
        f"{pct(mom['share_positive'], 0)} of months. Low volatility: {num(ic['low_vol']['pooled']['mean_ic'], 3)} "
        f"(t {num(ic['low_vol']['pooled']['t'])}).")
    add(f"- Costs: about {pct(net['cost_a_year'], 1)} of the book a year at {pct(net['monthly_turnover_one_way'], 0)} "
        f"monthly one-way turnover; the half-spread is the larger part. If the opening auction's fill costs no "
        f"spread, as the paper account assumes, the fees-only line applies.")
    add("")
    add("## Gaps and what could not be done")
    add("")
    first = next(iter(u["eligible_by_month_end"].items()))
    last = list(u["eligible_by_month_end"].items())[-1]
    add(f"- **Delisted stocks are missing** (see the top). Eligible stocks: {first[1]['NO']} Oslo and "
        f"{first[1]['SE']} Stockholm in {first[0][:7]}, {last[1]['NO']} and {last[1]['SE']} in {last[0][:7]}; "
        f"the early years are thin because only survivors are in. {u['yahoo_history_starts_after_2012_03']} of "
        "the series start after March 2012 (listings since, or Yahoo history lost at a ticker change).")
    add(f"- Yahoo has no data for {u['yahoo_missing']} of today's shares: "
        f"{', '.join(u['yahoo_missing_symbols'][:12])}{' …' if u['yahoo_missing'] > 12 else ''}.")
    add("- No market-cap or P/E filter (no history of either), and today's Nordnet list stands in for each "
        "month's. The liquidity floor is in 2026 kroner throughout.")
    add(f"- Data repairs: {u['bad_opens_replaced_by_previous_close']} opening prices missing or outside the day's "
        f"range were replaced by the previous close; {u['bad_dividends_dropped']} Yahoo dividends of half the "
        "price or more were dropped.")
    sc = u["sector_coverage_ever_top60"]
    add(f"- Nordnet's list has no sectors (its `attributes` endpoint lists none), so the exploratory sector cap "
        f"uses Yahoo's sector (today's classification) for {sc['with_sector']} of the {sc['stocks']} stocks ever "
        "ranked in the top 60; the rest are uncapped.")
    add("- Not modelled: Norwegian tax (an ASK defers it), price impact, and the delay between the close and the "
        "evening decision.")
    path.write_text("\n".join(lines) + "\n")
