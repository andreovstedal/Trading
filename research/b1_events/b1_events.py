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
import math
import random
import re
import statistics
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import b1_build  # noqa: E402
import b1_data  # noqa: E402
import b1_oslo  # noqa: E402
import b1_report  # noqa: E402
from b1_fetch import Cache, newsweb_body  # noqa: E402
from b1_hand_check import INCENTIVE_ONLY, VERDICTS  # noqa: E402
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
MARKET_CLOSE = {"NO": time(16, 30), "SE": time(17, 30)}  # local; a notice after it follows that day's close
ORDER_DAYS = 5  # an order lapses if the stock has not traded within this many market days
HAND_CHECK_SEED, HAND_CHECK_N = 20261008, 20
# Post hoc (after reading the hand-check sample): a programme whose notice names employee, board or incentive
# schemes as its purpose.
INCENTIVE = re.compile(r"employee|ansatt|incentive|insentiv|bonus|remunerat|godtgj|share[- ]based|aksjebasert|"
                       r"share savings|aksjespar|spareprogram|share purchase program|option program|opsjon|"
                       r"\bLTI|long[- ]term incentive|aksjeprogram", re.IGNORECASE)
# Post hoc (after the check, which split the title-stated Oslo purchases this way): an insider notice whose text
# names an employee or incentive scheme, an allotment, a share issue or subscription, an offer or an exercise,
# rather than a purchase in the market.
NOT_IN_MARKET = re.compile(
    r"employee[s']*\s+(?:share|stock|purchase|saving|incentive|option|program|offer|trust)|(?:by|to|for) (?:the )?"
    r"employees|employees (?:buy|purchase|bought)|ansatt\w*\s*(?:aksje|kjøp|program|tilbud|spar)|til (?:de )?ansatte|"
    r"ansattes|share savings|aksjespar|spareprogram|share purchase (?:plan|program)|aksjekjøpsprogram|ESPP|\bLTIP?\b|"
    r"long[- ]term incentive|incentive (?:program|plan|scheme)|insentiv|bonus|share[- ]based|allot|tildel|subscri|"
    r"tegning|tegnet|private placement|emisjon|\boffer\b|tilbudet|exercis|innløs|utøv|\bRSU|\bPSU|matching share",
    re.IGNORECASE)
