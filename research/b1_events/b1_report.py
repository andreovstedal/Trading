"""results.md for B1, written from the results dictionary. Kept under 900 words of prose."""

from __future__ import annotations

PRE = ("buyback_start", "insider_cluster", "insider_buy_no")
NAME = {"buyback_start": "New buyback programme, Oslo", "insider_cluster": "Insider cluster, Stockholm",
        "insider_buy_no": "Insider purchase notice, Oslo",
        "insider_cluster_today": "↳ comparison: FI's status today (hindsight)",
        "insider_buy_no_title": "↳ subset: purchase stated in the title"}
SHORT = {"buyback_start": "Buyback start", "insider_cluster": "SE cluster", "insider_buy_no": "NO insider buy",
         "insider_cluster_today": "SE cluster, today's status", "insider_buy_no_title": "NO title subset",
         "buyback_start_1102": "Buyback start in 1102", "insider_buy_no_pre2013": "NO title buy pre-2013"}
LOSER = {"buyback_start": "the Oslo buyback start", "insider_cluster": "the Stockholm insider cluster",
         "insider_buy_no": "the Oslo insider purchase"}
# The 5-day headline as the checker reviewed it (results.json before the check): mean, t, n.
BEFORE_CHECK = {"buyback_start": (0.0016, 0.45, 220), "insider_cluster": (-0.0087, -5.07, 4470),
                "insider_buy_no": (-0.0036, -1.24, 726)}


def pct(x, d: int = 2) -> str:
    return "–" if x is None else f"{100 * x:+.{d}f} %"


def cell(s: dict, nw: bool = False, n: bool = True) -> str:
    """mean in % (t clustered by month [/ Newey-West t]; n)"""
    if not s or not s.get("n"):
        return "–"
    t = s.get("t_cl")
    ts = "–" if t is None else f"{t:.1f}"
    if nw and s.get("t_nw") is not None:
        ts += f" / {s['t_nw']:.1f}"
    return f"{100 * s['mean']:+.2f} ({ts}; {_n(s)})" if n else f"{100 * s['mean']:+.2f} ({ts})"


def _n(s: dict) -> str:
    return f"{s['n']} ≈ {s['weighted_n']:.0f}" if s.get("weighted_n") else str(s["n"])


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _t(s: dict) -> str:
    return f"{100 * s['mean']:+.2f} % (t {s['t_cl']:.2f}; n {_n(s)})"


