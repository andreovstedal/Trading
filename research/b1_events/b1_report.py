"""results.md for B1, written from results.json's dictionary."""

from __future__ import annotations

LABEL = {
    "buyback_start": "New buyback programme, Oslo (1007, 2017-)",
    "insider_cluster": "Insider cluster, Stockholm (FI, 2016-)",
    "insider_buy_no": "Insider purchase notice, Oslo (1102, 2013-)",
    "buyback_start_1102": "Exploratory: buyback start in 1102, 2013-03 to 2017-02",
    "insider_buy_no_pre2013": "Exploratory: insider purchase, Oslo, 2005 to 2013-02 (equal-weighted benchmark)",
}
SHORT = {"buyback_start": "Buyback start (NO)", "insider_cluster": "Insider cluster (SE)",
         "insider_buy_no": "Insider buy (NO)", "buyback_start_1102": "Buyback 1102 (NO, expl.)",
         "insider_buy_no_pre2013": "Insider buy pre-2013 (expl.)"}
PRE = ("buyback_start", "insider_cluster", "insider_buy_no")


def pct(x, d: int = 2) -> str:
    return "–" if x is None else f"{100 * x:+.{d}f} %"


def tval(x) -> str:
    return "–" if x is None else f"{x:.2f}"


def cell(s: dict) -> str:
    if not s or not s.get("n"):
        return "–"
    return f"{pct(s['mean'])} (t {tval(s.get('t_cl'))}, n {s['n']})"