PREREGISTERED = ("buyback_start", "insider_cluster", "insider_buy_no")
EXPLORATORY = ("insider_cluster_today", "insider_buy_no_title", "buyback_start_1102", "insider_buy_no_pre2013")


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
    index_bars = {c: b1_data.load_bars(cache, s) for c, s in (("NO", b1_data.OSEBX), ("SE", b1_data.OMXSB))}
    index = {c: b1_data.IndexSeries(b) for c, b in index_bars.items()}
    seknok = b1_data.load_bars(cache, b1_data.SEKNOK)
    cal = {c: b1_data.trading_calendar(index_bars[c], [b1_data.load_bars(cache, s) for s in b1_data.LARGE[c]])
           for c in ("NO", "SE")}
    added_days = {c: [d.isoformat() for d in cal[c] if d >= index_bars[c].days[0] and not index[c].has(d)]
                  for c in cal}
    evenings = sorted(set(cal["NO"]) | set(cal["SE"]))

    # 2. Events.
    nw_events, nw_counts = b1_build.newsweb_events(lists, b1_data.END)
    no_events, no_counts = b1_oslo.events(cache, lists[1102], b1_data.END)
    log(f"Oslo insider purchases: {no_counts}")
    share_isins = {b1_build.norm_isin(r["isin"]) for r in fi_rows if r["instrument_type"] == "Aktie"}
    share_isins |= {b1_build.norm_isin(r["isin"]) for r in nordnet["SE"] if r.get("isin")}
    share_like, share_like_counts = b1_build.untyped_share_like(fi_rows, share_isins)
    until, revision_counts = b1_build.revisions(fi_rows)
    purchases, fi_counts = b1_build.fi_purchases(fi_rows, share_isins, share_like, until)
    clusters, cluster_counts = b1_build.fi_clusters(purchases, evenings)
    purchases_today, fi_counts_today = b1_build.fi_purchases(fi_rows, share_isins, share_like, None)
    clusters_today, cluster_counts_today = b1_build.fi_clusters(purchases_today, evenings, "insider_cluster_today")
    events = nw_events + no_events + clusters + clusters_today
    log(f"events: {Counter(e['kind'] for e in events)}")
    for e in events:
        if e["kind"] == "buyback_start":
            body = newsweb_body(cache, e["message_ids"][0])
            e["incentive"] = bool(INCENTIVE.search(f"{e['title']} {body}")) if body else None
        elif e["kind"] in ("insider_buy_no", "insider_buy_no_title"):  # bodies already read by b1_oslo
            body = newsweb_body(cache, e["message_ids"][0])
            e["not_in_market"] = bool(NOT_IN_MARKET.search(f"{e['title']} {body or ''}"))

    # 3. Tickers and prices.
    se_names = {e["key"]: e.get("instrument_name") or "" for e in clusters + clusters_today}
    se_map = b1_data.map_se_isins(cache, se_names, nordnet["SE"])
    no_names = {e["key"]: e["name"] or "" for e in nw_events + no_events if e["key"]}
    no_map = b1_data.map_no_signs(cache, no_names, nordnet["NO"])
    log(f"tickers: {len(no_map)} of {len(no_names)} Oslo signs, {len(se_map)} of {len(se_names)} Swedish ISINs")
    for e in events:
        e["symbol"], e["map"] = (no_map if e["country"] == "NO" else se_map).get(e["key"], (None, None))
    events, folded = b1_build.merge_by_symbol(events)
    log(f"events folded into another of the same stock: {folded}")
    foreign = {sign: b1_data.foreign_listing(cache, name) for sign, name in sorted(no_names.items())
               if sign not in no_map}
    symbols = sorted({e["symbol"] for e in events if e["symbol"]})
    bars: dict[str, b1_data.Bars | None] = {}
    for i, s in enumerate(symbols):
        bars[s] = b1_data.load_bars(cache, s)
        if i % 100 == 0:
            log(f"prices {i}/{len(symbols)} (requests so far {cache.requests})")
    log(f"prices: {sum(1 for b in bars.values() if b)} of {len(symbols)} symbols on Yahoo")

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
        t = trade(e, bars.get(e["symbol"]) if e["symbol"] else None, cal[country], evenings,
                  index[country], round_trip("NOK" if country == "NO" else "SEK"), fx, ew)
        if t["status"] == "unmapped":
            t["foreign"] = (foreign.get(e["key"]) if country == "NO"
                            else (None if e["key"].startswith("SE") else "foreign ISIN"))
        trades.append(t)
    flag_while_held(trades)
    from_share_like = Counter(t["status"] for t in trades if t["kind"] == "insider_cluster"
                              and set(t["isins"].split(";")) & share_like)
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
            "calendar": "index days plus weekdays on which >= 4 of 8 large stocks traded",
            "nw_lags_months": {h: nw_lags(h) for h in HORIZONS},
            "oslo_sample": {"seed": b1_oslo.BODY_SAMPLE_SEED, "n": b1_oslo.BODY_SAMPLE_N},
        },
        "inputs": {
            "newsweb_1007_messages": len(lists[1007]), "newsweb_1102_messages": len(lists[1102]),
            "newsweb_counts": nw_counts, "oslo_insider_counts": no_counts, "fi_rows": len(fi_rows),
            "fi_counts": fi_counts, "fi_counts_today": fi_counts_today, "fi_revisions": revision_counts,
            "fi_untyped_share_like": share_like_counts, "cluster_events_from_share_like_isins": dict(from_share_like),
            "cluster_counts": cluster_counts, "cluster_counts_today": cluster_counts_today,
            "events_folded_by_symbol": folded, "calendar_days_added": added_days,
            "nordnet": {k: len(v) for k, v in nordnet.items()},
            "oslo_listed_abroad": {k: v for k, v in foreign.items() if v},
            "se_mapping": dict(Counter(m for _, m in se_map.values())), "se_isins_wanted": len(se_names),
            "no_mapping": dict(Counter(m for _, m in no_map.values())), "no_signs_wanted": len(no_names),
            "symbols": len(symbols), "symbols_on_yahoo": sum(1 for b in bars.values() if b),
            "index_open_is_previous_close": {c: _stale_open_share(b) for c, b in index_bars.items()},
        },
        "coverage": coverage(trades),
        "results": results,
        "hand_check": hand,
        "name_check": names,
        "warnings": warnings,
        "largest_moves": largest(trades),
    }
    _write_trades(args.cache / "out" / "trades.csv", trades)
    (args.out / "results.json").write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False))
    (args.out / "results.md").write_text(b1_report.render(out))
    log(f"wrote {args.out / 'results.json'} and results.md; {cache.requests} requests this run")
    cache.close()
    return 0