def render(out: dict) -> str:
    res, cov, cfg, inp, hc = out["results"], out["coverage"], out["config"], out["inputs"], out["hand_check"]
    h5 = cfg["horizons"][0]
    ex = {k: res[k]["explore"] for k in res}
    ne = {k: res[k]["net_excess"][h5] for k in res}
    oc = inp["oslo_insider_counts"]
    L: list[str] = []
    w = L.append
    passed = [k for k in PRE if res[k]["passes_bar"]]
    losing = [LOSER[k] for k in PRE if ne[k]["mean"] < 0 and (ne[k].get("t_cl") or 0) <= -2]
    w("# B1: event study of the short-term signals\n")
    w("Pre-registered in `research/PREREGISTRATION.md`; made by `b1_events.py`; other parts marked exploratory or "
      "post hoc.\n")
    if passed:
        w(f"**Verdict: {', '.join(NAME[k] for k in passed)} clear the bar; the others do not.**\n")
    else:
        w("**Verdict: no signal clears the bar (mean 5-day net excess > 0 with t ≥ 2).**"
          + (f" {_cap(' and '.join(losing))} lose money after costs (t ≤ −2)." if losing else "") + "\n")

    w("## Method\n")
    w("Seen at the first 20:45 UTC decision after publication (Swedish cluster: the first evening with purchases "
      "by ≥ 2 distinct insiders published in the last 4 days and not yet revised); bought at the next opening; "
      "sold at the 5th market day's close, the buying day first. gross = adjclose[exit] / (open[entry] · "
      "adjclose[entry]/close[entry]) − 1; net excess = gross − round trip "
      f"({pct(cfg['round_trip_cost']['NO'])} Oslo, {pct(cfg['round_trip_cost']['SE'])} Stockholm, `paper.costs`) "
      "− index (OSEBX GI, OMXSBGI), same opening to close. A stock's notices within 4 days are one event. "
      "m = Σw·x/Σw; t = m/SE, SE² = G/(G−1)·Σ_g(Σ_{i∈g} w_i(x_i−m))²/(Σw)², g = entry month; w = 1 except "
      "below.\n")
    w(f"Oslo insider notices are read as the code reads them, title and body: all {oc['title_purchase_notices']} "
      f"whose title states a purchase (census), and a random {oc['sampled']} of the {oc['title_silent_notices']} "
      f"with a silent title (seed {cfg['oslo_sample']['seed']}). An event found only through the sample has "
      f"w = (N/n)/m = {oc['expansion']:.2f}/m, m = its silent-title purchase notices (Hansen–Hurwitz; events "
      "built from the bodies of neighbouring notices). n: rows ≈ estimated events. Read with its body, "
      f"a title-stated purchase is dropped {oc.get('title_purchases_ambiguous_on_body', 0) + oc.get('title_purchases_own_shares_in_body', 0)} "
      f"times: {oc.get('title_purchases_ambiguous_on_body', 0)} turn ambiguous on a sell word (often shares sold to "
      f"employees, or boilerplate such as Yara's \"salg til mer enn 150 land\"), "
      f"{oc.get('title_purchases_own_shares_in_body', 0)} name own or treasury shares.\n")

    w("## Headline: the 5-day trade\n")
    w("| Signal | n | months | mean net excess | SE | t | median | > 0 | gross | index |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for k in ("buyback_start", "insider_cluster", "insider_cluster_today", "insider_buy_no", "insider_buy_no_title"):
        s, g, b = ne[k], res[k]["gross"][h5], res[k]["bench"][h5]
        w(f"| {NAME[k]} | {_n(s)} | {s.get('clusters')} | {pct(s['mean'])} | {pct(s.get('se_cl'))} | "
          f"{s.get('t_cl', 0):.2f} | {pct(s['median'])} | {100 * s['hit_rate']:.0f} % | {pct(g.get('mean'))} | "
          f"{pct(b.get('mean'))} |")
    share = cov["insider_buy_no_title"]["complete_5"] / (ne["insider_buy_no"].get("weighted_n") or 1)
    w(f"\nThe title subset, the Oslo row before the check, is {100 * share:.0f} % of the estimated events.\n")
    w("Cells: mean % (t by month / Newey–West t; n). Gap: previous close to entry opening.\n")
    w("| Signal | gap | gap − index | 5 days | 20 days | 60 days | 250 days |")
    w("|---|---|---|---|---|---|---|")
    for k in PRE:
        r = res[k]
        w(f"| {SHORT[k]} | {cell(r['gap'])} | {cell(r['gap_excess'])} | "
          + " | ".join(cell(r["net_excess"][h], nw=h != h5) for h in r["net_excess"]) + " |")
    lags = list(cfg["nw_lags_months"].values())
    w(f"\nBeyond 5 days holdings overlap across months, inflating the month-clustered t; the Newey–West t treats "
      f"month sums as a series ({lags[1]}, {lags[2]}, {lags[3]} lags).\n")

    w("## By year of entry (5-day net excess, % (t))\n")
    years = sorted({int(y) for k in PRE for y in res[k]["by_year"]})
    w("| Year | " + " | ".join(SHORT[k] for k in PRE) + " |")
    w("|---|" + "---|" * len(PRE))
    for y in years:
        w(f"| {y} | " + " | ".join(cell(res[k]["by_year"].get(y) or res[k]["by_year"].get(str(y)) or {}, n=False)
                                     for k in PRE) + " |")

    w("\n## What happens (buyback / SE cluster / NO insider)\n")
    nw5 = " / ".join(f"{ne[k].get('t_nw') or 0:.1f}" for k in PRE)
    gx = " / ".join(pct(res[k]["gross"][h5]["mean"] - res[k]["bench"][h5]["mean"]) for k in PRE)
    w(f"- **The move comes before the account can buy** (exploratory; gross, last close before publication to "
      f"entry opening): {' / '.join(cell(ex[k]['pre_entry_move']) for k in PRE)}. After entry, gross minus index "
      f"is {gx}.")
    w(f"- **Robust** (exploratory): winsorized 1/99 % {' / '.join(cell(ex[k]['winsorized_1pct'], n=False) for k in PRE)};"
      f" Newey–West t (1 lag) {nw5};"
      f" liquid stocks (≥ 1 MNOK a day) {' / '.join(cell(ex[k]['liquid']) for k in PRE)}; without events "
      f"while the stock is held {' / '.join(cell(ex[k]['skip_while_held'], n=False) for k in PRE)}.")
    w(f"- **Oslo strata:** title-stated events {cell(ex['insider_buy_no']['census_events'])}, sample-only "
      f"{cell(ex['insider_buy_no']['sample_events'])}.")
    w(f"- **Post hoc splits:** buybacks for employee/incentive schemes {cell(ex['buyback_start']['incentive_purpose'])}"
      f", others {cell(ex['buyback_start']['other_purpose'])}; Oslo insider notices naming a scheme, allotment, "
      f"share issue, offer or exercise {cell(ex['insider_buy_no']['not_in_market'])}, others "
      f"{cell(ex['insider_buy_no']['in_market'])}.")
    w(f"- **Exploratory sets:** buyback starts in 1102 titles, 2013-03 to 2017-02, {cell(ne['buyback_start_1102'])}; "
      f"Oslo title purchases 2005 to 2013-02 against equal-weighted event-free stocks "
      f"{cell(ne['insider_buy_no_pre2013'])}.\n")

    w("## Hand check: 20 random buyback starts\n")
    misses = [r for r in hc["sample"] if r["real_start"] is False]
    w(f"{hc['real_starts']} of {hc['judged']} announce a new programme (the miss{'es' if len(misses) > 1 else ''}: "
      + "; ".join(r["issuer"] for r in misses) + ", a termination). "
      f"{hc['incentive_only_by_hand']} of the {hc['real_starts']} only supply shares to employee or board schemes, "
      f"often NOK 1–20m (the post hoc keywords agree on {hc['incentive_rule_agrees']}).\n")

    w("## Coverage and survivorship\n")
    w("| Signal | events | no Yahoo series (delisted, merged) | listed abroad / foreign ISIN | Yahoo starts after "
      "event | lapsed | with 5-day result |")
    w("|---|---|---|---|---|---|---|")
    for k in list(PRE) + ["insider_cluster_today", "insider_buy_no_title", "buyback_start_1102",
                          "insider_buy_no_pre2013"]:
        c = cov[k]
        sfx = "_weighted" if "events_weighted" in c else ""
        ev = c.get(f"events{sfx}", 0) or 1
        cols = [f"{c.get(f'missing_{r}{sfx}', 0):.0f} ({100 * c.get(f'missing_{r}{sfx}', 0) / ev:.0f} %)"
                for r in ("not_found", "abroad", "starts_late")]
        lapsed = c.get("lapsed_weighted") if sfx else c.get("lapsed", 0) + c.get("bad_open", 0)
        done = c.get("complete_5_weighted") if sfx else c.get("complete_5", 0)
        w(f"| {SHORT[k]} | {('≈ ' if sfx else '') + format(ev, '.0f')} | " + " | ".join(cols)
          + f" | {lapsed:.0f} | {done:.0f} |")
    fc, lk = inp["fi_counts"], inp["fi_untyped_share_like"]
    late = ", ".join(x for x, _ in cov["insider_cluster"]["starts_late_examples"][:3])
    w("")
    w(f"- Missing events are missing, not zero. Oslo issuers listed abroad: "
      f"{', '.join(sorted(set(inp['oslo_listed_abroad'].values())))}. Yahoo series starting after a venue or "
      f"ticker change: {late}.")
    w(f"- FI typed no instrument before 2018-09-18: {fc['purchases_untyped_share_isin']} untyped purchases count "
      f"by an ISIN typed 'Aktie' elsewhere or on Nordnet's list, {fc['purchases_untyped_share_like']} by "
      f"{lk['share_like']} ISINs whose rows mostly name shares; {fc['purchases_untyped_dropped']} dropped (rights, "
      "options, bonds, malformed ISINs).")
    w(f"- {inp['cluster_counts']['clusters_only_by_name_spelling']} clusters rest on one name spelt two ways (kept, "
      f"as the code counts them); {cov['insider_buy_no'].get('no_dividend_adjustment_5', 0)} Oslo trades lack dividends (broken adjusted "
      "close). Not tested: Swedish buyback starts (MFN), the account's slot limits.\n")

    sl = inp["cluster_events_from_share_like_isins"]
    b = {k: f"{100 * m:+.2f} % (t {t:.2f}; n {n})" for k, (m, t, n) in BEFORE_CHECK.items()}
    nw250 = res["insider_cluster"]["net_excess"][250]
    w("## What changed after the check\n")
    w("All seven problems were real and are fixed. Before → after, 5-day net excess:\n")
    w(f"1. **Oslo insider row:** it held only title-stated purchases. Now title + body, census plus weighted "
      f"sample: {b['insider_buy_no']} → {_t(ne['insider_buy_no'])}. The subset is kept, labelled; the scheme split "
      "is post hoc.")
    w(f"2. **Point in time:** FI's {fc.get('status_Reviderad', 0)} revised and {fc.get('status_Makulerad', 0)} "
      f"cancelled share purchases count from publication, revised ones until their correction "
      f"({fc.get('revised_with_correction_found', 0)} found), the rest for the window (FI gives no time): "
      f"{b['insider_cluster']} → {_t(ne['insider_cluster'])} with all fixes; on today's status "
      f"{pct(ne['insider_cluster_today']['mean'])}.")
    w(f"3. **Untyped ISINs:** share-like ones now enter: {sum(sl.values())} cluster events, "
      f"{sl.get('ok', 0)} traded, the rest counted missing.")
    w("4. **Missing data:** split into delisted, listed abroad and late Yahoo series.")
    w(f"5. **Calendar:** the days missing from Yahoo's index ({len(inp['calendar_days_added']['NO'])} Oslo, "
      f"{len(inp['calendar_days_added']['SE'])} Stockholm) are added from 8 large stocks, the index unchanged "
      f"over them. Buyback starts, changed by this alone: {b['buyback_start']} → {_t(ne['buyback_start'])}.")
    w(f"6. **Overlap:** Newey–West t added beyond 5 days (Swedish cluster, 250 days: t {nw250.get('t_cl', 0):.1f} → "
      f"{nw250.get('t_nw', 0):.1f}).")
    w(f"7. **Double counting:** events merged by Yahoo symbol "
      f"({inp['events_folded_by_symbol'].get('insider_cluster', 0)} Swedish clusters folded); events "
      "the account would skip, as it still holds the stock, are dropped under Robust.")
    return "\n".join(L) + "\n"
