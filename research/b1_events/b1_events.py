"""B1: event study of the short-term signals, as pre-registered in research/PREREGISTRATION.md.

    .venv/bin/python research/b1_events/b1_events.py [--cache DIR] [--offline]

Downloads (and caches) NewsWeb's own-shares and insider categories, Finansinspektionen's insider register,
Nordnet's stock lists and Yahoo's daily bars; builds the events with the project's rules; trades each one as
the play-money account would (decided at 20:45 UTC, bought at the next opening, sold at the close of the 5th
trading day); and writes results.json and results.md next to this file. A second run reads only the cache.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import b1_build  # noqa: E402
import b1_data  # noqa: E402
import b1_report  # noqa: E402
from b1_fetch import Cache, newsweb_body  # noqa: E402
from b1_hand_check import VERDICTS  # noqa: E402
from b1_stats import summary, winsorize  # noqa: E402

from nordic_signals.advisor.allocation import SHORT_HORIZON_DAYS  # noqa: E402
from nordic_signals.advisor.paper import costs  # noqa: E402
from nordic_signals.advisor.scoring import PARAMS  # noqa: E402

DEFAULT_CACHE = Path("/tmp/claude-0/-home-user-Trading/0a31d734-cb89-583d-8276-7cd774b8c998/scratchpad/data/b1_events")
HERE = Path(__file__).resolve().parent
HORIZONS = (SHORT_HORIZON_DAYS, 20, 60, 250)
TRADE_NOK = 25_000.0  # one short-term slot of the play-money account
MIN_POSITION_NOK = 20_000.0
LIQUID_ADV_NOK = PARAMS["adv_multiple"] * MIN_POSITION_NOK  # the short-term sleeve's liquidity filter
ORDER_DAYS = 5  # an order lapses if the stock has not traded within this many market days
HAND_CHECK_SEED, HAND_CHECK_N = 20261008, 20
PREREGISTERED = ("buyback_start", "insider_cluster", "insider_buy_no")
EXPLORATORY = ("buyback_start_1102", "insider_buy_no_pre2013")


def round_trip(currency: str) -> float:
    """``paper.costs`` for a buy and a sale of one 25,000 NOK slot, as a fraction of the trade."""
    return 2 * sum(costs(TRADE_NOK, currency)) / TRADE_NOK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="download cache directory")
    ap.add_argument("--offline", action="store_true", help="fail instead of downloading a file missing from the cache")
    ap.add_argument("--out", type=Path, default=HERE, help="where results.json and results.md go")
    args = ap.parse_args(argv)
    cache = Cache(args.cache, offline=args.offline)
    warnings: list[str] = []
    log = _logger()

    # 1. Raw inputs.
    lists = b1_data.newsweb(cache, warnings)
    log(f"NewsWeb: 1007 {len(lists[1007])} messages, 1102 {len(lists[1102])}")
    fi_rows = b1_data.fi(cache, warnings)
    log(f"FI: {len(fi_rows)} rows")
    nordnet = b1_data.nordnet(cache)
    index = {c: b1_data.load_bars(cache, s) for c, s in (("NO", b1_data.OSEBX), ("SE", b1_data.OMXSB))}
    seknok = b1_data.load_bars(cache, b1_data.SEKNOK)
    cal = {c: [d for d, *_ in b.rows] for c, b in index.items()}
    evenings = sorted(set(cal["NO"]) | set(cal["SE"]))

    # 2. Events.
    nw_events, nw_counts = b1_build.newsweb_events(lists, b1_data.END)
    share_isins = {r["isin"] for r in fi_rows if r["instrument_type"] == "Aktie"}
    share_isins |= {r["isin"] for r in nordnet["SE"] if r.get("isin")}
    purchases, fi_counts = b1_build.fi_purchases(fi_rows, share_isins)
    clusters, cluster_counts = b1_build.fi_clusters(purchases, evenings)
    events = nw_events + clusters
    log(f"events: {Counter(e['kind'] for e in events)}")

    # 3. Tickers and prices.
    se_names = {e["key"]: e.get("instrument_name") or "" for e in clusters}
    se_map = b1_data.map_se_isins(cache, se_names, nordnet["SE"])
    no_names = {e["key"]: e["name"] or "" for e in nw_events if e["key"]}
    no_map = b1_data.map_no_signs(cache, no_names, nordnet["NO"])
    log(f"tickers: {len(no_map)} of {len(no_names)} Oslo signs, {len(se_map)} of {len(se_names)} Swedish ISINs")
    for e in events:
        e["symbol"], e["map"] = (no_map if e["country"] == "NO" else se_map).get(e["key"], (None, None))
    symbols = sorted({e["symbol"] for e in events if e["symbol"]})
    bars: dict[str, b1_data.Bars | None] = {}
    for i, s in enumerate(symbols):
        bars[s] = b1_data.load_bars(cache, s)
        if i % 100 == 0:
            log(f"prices {i}/{len(symbols)} (requests so far {cache.requests})")
    log(f"prices: {sum(1 for b in bars.values() if b)} of {len(symbols)} symbols on Yahoo")

    # Before the indices start (2013-03-05) the Oslo calendar is the days on which >= 5 fetched Oslo stocks traded.
    traded = Counter(d for s, b in bars.items() if b and s.endswith(".OL") for d, *r in b.rows if r[5])
    early = sorted(d for d, n in traded.items() if n >= 5 and d < cal["NO"][0])
    cal_no_full = early + cal["NO"]
    evenings_full = sorted(set(early) | set(evenings))

    # 4. Trades.
    by_symbol_events = defaultdict(list)
    for e in events:
        if e["symbol"]:
            by_symbol_events[e["symbol"]].append(e["at"].date())
    ew = EqualWeight(bars, by_symbol_events)
    fx = FX(seknok)
    trades = []
    for e in events:
        country = e["country"]
        market_cal = cal_no_full if country == "NO" else cal["SE"]
        t = trade(e, bars.get(e["symbol"]) if e["symbol"] else None, market_cal, evenings_full,
                  index[country], round_trip("NOK" if country == "NO" else "SEK"), fx, ew)
        trades.append(t)
    log(f"trades: {Counter((t['kind'], t['status']) for t in trades)}")

    # 5. Statistics.
    results = analyse(trades)
    hand = hand_check(cache, [e for e in events if e["kind"] == "buyback_start"])
    names = name_check(events, bars)
    out = {
        "generated_from_cache": str(args.cache),
        "requests_this_run": cache.requests,
        "config": {
            "end": b1_data.END.isoformat(), "decision_utc": "20:45", "horizons": HORIZONS,
            "round_trip_cost": {"NO": round_trip("NOK"), "SE": round_trip("SEK")},
            "trade_nok": TRADE_NOK, "event_window_days": b1_build.EVENT_WINDOW.days,
            "liquid_adv_nok": LIQUID_ADV_NOK, "order_days": ORDER_DAYS,
            "benchmarks": {"NO": b1_data.OSEBX, "SE": b1_data.OMXSB, "NO_before_2013-03-05": "equal-weighted"},
        },
        "inputs": {
            "newsweb_1007_messages": len(lists[1007]), "newsweb_1102_messages": len(lists[1102]),
            "newsweb_counts": nw_counts, "fi_rows": len(fi_rows), "fi_counts": fi_counts,
            "cluster_counts": cluster_counts, "nordnet": {k: len(v) for k, v in nordnet.items()},
            "se_mapping": dict(Counter(m for _, m in se_map.values())), "se_isins_wanted": len(se_names),
            "no_mapping": dict(Counter(m for _, m in no_map.values())), "no_signs_wanted": len(no_names),
            "symbols": len(symbols), "symbols_on_yahoo": sum(1 for b in bars.values() if b),
        },
        "coverage": coverage(trades),
        "results": results,
        "hand_check": hand,
        "name_check": names,
        "warnings": warnings,
        "largest_moves": largest(trades),
    }
    (args.out / "results.json").write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False))
    (args.out / "results.md").write_text(b1_report.render(out))
    log(f"wrote {args.out / 'results.json'} and results.md; {cache.requests} requests this run")
    cache.close()
    return 0


def _logger():
    start = datetime.now()

    def log(msg: str) -> None:
        print(f"[{(datetime.now() - start).total_seconds():6.0f}s] {msg}", flush=True)

    return log


class FX:
    """NOK per SEK on or before a day (Yahoo's SEKNOK=X close)."""

    def __init__(self, bars: b1_data.Bars | None):
        self.days = bars.days if bars else []
        self.close = [r[4] for r in bars.rows] if bars else []

    def nok_per(self, currency: str, day: date) -> float | None:
        if currency == "NOK":
            return 1.0
        i = bisect_right(self.days, day) - 1
        return self.close[i] if i >= 0 else None


class EqualWeight:
    """Equal-weighted return of the fetched Oslo stocks with no event of any kind from 30 days before the entry
    to the exit, bought at the entry day's opening and sold at the exit day's close (dividends included)."""

    def __init__(self, bars: dict, event_days: dict[str, list[date]]):
        self.bars = {s: b for s, b in bars.items() if b and s.endswith(".OL")}
        self.event_days = {s: sorted(d) for s, d in event_days.items()}

    def ret(self, d1: date, dx: date, exclude: str) -> tuple[float | None, int]:
        rets = []
        for s, b in self.bars.items():
            if s == exclude:
                continue
            days = self.event_days.get(s, [])
            i = bisect_left(days, d1 - timedelta(days=30))
            if i < len(days) and days[i] <= dx:
                continue
            j1, jx = b.index.get(d1), b.index.get(dx)
            if j1 is None or jx is None:
                continue
            r1 = b.rows[j1]
            if not _sane_open(r1) or not r1[6]:
                continue
            r = b.rows[jx][5] / (r1[1] * r1[5] / r1[4]) - 1
            if -0.9 < r < 10:
                rets.append(r)
        return (statistics.fmean(rets) if rets else None), len(rets)


def _sane_open(row: tuple) -> bool:
    _, o, h, lo, c, a, _ = row
    if not o or o <= 0 or not c or c <= 0 or not a:
        return False
    if h and lo:
        return lo * 0.98 <= o <= h * 1.02
    return True


def trade(e: dict, b: b1_data.Bars | None, cal: list[date], evenings: list[date], idx: b1_data.Bars,
          cost: float, fx: FX, ew: EqualWeight) -> dict:
    """The account's trade on one event: decided on the evening whose 20:45 UTC decision first sees the event,
    bought at the next opening on which the stock trades (lapsing after ORDER_DAYS market days), and sold at
    the close of the k-th market day, the buying day being the first.

        gross_k  = adjclose[exit] / (open[entry] * adjclose[entry] / close[entry]) - 1     (dividends included)
        bench_k  = index close[exit] / index open[entry] - 1   (equal-weighted before 2013-03-05)
        excess_k = gross_k - round-trip cost - bench_k
        gap      = open[entry] * adj factor[entry] / adjclose[previous bar] - 1
    """
    t = {"kind": e["kind"], "country": e["country"], "key": e["key"], "name": e["name"], "symbol": e.get("symbol"),
         "at": e["at"].isoformat(), "title": e.get("title"), "notices": e.get("notices"), "cost": cost}
    if not e.get("symbol"):
        t["status"] = "unmapped"
        return t
    if b is None:
        t["status"] = "not_on_yahoo"
        return t
    decided = b1_build.decision_date(e["at"], evenings)
    t["decided"] = decided.isoformat() if decided else None
    if decided is None:
        t["status"] = "after_data"
        return t
    if b.days[0] > decided or b.days[-1] <= decided:
        t["status"] = "outside_yahoo_history"
        return t
    i = bisect_right(cal, decided)
    entry = None
    bad_open = False
    for d in cal[i:i + ORDER_DAYS]:
        j = b.index.get(d)
        if j is None or b.rows[j][6] == 0:  # no bar, or no trades that day: the order waits
            continue
        if not _sane_open(b.rows[j]):
            bad_open = True
            continue
        entry = (d, j)
        break
    if entry is None:
        t["status"] = "bad_open" if bad_open else ("not_yet" if len(cal[i:]) < ORDER_DAYS else "lapsed")
        return t
    d1, j1 = entry
    row1 = b.rows[j1]
    p_in = row1[1] * row1[5] / row1[4]  # the opening price on the adjusted-close scale
    k = bisect_left(cal, d1)
    t.update(entry=d1.isoformat(), month=d1.strftime("%Y-%m"), year=d1.year, status="ok")
    # Liquidity as the advisor measures it: median daily turnover in NOK over the previous 20 sessions.
    turn = [r[4] * r[6] for r in b.rows[max(0, j1 - 20):j1] if r[6]]
    rate = fx.nok_per("NOK" if e["country"] == "NO" else "SEK", d1)
    t["adv_nok"] = statistics.median(turn) * rate if turn and rate else None
    if j1 > 0:
        t["gap"] = p_in / b.rows[j1 - 1][5] - 1
        ij = idx.index.get(d1)
        if ij is not None and ij > 0:
            t["gap_excess"] = t["gap"] - (idx.rows[ij][1] / idx.rows[ij - 1][4] - 1)
    # Exploratory: what happened between the last close before publication and the entry opening.
    pub_local = e["at"].astimezone(b1_data.NORDIC_TZ).date()
    jp = bisect_left(b.days, pub_local) - 1
    if 0 <= jp < j1:
        t["pre_entry"] = p_in / b.rows[jp][5] - 1
    for h in HORIZONS:
        if k + h - 1 >= len(cal):
            continue
        dx = cal[k + h - 1]
        jx = bisect_right(b.days, dx) - 1
        if b.days[-1] < dx or b.days[jx] < dx - timedelta(days=10):
            t[f"ended_{h}"] = True  # Yahoo's series stops before the exit (delisted, merged, renamed)
            continue
        gross = b.rows[jx][5] / p_in - 1
        t[f"gross_{h}"] = gross
        t[f"exit_{h}"] = dx.isoformat()
        if d1 >= b1_build.INDEX_START:
            i1, ix = idx.index.get(d1), idx.index.get(dx)
            if i1 is not None and ix is not None:
                t[f"bench_{h}"] = idx.rows[ix][4] / idx.rows[i1][1] - 1
                if i1 > 0:
                    t[f"bench_cc_{h}"] = idx.rows[ix][4] / idx.rows[i1 - 1][4] - 1
        if h == SHORT_HORIZON_DAYS and e["kind"].startswith("insider_buy_no"):
            t[f"ew_{h}"], t["ew_n"] = ew.ret(d1, dx, b.symbol)
        bench = t.get(f"bench_{h}") if d1 >= b1_build.INDEX_START else t.get(f"ew_{h}")
        if bench is not None:
            t[f"net_excess_{h}"] = gross - cost - bench
    return t


def _stat(rows: list[dict], field: str, transform=None) -> dict:
    sel = [r for r in rows if r.get(field) is not None]
    vals = [r[field] for r in sel]
    if transform:
        vals = transform(vals)
    return summary(vals, [r["month"] for r in sel])


def analyse(trades: list[dict]) -> dict:
    ok = [t for t in trades if t["status"] == "ok"]
    out: dict = {}
    for kind in PREREGISTERED + EXPLORATORY:
        rows = [t for t in ok if t["kind"] == kind]
        h5 = f"net_excess_{SHORT_HORIZON_DAYS}"
        res = {
            "net_excess": {h: _stat(rows, f"net_excess_{h}") for h in HORIZONS},
            "gross": {h: _stat(rows, f"gross_{h}") for h in HORIZONS},
            "bench": {h: _stat(rows, f"bench_{h}") for h in HORIZONS},
            "gap": _stat(rows, "gap"),
            "gap_excess": _stat(rows, "gap_excess"),
            "by_year": {y: _stat([r for r in rows if r["year"] == y], h5) for y in sorted({r["year"] for r in rows})},
            # Exploratory views of the 5-day trade.
            "explore": {
                "winsorized_1pct": _stat(rows, h5, winsorize),
                "bench_close_to_close": summary(
                    [r[f"gross_{SHORT_HORIZON_DAYS}"] - r["cost"] - r[f"bench_cc_{SHORT_HORIZON_DAYS}"]
                     for r in rows if r.get(f"bench_cc_{SHORT_HORIZON_DAYS}") is not None],
                    [r["month"] for r in rows if r.get(f"bench_cc_{SHORT_HORIZON_DAYS}") is not None]),
                "liquid": _stat([r for r in rows if (r.get("adv_nok") or 0) >= LIQUID_ADV_NOK], h5),
                "illiquid": _stat([r for r in rows if (r.get("adv_nok") or 0) < LIQUID_ADV_NOK], h5),
                "pre_entry_move": _stat(rows, "pre_entry"),
                "since_2017_02_15": _stat([r for r in rows if r["entry"] >= "2017-02-15"], h5),
            },
        }
        if kind in ("insider_buy_no", "insider_buy_no_pre2013"):
            ew_rows = [r for r in rows if r.get(f"ew_{SHORT_HORIZON_DAYS}") is not None]
            res["explore"]["equal_weight_benchmark"] = summary(
                [r[f"gross_{SHORT_HORIZON_DAYS}"] - r["cost"] - r[f"ew_{SHORT_HORIZON_DAYS}"] for r in ew_rows],
                [r["month"] for r in ew_rows])
        res["passes_bar"] = bool(res["net_excess"][SHORT_HORIZON_DAYS].get("n")
                                 and res["net_excess"][SHORT_HORIZON_DAYS]["mean"] > 0
                                 and (res["net_excess"][SHORT_HORIZON_DAYS].get("t_cl") or 0) >= 2)
        out[kind] = res
    return out


def coverage(trades: list[dict]) -> dict:
    out = {}
    for kind in PREREGISTERED + EXPLORATORY:
        rows = [t for t in trades if t["kind"] == kind]
        c = Counter(t["status"] for t in rows)
        c["events"] = len(rows)
        for h in HORIZONS:
            c[f"complete_{h}"] = sum(1 for t in rows if t.get(f"net_excess_{h}") is not None)
            c[f"ended_before_{h}"] = sum(1 for t in rows if t.get(f"ended_{h}"))
        c["first_entry"] = min((t["entry"] for t in rows if t.get("entry")), default=None)
        c["last_entry"] = max((t["entry"] for t in rows if t.get("entry")), default=None)
        c["missing_symbols"] = sorted({t["symbol"] or t["key"] for t in rows
                                       if t["status"] in ("unmapped", "not_on_yahoo")})[:400]
        out[kind] = dict(c)
    return out


def largest(trades: list[dict], n: int = 12) -> list[dict]:
    rows = [t for t in trades if t.get(f"gross_{SHORT_HORIZON_DAYS}") is not None and t["kind"] in PREREGISTERED]
    rows.sort(key=lambda t: -abs(t[f"gross_{SHORT_HORIZON_DAYS}"]))
    return [{k: t.get(k) for k in ("kind", "symbol", "name", "entry", "title", f"gross_{SHORT_HORIZON_DAYS}")}
            for t in rows[:n]]


def hand_check(cache: Cache, events: list[dict]) -> dict:
    sample = random.Random(HAND_CHECK_SEED).sample(events, min(HAND_CHECK_N, len(events)))
    rows = []
    for e in sorted(sample, key=lambda e: e["at"]):
        mid = e["message_ids"][0]
        body = newsweb_body(cache, mid) or ""
        verdict = VERDICTS.get(mid)
        rows.append({"message_id": mid, "issuer": e["key"], "published": e["at"].isoformat(), "title": e["title"],
                     "body_start": " ".join(body.split())[:400],
                     "real_start": verdict[0] if verdict else None, "note": verdict[1] if verdict else None})
    judged = [r for r in rows if r["real_start"] is not None]
    return {"seed": HAND_CHECK_SEED, "n": len(rows), "judged": len(judged),
            "real_starts": sum(1 for r in judged if r["real_start"]), "sample": rows}


_GENERIC = {"asa", "as", "ab", "publ", "group", "holding", "holdings", "the", "company", "limited", "ltd", "plc",
            "inc", "and", "of", "bank", "ser", "sa", "se", "nv", "corporation", "corp", "international"}


def name_check(events: list[dict], bars: dict) -> dict:
    """Flag Oslo tickers whose Yahoo name shares no word with NewsWeb's issuer name."""
    names = {e["key"]: (e["name"] or "", e["symbol"]) for e in events if e["country"] == "NO" and e["symbol"]}
    flagged = []
    checked = 0
    for sign, (issuer, symbol) in sorted(names.items()):
        b = bars.get(symbol)
        if not b:
            continue
        checked += 1
        yahoo = f"{b.meta.get('longName') or ''} {b.meta.get('shortName') or ''}"
        words = lambda s: {w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split()  # noqa: E731
                           if w not in _GENERIC and len(w) >= 3}
        if not words(issuer) & words(yahoo):
            flagged.append({"sign": sign, "symbol": symbol, "newsweb": issuer, "yahoo": yahoo.strip()})
    return {"checked": checked, "no_common_word": len(flagged), "flagged": flagged}


if __name__ == "__main__":
    raise SystemExit(main())