def _stale_open_share(b: b1_data.Bars) -> float:
    """Share of days on which Yahoo's index opening equals the previous close (a stale first calculation)."""
    rows = b.rows
    return sum(1 for a, z in zip(rows, rows[1:]) if abs(z[OPEN] / a[CLOSE] - 1) < 1e-9) / max(len(rows) - 1, 1)


def _write_trades(path: Path, trades: list[dict]) -> None:
    """Every event and its trade, for audit (kept with the cache, not in the repository)."""
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for t in trades for k in t})
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(trades)


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
            if not _sane_open(b.rows[j1]) or not b.rows[j1][6] or _split_error(b, j1, jx):
                continue
            rets.append(total_return(b, j1, OPEN, jx, CLOSE)[0])
        return (statistics.fmean(rets) if rets else None), len(rets)


OPEN, CLOSE = 1, 4  # positions in a bar: (day, open, high, low, close, adjclose, volume)


def total_return(b: b1_data.Bars, j_from: int, at_from: int, j_to: int, at_to: int) -> tuple[float, bool]:
    """From one bar's open or close to a later bar's open or close, dividends included through Yahoo's dividend
    adjustment factor f = adjclose / close:  r = price_to * f_to / (price_from * f_from) - 1.  Where Yahoo's
    adjusted close is broken (f not in (0, 1], or f falling, or rising by more than half), the split-adjusted
    price alone is used, without dividends; the second value says whether the dividend adjustment was used."""
    a, z = b.rows[j_from], b.rows[j_to]
    raw = z[at_to] / a[at_from] - 1
    f_a = a[5] / a[4] if a[5] and a[4] else None
    f_z = z[5] / z[4] if z[5] and z[4] else None
    if f_a and f_z and 0 < f_a <= f_z * 1.0001 and f_z <= 1.0001 and f_z / f_a <= 1.5:
        return (1 + raw) * f_z / f_a - 1, True
    return raw, False


def _sane_open(row: tuple) -> bool:
    _, o, h, lo, c, a, _ = row
    if not o or o <= 0 or not c or c <= 0:
        return False
    if h and lo:
        return lo * 0.98 <= o <= h * 1.02
    return True


