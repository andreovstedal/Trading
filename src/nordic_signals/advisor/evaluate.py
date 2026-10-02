"""Scoring past recommendations against what prices actually did.

Every finished recommendation stored a score for every stock it looked at,
so once enough trading days have passed each one gets a forward return: 20,
60, 120 and 250 trading days for the long-term ranking, and 1, 2 and 5 for
short-term signals, counted on each country's own trading days. Start prices
are the prices the recommendation saw; end prices are closing prices from
Nordnet snapshots taken after the close, so returns exclude dividends.

``track_record`` then answers the questions in the research report: does the
ranking order stocks (rank IC), do the chosen stocks beat an equal-weighted
universe (excess return, hit rate), and do the short-term signals work.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timezone
from statistics import mean, stdev
from typing import Any

from sqlalchemy import insert, select

from ..collectors.base import NORDIC_TZ
from ..store import Store, utcnow
from .features import trading_day
from .scoring import percentile_ranks

LONG_HORIZONS = (20, 60, 120, 250)
SHORT_HORIZONS = (1, 2, 5)
MIN_IC_STOCKS = 10
MARKET_CLOSED = time(18, 0)  # local time; Oslo closes at 16:25 and Stockholm at 17:30


def evaluate(store: Store) -> int:
    """Compute outcomes that have matured since the last run. Returns the number of new outcomes."""
    recs = store.query(select(store.table("recommendations")).where(store.table("recommendations").c.status == "done"))
    if not recs:
        return 0
    o = store.table("outcomes")
    done = {(r["recommendation_id"], r["instrument_id"], r["horizon_days"])
            for r in store.query(select(o.c.recommendation_id, o.c.instrument_id, o.c.horizon_days))}

    s, sig = store.table("scores"), store.table("short_signals")
    rec_ids = [r["id"] for r in recs]
    start = {r["id"]: _local_date(r["created_at"]) for r in recs}
    wanted: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
    for row in store.query(select(s.c.recommendation_id, s.c.instrument_id, s.c.ref_price)
                           .where(s.c.recommendation_id.in_(rec_ids), s.c.eligible.is_(True))):
        # Short horizons too: they are the universe benchmark that short-term signals are measured against.
        wanted[(row["recommendation_id"], row["instrument_id"])] = (row["ref_price"], SHORT_HORIZONS + LONG_HORIZONS)
    for row in store.query(select(sig.c.recommendation_id, sig.c.instrument_id, sig.c.ref_price)
                           .where(sig.c.recommendation_id.in_(rec_ids))):
        key = (row["recommendation_id"], row["instrument_id"])
        price, horizons = wanted.get(key, (row["ref_price"], ()))
        wanted[key] = (price, tuple(sorted(set(horizons) | set(SHORT_HORIZONS))))

    ids = {i for _, i in wanted}
    series = _closing_prices(store, ids, min(start.values()))
    inst = store.table("instruments")
    country = {r["instrument_id"]: r["exchange_country"] for r in store.query(
        select(inst.c.instrument_id, inst.c.exchange_country).where(inst.c.instrument_id.in_(list(ids))))}
    # Trading days per country: the days on which its stocks traded (Oslo and Stockholm have different holidays).
    calendar_days: dict[str | None, set[date]] = defaultdict(set)
    for instrument_id, prices in series.items():
        calendar_days[country.get(instrument_id)].update(prices)
    calendars = {c: sorted(days) for c, days in calendar_days.items()}

    now = utcnow()
    rows = []
    for (rec_id, instrument_id), (start_price, horizons) in wanted.items():
        prices = series.get(instrument_id)
        if not prices or not start_price:
            continue
        traded = sorted(prices)
        later = [d for d in calendars[country.get(instrument_id)] if d > start[rec_id]]
        for h in horizons:
            if (rec_id, instrument_id, h) in done or len(later) < h:
                continue
            end_date = later[h - 1]
            # The latest close on or before the end date: a stock that did not trade kept its price.
            k = bisect_right(traded, end_date)
            if k == 0:
                continue
            end_price = prices[traded[k - 1]]
            rows.append({
                "recommendation_id": rec_id, "instrument_id": instrument_id, "horizon_days": h,
                "start_date": start[rec_id], "end_date": end_date, "start_price": start_price,
                "end_price": end_price, "ret": end_price / start_price - 1, "computed_at": now,
            })
    with store.engine.begin() as conn:
        for i in range(0, len(rows), 500):
            conn.execute(insert(o), rows[i:i + 500])
    return len(rows)


def track_record(store: Store) -> dict[str, Any]:
    """Aggregate outcomes per model version and horizon (long) and per signal type and horizon (short)."""
    recs = {r["id"]: r for r in store.query(select(store.table("recommendations")))}
    s, o, sig = store.table("scores"), store.table("outcomes"), store.table("short_signals")
    rows = store.query(
        select(o.c.recommendation_id, o.c.instrument_id, o.c.horizon_days, o.c.ret, s.c.score, s.c.long_shares,
               s.c.eligible)
        .join(s, (s.c.recommendation_id == o.c.recommendation_id) & (s.c.instrument_id == o.c.instrument_id))
    )
    by_rec_h: dict[tuple[int, int], list] = defaultdict(list)
    for r in rows:
        if r["eligible"]:
            by_rec_h[(r["recommendation_id"], r["horizon_days"])].append(r)

    per_rec: dict[tuple[int, int], dict[str, Any]] = {}
    for (rec_id, h), lines in by_rec_h.items():
        universe = mean(r["ret"] for r in lines)
        picks = [r["ret"] for r in lines if r["long_shares"]]
        per_rec[(rec_id, h)] = {
            "universe": universe,
            "picks": mean(picks) if picks else None,
            "excess": mean(picks) - universe if picks else None,
            "ic": spearman([(r["score"], r["ret"]) for r in lines if r["score"] is not None]),
        }

    long_rows = []
    groups: dict[tuple[str, int], list] = defaultdict(list)
    for (rec_id, h), stats in per_rec.items():
        if h in LONG_HORIZONS:
            groups[(recs[rec_id]["model_version"], h)].append((rec_id, stats))
    for (version, h), items in sorted(groups.items()):
        excess = [st["excess"] for _, st in items if st["excess"] is not None]
        ics = [st["ic"] for _, st in items if st["ic"] is not None]
        long_rows.append({
            "model_version": version, "horizon": h, "recommendations": len(items),
            "days": len({_local_date(recs[rid]["created_at"]) for rid, _ in items}),
            "picks": _mean([st["picks"] for _, st in items]),
            "universe": _mean([st["universe"] for _, st in items]),
            "excess": _mean(excess),
            "hit_rate": sum(e > 0 for e in excess) / len(excess) if excess else None,
            "ic": _mean(ics),
            "ic_t": mean(ics) / stdev(ics) * len(ics) ** 0.5 if len(ics) >= 3 and stdev(ics) > 0 else None,
        })

    short_groups: dict[tuple[str, int], list[float]] = defaultdict(list)
    signal_rows = store.query(
        select(sig.c.recommendation_id, sig.c.instrument_id, sig.c.signal_type, sig.c.direction, o.c.horizon_days,
               o.c.ret)
        .join(o, (o.c.recommendation_id == sig.c.recommendation_id) & (o.c.instrument_id == sig.c.instrument_id))
    )
    for r in signal_rows:
        stats = per_rec.get((r["recommendation_id"], r["horizon_days"]))
        if r["horizon_days"] in SHORT_HORIZONS and stats:
            short_groups[(r["signal_type"], r["horizon_days"])].append(r["direction"] * (r["ret"] - stats["universe"]))
    short_rows = [{
        "signal_type": signal, "horizon": h, "signals": len(values), "excess": mean(values),
        "hit_rate": sum(v > 0 for v in values) / len(values),
    } for (signal, h), values in sorted(short_groups.items())]
    return {"long": long_rows, "short": short_rows,
            "recommendations": sum(1 for r in recs.values() if r["status"] == "done")}


def spearman(pairs: list[tuple[float, float]]) -> float | None:
    if len(pairs) < MIN_IC_STOCKS:
        return None
    xs = percentile_ranks(dict(enumerate(p[0] for p in pairs)))
    ys = percentile_ranks(dict(enumerate(p[1] for p in pairs)))
    keys = list(xs)
    mx, my = mean(xs.values()), mean(ys.values())
    cov = sum((xs[k] - mx) * (ys[k] - my) for k in keys)
    vx = sum((xs[k] - mx) ** 2 for k in keys)
    vy = sum((ys[k] - my) ** 2 for k in keys)
    return cov / (vx * vy) ** 0.5 if vx and vy else None


def _closing_prices(store: Store, instrument_ids: set[int], since: date) -> dict[int, dict[date, float]]:
    """Closing price per instrument per trading day.

    Only snapshots taken after that day's close count: intraday prices are still moving, and between Nordnet's
    morning reset and the first trade "last" is 0.
    """
    t = store.table("nordnet_observations")
    since_dt = datetime(since.year, since.month, since.day, tzinfo=NORDIC_TZ)
    series: dict[int, dict[date, float]] = defaultdict(dict)
    rows = store.query(
        select(t.c.instrument_id, t.c.observed_at, t.c.tick_at, t.c.last)
        .where(t.c.instrument_id.in_(list(instrument_ids)), t.c.observed_at >= since_dt, t.c.last > 0)
        .order_by(t.c.observed_at)
    )
    for r in rows:
        day = trading_day(r["tick_at"], r["observed_at"])
        observed = _local(r["observed_at"])
        if observed.date() > day or observed.time() >= MARKET_CLOSED:
            series[r["instrument_id"]][day] = r["last"]
    return series


def _local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NORDIC_TZ)


def _local_date(dt: datetime) -> date:
    return _local(dt).date()


def _mean(values: list) -> float | None:
    present = [v for v in values if v is not None]
    return mean(present) if present else None