def render(out: dict) -> str:
    res, cov, cfg, inp = out["results"], out["coverage"], out["config"], out["inputs"]
    h5 = str(cfg["horizons"][0]) if str(cfg["horizons"][0]) in res["buyback_start"]["net_excess"] else cfg["horizons"][0]
    L = []
    w = L.append
    w("# B1: event study of the short-term signals\n")
    w("Pre-registered in `research/PREREGISTRATION.md`; run by `b1_events.py` (numbers below come from "
      "`results.json`). Rows marked *exploratory* were not pre-registered.\n")
    w("**Method.** An event is seen by the first 20:45 UTC evening decision at or after its publication "
      "(evenings: days Oslo or Stockholm trades), bought at the next opening on which the stock trades (an order "
      "lapses after 5 market days) and sold at the close of the 5th market day, the buying day being the first. "
      "Dividends are included through Yahoo's adjusted close: gross = adjclose[exit] / (open[entry] × "
      "adjclose[entry]/close[entry]) − 1. Net excess = gross − round trip − index, the index (OSEBX GI, "
      "OMX Stockholm Benchmark GI) taken from the same opening to the same close. Round trip from `paper.costs` on "
      f"a 25,000 NOK slot: Oslo {pct(cfg['round_trip_cost']['NO'])}, Stockholm {pct(cfg['round_trip_cost']['SE'])}. "
      "Notices of one kind for one stock within 4 days (`features.EVENT_WINDOW`) are one event. t is the mean over "
      "its standard error clustered by calendar month of entry: SE² = G/(G−1) · Σ_g(Σ_{i∈g} e_i)² / n².\n")

    w("## Headline: the 5-day trade\n")
    w("| Signal | n | months | mean net excess | SE (clustered) | t | median | share > 0 | mean gross | "
      "mean index | bar met? |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in PRE:
        s = res[k]["net_excess"][h5]
        g, b = res[k]["gross"][h5], res[k]["bench"][h5]
        if not s.get("n"):
            w(f"| {LABEL[k]} | 0 | | | | | | | | | no |")
            continue
        w(f"| {LABEL[k]} | {s['n']} | {s.get('clusters')} | {pct(s['mean'])} | {pct(s.get('se_cl'))} | "
          f"{tval(s.get('t_cl'))} | {pct(s['median'])} | {100 * s['hit_rate']:.0f} % | {pct(g.get('mean'))} | "
          f"{pct(b.get('mean'))} | {'**yes**' if res[k]['passes_bar'] else 'no'} |")
    w("")
    w("Bar (pre-registered): mean net excess > 0 with t ≥ 2.\n")

    w("## Other horizons (net excess, same entry; gap is gross, previous close to the entry opening)\n")
    w("| Signal | gap | gap minus index | 5 days | 20 days | 60 days | 250 days |")
    w("|---|---|---|---|---|---|---|")
    for k in PRE:
        r = res[k]
        w(f"| {SHORT[k]} | {cell(r['gap'])} | {cell(r['gap_excess'])} | "
          + " | ".join(cell(r["net_excess"][h]) for h in r["net_excess"]) + " |")
    w("")

    w("## By year of entry (5-day net excess)\n")
    years = sorted({y for k in PRE for y in res[k]["by_year"]}, key=int)
    w("| Year | " + " | ".join(SHORT[k] for k in PRE) + " |")
    w("|---|" + "---|" * len(PRE))
    for y in years:
        w(f"| {y} | " + " | ".join(cell(res[k]["by_year"].get(y) or res[k]["by_year"].get(int(y)) or {})
                                     for k in PRE) + " |")
    w("")

    w("## Exploratory (not pre-registered; no bar applies)\n")
    w("| View (5-day net excess) | " + " | ".join(SHORT[k] for k in PRE) + " |")
    w("|---|" + "---|" * len(PRE))
    views = [("winsorized_1pct", "Winsorized at 1 % / 99 %"),
             ("bench_close_to_close", "Index from the previous close instead of the opening"),
             ("liquid", "Liquid only (20-day median turnover ≥ 1 MNOK, the sleeve's filter)"),
             ("illiquid", "The rest (less liquid)"),
             ("since_2017_02_15", "Entries from 2017-02-15 (the buyback sample's period)"),
             ("pre_entry_move", "Gross move from the last close before publication to the entry opening")]
    for key, text in views:
        w(f"| {text} | " + " | ".join(cell(res[k]["explore"].get(key) or {}) for k in PRE) + " |")
    ew = res["insider_buy_no"]["explore"].get("equal_weight_benchmark")
    w("")
    w(f"- {LABEL['buyback_start_1102']}: {cell(res['buyback_start_1102']['net_excess'][h5])}.")
    w(f"- {LABEL['insider_buy_no_pre2013']}: {cell(res['insider_buy_no_pre2013']['net_excess'][h5])}. "
      f"For scale, the same equal-weighted benchmark on the 2013- Oslo insider sample gives {cell(ew or {})} "
      f"against {cell(res['insider_buy_no']['net_excess'][h5])} with OSEBX GI.")
    w("")

    hc = out["hand_check"]
    w("## Hand check of the buyback classifier\n")
    if hc["judged"]:
        w(f"{hc['real_starts']} of {hc['judged']} randomly drawn buyback-start events (seed {hc['seed']}) "
          "announce a new programme on reading the title and the start of the notice. The misses:\n")
        for r in hc["sample"]:
            if r["real_start"] is False:
                w(f"- {r['issuer']} {r['published'][:10]}: \"{r['title'].strip()}\" ({r['note']})")
    else:
        w("Not yet judged.")
    w("")

    w("## Coverage and survivorship\n")
    w("| Signal | events | no ticker | not on Yahoo | outside Yahoo's history | lapsed / bad open / too recent | "
      "traded | with 5-day result | series ends before day 250 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for k in list(PRE) + ["buyback_start_1102", "insider_buy_no_pre2013"]:
        c = cov[k]
        w(f"| {SHORT[k]} | {c.get('events', 0)} | {c.get('unmapped', 0)} | {c.get('not_on_yahoo', 0)} | "
          f"{c.get('outside_yahoo_history', 0)} | {c.get('lapsed', 0)} / {c.get('bad_open', 0)} / "
          f"{c.get('not_yet', 0) + c.get('after_data', 0)} | {c.get('ok', 0)} | {c.get('complete_5', 0)} | "
          f"{c.get('ended_before_250', 0)} |")
    w("")
    nc = out["name_check"]
    w(f"Inputs: {inp['newsweb_1007_messages']} own-share and {inp['newsweb_1102_messages']} insider-category "
      f"NewsWeb messages, {inp['fi_rows']} FI rows; {inp['symbols_on_yahoo']} of {inp['symbols']} tickers found "
      f"on Yahoo. Swedish ISINs mapped: {inp['se_mapping']} of {inp['se_isins_wanted']}. Oslo tickers are "
      f"NewsWeb's issuer signs; {nc['no_common_word']} of {nc['checked']} Yahoo names share no word with "
      "NewsWeb's issuer name (listed in results.json).\n")
    return "\n".join(L) + "\n"