def trade(e: dict, b: b1_data.Bars | None, cal: list[date], evenings: list[date], idx: b1_data.IndexSeries,
          cost: float, fx: FX, ew: EqualWeight) -> dict:
    """The account's trade on one event: decided on the evening whose 20:45 UTC decision first sees the event,
    bought at the next opening on which the stock trades (lapsing after ORDER_DAYS market days), and sold at
    the close of the k-th market day, the buying day being the first.

        gross_k  = total_return(entry open -> exit close)   (dividends included where Yahoo's adjustment is sane)
        bench_k  = index close[exit] / index open[entry] - 1   (equal-weighted before 2013-03-05; a day missing
                   from Yahoo's index series counts as unchanged from the previous close)
        excess_k = gross_k - round-trip cost - bench_k
        gap      = total_return(previous bar's close -> entry open)
    """
    t = {"kind": e["kind"], "country": e["country"], "key": e["key"], "name": e["name"], "symbol": e.get("symbol"),
         "at": e["at"].isoformat(), "title": e.get("title"), "notices": e.get("notices"), "cost": cost,
         "incentive": e.get("incentive"), "not_in_market": e.get("not_in_market"),
         "message_id": (e.get("message_ids") or [None])[0], "weight": e.get("weight", 1.0),
         "stratum": e.get("stratum"), "isins": ";".join(e.get("isins") or [])}
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
    if b.days[0] > decided:
        t["status"] = "yahoo_starts_late"  # a listed stock whose Yahoo series begins after the event
        t["yahoo_first_day"] = b.days[0].isoformat()
        return t
    if b.days[-1] <= decided:
        t["status"] = "not_yet" if decided >= cal[-1] else "yahoo_ended"
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
    k = bisect_left(cal, d1)
    t.update(entry=d1.isoformat(), month=d1.strftime("%Y-%m"), year=d1.year, status="ok")
    # Liquidity as the advisor measures it: median daily turnover in NOK over the previous 20 sessions.
    turn = [r[4] * r[6] for r in b.rows[max(0, j1 - 20):j1] if r[6]]
    rate = fx.nok_per("NOK" if e["country"] == "NO" else "SEK", d1)
    t["adv_nok"] = statistics.median(turn) * rate if turn and rate else None
    index_open, index_prev = idx.open(d1), idx.prev_close(d1)
    if j1 > 0:
        t["gap"] = total_return(b, j1 - 1, CLOSE, j1, OPEN)[0]
        if d1 >= b1_build.INDEX_START and index_open and index_prev:
            t["gap_excess"] = t["gap"] - (index_open / index_prev - 1)
    # Exploratory: what happened between the last close before publication and the entry opening.
    pub = e.get("published", e["at"]).astimezone(b1_data.NORDIC_TZ)  # FI clusters: when the cluster formed
    after_close = pub.time() >= (MARKET_CLOSE[e["country"]])
    jp = (bisect_right if after_close else bisect_left)(b.days, pub.date()) - 1
    if 0 <= jp < j1:
        t["pre_entry"] = total_return(b, jp, CLOSE, j1, OPEN)[0]
    for h in HORIZONS:
        if k + h - 1 >= len(cal):
            continue
        dx = cal[k + h - 1]
        jx = bisect_right(b.days, dx) - 1
        if b.days[-1] < dx or b.days[jx] < dx - timedelta(days=10):
            t[f"ended_{h}"] = True  # Yahoo's series stops before the exit (delisted, merged, renamed)
            continue
        if _split_error(b, j1, jx):
            t[f"suspect_{h}"] = True  # a one-day jump Yahoo's split adjustment most likely got wrong
            continue
        gross, with_dividends = total_return(b, j1, OPEN, jx, CLOSE)
        t[f"gross_{h}"] = gross
        if not with_dividends:
            t[f"no_dividend_adjustment_{h}"] = True
        t[f"exit_{h}"] = dx.isoformat()
        if d1 >= b1_build.INDEX_START:
            index_close = idx.close(dx)
            if index_open and index_close:
                t[f"bench_{h}"] = index_close / index_open - 1
            if index_prev and index_close:
                t[f"bench_cc_{h}"] = index_close / index_prev - 1
        if h == SHORT_HORIZON_DAYS and e["kind"].startswith("insider_buy_no"):
            t[f"ew_{h}"], t["ew_n"] = ew.ret(d1, dx, b.symbol)
        bench = t.get(f"bench_{h}") if d1 >= b1_build.INDEX_START else t.get(f"ew_{h}")
        if bench is not None:
            t[f"net_excess_{h}"] = gross - cost - bench
    return t


