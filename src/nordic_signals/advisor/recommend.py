"""Making a recommendation end to end, and logging everything it was based on."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select

from ..store import Store, utcnow
from .allocation import SHORT_HORIZON_DAYS, Policy, allocate_long, short_sleeve
from .features import build_features
from .scoring import MODEL_VERSION, PARAMS, score_stocks

log = logging.getLogger(__name__)

FX_PAIRS = {"SEK": "SEKNOK=X"}


def create(store: Store, policy: Policy, *, origin: str | None = None) -> int:
    recs = store.table("recommendations")
    with store.engine.begin() as conn:
        return conn.execute(
            insert(recs).values(created_at=utcnow(), status="queued", model_version=MODEL_VERSION,
                                account_value=policy.account_value, currency="NOK", policy=policy.as_dict(),
                                params=_jsonable(PARAMS), origin=origin)
            .returning(recs.c.id)
        ).scalar_one()


def run(store: Store, rec_id: int, *, refresh: Callable[[], dict[str, Any]] | None = None) -> None:
    """Refresh data (optional), score the universe, allocate, and store it all under ``rec_id``."""
    row = store.get("recommendations", id=rec_id)
    policy = Policy(**row["policy"])
    _update(store, rec_id, status="running")
    try:
        refreshed = refresh() if refresh else None
        asof = utcnow()
        fx = load_fx(store, asof)
        stocks = build_features(store, asof, policy.countries)
        if not stocks:
            raise RuntimeError("Ingen ferske data fra Nordnet. Kjør den daglige innsamlingen, eller trykk på"
                               " knappen med «Oppdater data først» krysset av.")
        scored = score_stocks(stocks, fx, target_position=policy.target_position, ask_only=policy.ask_only)
        positions, long_notes = allocate_long(scored, policy)
        signals, short_notes = short_sleeve(scored, policy)
        _save_lines(store, rec_id, scored, positions, signals)
        invested = sum(p.amount for p in positions)
        traded_short = sum(s.amount for s in signals if s.direction > 0 and not s.paper)
        summary = {
            "asof": asof.isoformat(),
            "universe": len(scored),
            "eligible": sum(s.eligible for s in scored),
            "positions": len(positions),
            "long_invested": invested,
            "short_invested": traded_short,
            "cash": policy.account_value - invested - traded_short,
            "fx": fx,
            "notes": long_notes + short_notes,
        }
        _update(store, rec_id, status="done", finished_at=utcnow(), summary=summary,
                data_cutoff=data_cutoff(store), refresh=refreshed)
    except Exception as exc:
        log.exception("recommendation %s failed", rec_id)
        _update(store, rec_id, status="failed", finished_at=utcnow(), error=f"{type(exc).__name__}: {exc}")


def load_fx(store: Store, asof: datetime) -> dict[str, float]:
    """NOK per unit of each supported currency, from the latest Yahoo daily close."""
    p = store.table("price_bars")
    fx = {"NOK": 1.0}
    for currency, symbol in FX_PAIRS.items():
        rate = store.scalar(
            select(p.c.close).where(p.c.symbol == symbol, p.c.interval == "1d", p.c.first_seen_at <= asof)
            .order_by(p.c.ts.desc()).limit(1)
        )
        if rate:
            fx[currency] = rate
    return fx


def data_cutoff(store: Store) -> dict[str, str]:
    """When each source last ran successfully, as shown next to a recommendation."""
    runs = store.table("runs")
    rows = store.query(
        select(runs.c.source, func.max(runs.c.finished_at).label("at")).where(runs.c.ok.is_(True))
        .group_by(runs.c.source)
    )
    return {r["source"]: r["at"].isoformat() for r in rows if r["at"]}


def _save_lines(store: Store, rec_id: int, scored, positions, signals) -> None:
    held = {p.stock.instrument_id: p for p in positions}
    rows = []
    for item in scored:
        s, position = item.stock, held.get(item.stock.instrument_id)
        rows.append({
            "recommendation_id": rec_id,
            "instrument_id": s.instrument_id,
            "isin": s.isin,
            "symbol": s.symbol,
            "name": s.name,
            "country": s.country,
            "segments": s.segments,
            "currency": s.currency,
            "eligible": item.eligible,
            "exclusion": item.exclusion,
            "score": item.score,
            "rank": item.rank,
            "themes": _jsonable(item.themes),
            "overlays": _jsonable(item.overlays),
            "features": _jsonable(s.features),
            "events": _jsonable(s.events),
            "reasons": item.reasons,
            "ref_price": s.price,
            "fx_rate": item.fx,
            "long_amount": position.amount if position else None,
            "long_shares": position.shares if position else None,
            "long_weight": position.weight if position else None,
        })
    signal_rows = [{
        "recommendation_id": rec_id,
        "instrument_id": sig.stock.instrument_id,
        "signal_type": sig.signal,
        "direction": sig.direction,
        "description": sig.description,
        "paper": sig.paper,
        "amount": sig.amount,
        "shares": sig.shares,
        "ref_price": sig.stock.price,
        "fx_rate": sig.scored.fx,
        "horizon_days": SHORT_HORIZON_DAYS,
    } for sig in signals]
    with store.engine.begin() as conn:
        for start in range(0, len(rows), 500):
            conn.execute(insert(store.table("scores")), rows[start:start + 500])
        if signal_rows:
            conn.execute(insert(store.table("short_signals")), signal_rows)


def _update(store: Store, rec_id: int, **values: Any) -> None:
    recs = store.table("recommendations")
    with store.engine.begin() as conn:
        conn.execute(recs.update().where(recs.c.id == rec_id).values(**values))


def _jsonable(value: Any) -> Any:
    """Plain JSON types only: NaN and infinity become None, tuples become lists."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
