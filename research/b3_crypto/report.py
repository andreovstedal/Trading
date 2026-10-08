"""results.md for B3, from the results ``b3.main`` computed. Table cells carry no % sign (the headers say %)."""

from __future__ import annotations

HOLD = "Buy and hold"
SHORT = {"Buy and hold at 60 % volatility": "Volatility 60 %", "Top 2 by 3-month return": "Top 2",
         "12-week momentum": "Momentum"} | {f"{n}-day average": f"{n}-day" for n in (50, 100, 150, 200, 250)}
A, B = "from 2018-07", "from 2020-11"


def pct(x: float | None, digits: int = 1, sign: bool = False, unit: bool = True) -> str:
    if x is None:
        return "–"
    s = f"{x * 100:{'+' if sign else ''}.{digits}f}" + (" %" if unit else "")
    return s.replace("-", "−")


def num(x: float, digits: int = 1, sign: bool = False) -> str:
    return pct(x, digits, sign, unit=False)


def pair(a: float, b: float, digits: int = 1) -> str:
    return f"{num(a, digits)}/{num(b, digits)}"


def name(r: str) -> str:
    return SHORT.get(r, r)


def bar_section(out: dict) -> list[str]:
    per, win, hol, dsr, bar = out["periods"], out["windows"]["summary"], out["holdout"], out["dsr"], out["bar"]
    rules = list(per[A])
    top = "Top 2 by 3-month return"
    t2 = per[A][top]
    refund = t2["largest_refund"]
    loss_x = max(x["largest_net_loss_over_start"] for p in per.values() for x in p.values())
    L = [
        "## The bar",
        "",
        "Net return a year after costs and tax, %, as *refund*/*carry*: a year's net loss refunded at 22 % in "
        f"cash on 1 January (assumes other taxable income of up to {loss_x:.0f} times the starting capital), or "
        "carried forward, any rest refunded at the end. A rule must clear in both.",
        "",
        "| Rule | Jul 2018 | Nov 2020 | 3-yr median | BTC 2010–18 | DSR | Clears |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rules:
        h, x = hol.get(r), [per[A][r], per[B][r], win[r]]
        cells = [pair(x[0]["net_cagr"], x[0]["net_cagr_carry"]), pair(x[1]["net_cagr"], x[1]["net_cagr_carry"]),
                 pair(x[2]["median"], x[2]["median_carry"]),
                 pair(h["net_cagr"], h["net_cagr_carry"], 0) if h else "–"]
        if r == HOLD:
            L.append(f"| *{r}* | " + " | ".join(f"*{c}*" for c in cells) + " | – | – |")
        else:
            L.append(f"| {name(r)} | " + " | ".join(cells) + f" | {bar[r]['dsr']:.3f} | "
                     f"{'yes' if bar[r]['clears'] else '**no**'} |")
    fails = {reading: [sum(1 for b in bar.values() if b[reading][k] is False)
                       for k in ("test1_periods", "test2_windows", "test3_holdout")] for reading in ("refund", "carry")}
    f = fails["refund"]
    same = fails["refund"] == fails["carry"]
    failing = (f"Failing in {'both readings' if same else 'the refund reading'}: test 1, {f[0]} of 8; test 2, "
               f"{f[1]} of 8; test 3, {f[2]} of 6"
               + ("" if same else f" (carry: {fails['carry'][0]}, {fails['carry'][1]}, {fails['carry'][2]})") + ". ")
    beat_a = [r for r in bar if per[A][r]["net_cagr"] > per[A][HOLD]["net_cagr"]]
    first = (f"The {', '.join(beat_a)} beat holding from July 2018 by "
             f"{(per[A][beat_a[0]]['net_cagr'] - per[A][HOLD]['net_cagr']) * 100:.1f} points (refund), then lost "
             "from November 2020. " if beat_a else "")
    beat_h = [r for r in bar if r in hol and hol[r]["pre_tax_cagr"] > hol[HOLD]["pre_tax_cagr"]]
    srs = [v["sr_annual"] for v in dsr["rules"].values()]
    L += [
        "",
        failing + first
        + f"Before tax, {len(beat_h)} of the 6 beat holding Bitcoin, after tax none: they pay tax yearly, "
        "holding once at the end. "
        f"Refunds are large: top 2 got {refund['amount'] / 1000:.0f}k on {refund['day']}, "
        f"{pct(refund['share_of_book'], 0)} of its book; carrying losses forward, it ends at "
        f"{pct(t2['net_cagr_carry'])} and {pct(per[B][top]['net_cagr_carry'])}, below its before-tax "
        f"{pct(t2['pre_tax_cagr'])} and {pct(per[B][top]['pre_tax_cagr'])}. "
        f"The DSR reaches 0.95 for {sum(b['dsr_ok'] for b in bar.values())} of 8, but only shows a Sharpe ratio above "
        f"what the best of 8 skill-less trials would show ({dsr['rules'][rules[1]]['sr0_annual']:.2f} a year), not "
        f"above holding's ({dsr['hold']['sr_annual']:.2f}; rules {min(srs):.2f}–{max(srs):.2f}).",
    ]
    return L


def risk_section(out: dict) -> list[str]:
    per, win = out["periods"], out["windows"]
    rules = list(per[A])
    L = [
        "## Before tax, from July 2018",
        "",
        "| Rule | Return % | Worst fall % | Trades/yr | Costs/yr % | vs hold, log %/yr ±SE "
        "| Windows won after tax % |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rules:
        x = per[A][r]
        d = x.get("vs_hold_pre_tax")
        diff = f"{num(d['per_year'], 1, True)}±{num(d['se'])}" if d else "–"
        won = f"{win['summary'][r]['share_beating_hold'] * 100:.0f}" if r != HOLD else "–"
        L.append(f"| {name(r)} | {num(x['pre_tax_cagr'])} | {num(x['max_drawdown'], 0)} | "
                 f"{x['trades_per_year']:.0f} | {num(x['costs_per_year'])} | {diff} | {won} |")
    # the worst fall in both periods: which rules cut it, and by how much
    hold = min(per[k][HOLD]["max_drawdown"] for k in per)
    dd = {r: [per[k][r]["max_drawdown"] for k in per] for r in rules if r != HOLD}
    cut = [r for r, v in dd.items() if min(v) > hold + 0.1]  # by more than 10 points in both periods
    small = [r for r, v in dd.items() if hold < min(v) <= hold + 0.1]
    deeper = [r for r, v in dd.items() if min(v) <= hold]
    lo, hi = min(min(dd[r]) for r in cut), max(max(dd[r]) for r in cut)
    words = "None One Two Three Four Five Six Seven Eight".split()
    falls = (f"{words[len(cut)]} of 8 rules cut the worst fall ({pct(hi, 0)} to {pct(lo, 0)} across both periods, "
             f"against {pct(hold, 0)})")
    if small:
        falls += "; " + "; ".join(f"{name(r).lower()} only to {pct(min(dd[r]), 0)}" for r in small)
    if deeper:
        falls += "; " + "; ".join(f"{name(r).lower()} fell further, {pct(min(dd[r]), 0)}" for r in deeper)
    L += [
        "",
        falls + ". No difference reaches two standard errors (largest |t| "
        f"{max(abs(per[A][r]['vs_hold_pre_tax']['t']) for r in dd):.1f}, a loss). The {win['count']} windows "
        f"(starts {win['starts'][0][:7]} to {win['starts'][-1][:7]}; refund reading) overlap: about "
        f"{win['independent']:.1f} independent spans.",
    ]
    return L


def readme_section(out: dict) -> list[str]:
    """The README port's steps (``readme_check``) as one paragraph: its table, this engine, and the gap's moves."""
    rc = [row for row in out["readme_check"] if not row["step"].startswith("+ a coin with too short")]
    assert [row["step"][:12] for row in rc] == ["README scrip", "+ decide at ", "+ purchases ", "+ everything",
                                                "+ crypto.py'"], [row["step"] for row in rc]

    def hs(row: dict, y: str) -> str:
        return f"{num(row[f'from {y} hold'])}/{num(row[f'from {y} sma200'])} %"

    def gaps(y: str) -> tuple[list[float], list[float]]:
        g = [row[f"from {y} sma200"] - row[f"from {y} hold"] for row in rc]
        return g, [b - a for a, b in zip(g, g[1:])]

    (g18, s18), (g20, s20) = gaps("2018"), gaps("2020")
    return [
        "## The README's 200-day gap",
        "",
        "Ported to `readme_check.py`, the README's scratch script reproduces its table exactly (hold/200-day before "
        f"tax: {hs(rc[0], '2018')} from 2018, {hs(rc[0], '2020')} from 2020); this engine gives {hs(rc[-1], '2018')} "
        f"and {hs(rc[-1], '2020')}. Switching its differences one at a time (decide at 00:00 on the 1st; costs "
        "inside purchases; final sale at the bid; crypto.py's month) moves the gap "
        f"{num(g18[0])} → {num(g18[-1])} points from 2018 ({', '.join(num(x, 1, True) for x in s18)}) and "
        f"{num(g20[0])} → {num(g20[-1])} from 2020 ({', '.join(num(x, 1, True) for x in s20)}). B3's 2018 book also "
        "differs (SOL from 2020; XRP and ADA 12.5 %, not 18.75 %) and adds tax.",
    ]


def markdown(out: dict) -> str:
    dec = out["decision"]
    if dec["cleared"]:
        verdict = (f"**{', '.join(dec['cleared'])} clear{'s' if len(dec['cleared']) == 1 else ''} the bar; "
                   f"{dec['main_account']} has the highest median 3-year net return and becomes the main crypto "
                   f"account, with buy and hold as its yardstick.**")
    else:
        verdict = ("**No rule clears the bar: as pre-registered, buy and hold becomes the main crypto account, the "
                   "200-day rule stays beside it as the comparison, and the pump.fun part stays in both.**")
    tt, nok = out["exploratory_tax_timing"], out["exploratory_nok"]
    nok_pass = [r for r in nok["windows_median"] if r != HOLD
                and all(nok["periods"][k][r] > nok["periods"][k][HOLD] for k in nok["periods"])
                and nok["windows_median"][r] > nok["windows_median"][HOLD]]
    passes = [len(res["tests_1_and_2_pass"]) for res in tt.values()] + [len(nok_pass)]
    hold_pre = out["periods"][A][HOLD]
    L = [
        "# B3: crypto, trade or hold",
        "",
        "As pre-registered (`research/PREREGISTRATION.md`), run by `b3.py`: 31.25 % BTC and ETH, 12.5 % XRP, ADA "
        "and SOL; 20 % band; Firi's 0.7 % fee plus the account's spreads; 22 % tax on each year's net realised gain "
        "(FIFO), settled 1 January; both books sold at the end. Yahoo daily USD closes to 7 October 2026; Bitcoin "
        "2010–18 from Coin Metrics. Without tax, the replay matches `crypto.account` to 1e-15 (`crosscheck.py`).",
        "",
        verdict,
        "",
        *bar_section(out),
        "",
        *risk_section(out),
        "",
        *readme_section(out),
        "",
        "## Formulas and choices",
        "",
        "- Net return a year = (V_end/100000)^(365.25/days)−1, V_end after the final sale and tax.",
        "- Averages: hold while close > mean of the last N closes; momentum: close > close 84 days earlier; "
        "volatility: exposure = min(1, 0.60/σ), σ = √365·sd of the book's last 60 daily returns; top 2: equal "
        "halves by 3-month return. A coin short of history is held.",
        "- Chosen by the analyst, not in the pre-registration: book-level σ, top 2's equal halves, settlement on "
        "1 January, the refund reading, test 2 as median against median.",
        "- SE = 365·sd(d)/√T, d = daily log-return difference before tax. DSR = Φ((SR−SR0)√(T−1)/"
        "√(1−γ3·SR+(γ4−1)/4·SR²)), SR0 = √V[SR]·((1−γ)Φ⁻¹(1−1/8)+γΦ⁻¹(1−1/(8e))), on daily before-tax returns from "
        f"July 2018 (T = {out['dsr']['rules'][list(out['dsr']['rules'])[0]]['T']}).",
        "",
        "## Limits",
        "",
        "- Survivorship: the coins are 2026's survivors, which favours buy and hold: a coin that died (as LUNA and "
        "FTT did) would have cost holding its whole share, more with monthly top-ups, while a trend rule would "
        "have sold it. Yahoo starts ETH, XRP and ADA 9 November 2017, SOL 10 April 2020; no gaps.",
        "- Spreads fixed at the account's first days; no market impact; USD, not NOK.",
        "",
        "## Exploratory (not pre-registered)",
        "",
        f"Tax on 1 June, all tax at the end, or the book in NOK (refund reading): {passes[0]}, {passes[1]} and "
        f"{passes[2]} rules pass tests 1–2.",
        "",
        "## After the check",
        "",
        "Added the carry reading, which a rule must also clear (refunds had lifted top 2 above its before-tax "
        "return); trades and costs from the "
        f"untaxed run (hold {hold_pre['trades_per_year']:.0f} a year, not "
        f"{hold_pre['with_tax_sales']['trades_per_year']:.0f}); fixed the worst-fall and DSR sentences; added "
        "survivorship's direction; split the final sale from crypto.py's month, with 2020's steps; \"fixed before "
        "running\" (unverifiable) became \"chosen by the analyst\"; cut to under 900 words (pipes not counted).",
    ]
    return "\n".join(L) + "\n"