def flag_while_held(trades: list[dict]) -> None:
    """Mark events the account would skip because it still holds the stock from an earlier event of the same
    signal: decided on or before the evening of that holding's 5th day (``paper._plan``'s ``taken``)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for t in trades:
        if t["status"] == "ok":
            groups[(t["kind"], t["symbol"])].append(t)
    for items in groups.values():
        items.sort(key=lambda t: (t["entry"], t["at"]))
        held_until = None
        for t in items:
            if held_until is not None and t["decided"] <= held_until:
                t["while_held"] = True
                continue
            held_until = t.get(f"exit_{SHORT_HORIZON_DAYS}") or held_until


def nw_lags(h: int) -> int:
    """Newey-West lags in months: enough for holdings that start in different months to stop overlapping."""
    return 1 if h <= SHORT_HORIZON_DAYS else 1 + math.ceil(h / 21)


def _split_error(b: b1_data.Bars, j1: int, jx: int) -> bool:
    """Whether Yahoo's split-adjusted prices over the holding period look broken: a price at or below zero, a
    one-day rise beyond x4 (from the entry opening on the first day), or a one-day fall below x0.2 within 10 days
    of one of Yahoo's split dates (Yahoo sometimes applies a reverse split days away from the price jump). A large
    fall without a split nearby is kept: stocks do crash."""
    prev = b.rows[j1][OPEN]
    for r in b.rows[j1:jx + 1]:
        if not prev or prev <= 0 or not r[CLOSE] or r[CLOSE] <= 0 or r[CLOSE] / prev > 4:
            return True
        if r[CLOSE] / prev < 0.2 and any(abs((d - r[0]).days) <= 10 for d in b.split_days):
            return True
        prev = r[CLOSE]
    return False


def _stat(rows: list[dict], field: str, transform=None, lags: int | None = None) -> dict:
    sel = [r for r in rows if r.get(field) is not None]
    vals = [r[field] for r in sel]
    if transform:
        vals = transform(vals)
    return summary(vals, [r["month"] for r in sel], [r.get("weight", 1.0) for r in sel], lags)


def analyse(trades: list[dict]) -> dict:
    ok = [t for t in trades if t["status"] == "ok"]
    out: dict = {}
    h5 = f"net_excess_{SHORT_HORIZON_DAYS}"
    for kind in PREREGISTERED + EXPLORATORY:
        rows = [t for t in ok if t["kind"] == kind]
        for r in rows:
            if r.get(f"bench_cc_{SHORT_HORIZON_DAYS}") is not None:
                r["net_excess_cc"] = r[f"gross_{SHORT_HORIZON_DAYS}"] - r["cost"] - r[f"bench_cc_{SHORT_HORIZON_DAYS}"]
            if r.get(f"ew_{SHORT_HORIZON_DAYS}") is not None:
                r["net_excess_ew"] = r[f"gross_{SHORT_HORIZON_DAYS}"] - r["cost"] - r[f"ew_{SHORT_HORIZON_DAYS}"]
        res = {
            "net_excess": {h: _stat(rows, f"net_excess_{h}", lags=nw_lags(h)) for h in HORIZONS},
            "gross": {h: _stat(rows, f"gross_{h}") for h in HORIZONS},
            "bench": {h: _stat(rows, f"bench_{h}") for h in HORIZONS},
            "gap": _stat(rows, "gap"),
            "gap_excess": _stat(rows, "gap_excess"),
            "by_year": {y: _stat([r for r in rows if r["year"] == y], h5) for y in sorted({r["year"] for r in rows})},
            # Exploratory views of the 5-day trade.
            "explore": {
                "winsorized_1pct": _stat(rows, h5, winsorize),
                "bench_close_to_close": _stat(rows, "net_excess_cc"),
                "liquid": _stat([r for r in rows if (r.get("adv_nok") or 0) >= LIQUID_ADV_NOK], h5),
                "illiquid": _stat([r for r in rows if (r.get("adv_nok") or 0) < LIQUID_ADV_NOK], h5),
                "pre_entry_move": _stat(rows, "pre_entry"),
                "since_2017_02_15": _stat([r for r in rows if r["entry"] >= "2017-02-15"], h5),
                "skip_while_held": _stat([r for r in rows if not r.get("while_held")], h5),
            },
        }
        if kind == "buyback_start":
            res["explore"]["incentive_purpose"] = _stat([r for r in rows if r.get("incentive") is True], h5)
            res["explore"]["other_purpose"] = _stat([r for r in rows if r.get("incentive") is False], h5)
        if kind in ("insider_buy_no", "insider_buy_no_title"):
            res["explore"]["not_in_market"] = _stat([r for r in rows if r.get("not_in_market") is True], h5)
            res["explore"]["in_market"] = _stat([r for r in rows if r.get("not_in_market") is False], h5)
        if kind == "insider_buy_no":
            res["explore"]["census_events"] = _stat([r for r in rows if r.get("stratum") == "census"], h5)
            res["explore"]["sample_events"] = _stat([r for r in rows if r.get("stratum") == "sample"], h5)
        if kind in ("insider_buy_no", "insider_buy_no_title", "insider_buy_no_pre2013"):
            res["explore"]["equal_weight_benchmark"] = _stat(rows, "net_excess_ew")
        res["passes_bar"] = bool(res["net_excess"][SHORT_HORIZON_DAYS].get("n")
                                 and res["net_excess"][SHORT_HORIZON_DAYS]["mean"] > 0
                                 and (res["net_excess"][SHORT_HORIZON_DAYS].get("t_cl") or 0) >= 2)
        out[kind] = res
    return out


MISSING = {  # why an event has no trade: the coverage table's columns
    "not_found": "no Yahoo series (delisted, merged, renamed)",
    "abroad": "listed abroad / foreign ISIN, no Yahoo series here",
    "starts_late": "Yahoo series starts after the event",
}


def missing_reason(t: dict) -> str | None:
    if t["status"] == "unmapped":
        return "abroad" if t.get("foreign") else "not_found"
    if t["status"] in ("not_on_yahoo", "yahoo_ended"):
        return "not_found"
    if t["status"] == "yahoo_starts_late":
        return "starts_late"
    return None


def coverage(trades: list[dict]) -> dict:
    out = {}
    for kind in PREREGISTERED + EXPLORATORY:
        rows = [t for t in trades if t["kind"] == kind]
        c = Counter(t["status"] for t in rows)
        c["events"] = len(rows)
        weighted = any(t["weight"] != 1.0 for t in rows)
        for reason in MISSING:
            c[f"missing_{reason}"] = sum(1 for t in rows if missing_reason(t) == reason)
        if weighted:
            c["events_weighted"] = sum(t["weight"] for t in rows)
            for reason in MISSING:
                c[f"missing_{reason}_weighted"] = sum(t["weight"] for t in rows if missing_reason(t) == reason)
            c["lapsed_weighted"] = sum(t["weight"] for t in rows if t["status"] in ("lapsed", "bad_open"))
            c["complete_5_weighted"] = sum(t["weight"] for t in rows if t.get("net_excess_5") is not None)
        for h in HORIZONS:
            c[f"complete_{h}"] = sum(1 for t in rows if t.get(f"net_excess_{h}") is not None)
            c[f"ended_before_{h}"] = sum(1 for t in rows if t.get(f"ended_{h}"))
            c[f"suspect_split_{h}"] = sum(1 for t in rows if t.get(f"suspect_{h}"))
            c[f"no_dividend_adjustment_{h}"] = sum(1 for t in rows if t.get(f"no_dividend_adjustment_{h}"))
        c["while_held"] = sum(1 for t in rows if t.get("while_held"))
        c["first_entry"] = min((t["entry"] for t in rows if t.get("entry")), default=None)
        c["last_entry"] = max((t["entry"] for t in rows if t.get("entry")), default=None)
        for reason in MISSING:
            c[f"symbols_{reason}"] = sorted({t["symbol"] or t["key"] for t in rows if missing_reason(t) == reason})[:300]
        c["starts_late_examples"] = sorted(Counter(f"{t['symbol']} (from {t['yahoo_first_day']})" for t in rows
                                                   if t["status"] == "yahoo_starts_late").items(),
                                           key=lambda x: -x[1])[:10]
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
    starts = [r for r in rows if r["real_start"]]
    by_id = {e["message_ids"][0]: e for e in sample}
    agree = sum(1 for r in starts if by_id[r["message_id"]].get("incentive") == (r["message_id"] in INCENTIVE_ONLY))
    return {"seed": HAND_CHECK_SEED, "n": len(rows), "judged": len(judged),
            "real_starts": len(starts), "incentive_only_by_hand": sum(1 for r in starts if r["message_id"] in INCENTIVE_ONLY),
            "incentive_rule_agrees": agree, "sample": rows}


_GENERIC = {"asa", "as", "ab", "publ", "group", "holding", "holdings", "the", "company", "limited", "ltd", "plc",
            "inc", "and", "of", "bank", "ser", "sa", "se", "nv", "corporation", "corp", "international"}


def name_check(events: list[dict], bars: dict) -> dict:
    """Flag tickers whose Yahoo name shares no word with the issuer's name in NewsWeb or FI's register."""
    names = {e["key"]: (e["name"] or "", e["symbol"]) for e in events if e["symbol"]}
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
