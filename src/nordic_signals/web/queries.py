"""Read-only queries behind the web pages."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from ..advisor.features import NEWSWEB_INSIDER, build_features, insider_direction
from ..collectors.base import NORDIC_TZ
from ..jobs import SETS
from ..store import Store, utcnow

# Sources shown on the data page, in schedule order, with what each one is for.
SOURCES = {
    "nordnet": "Handlebare aksjer, kurser, nøkkeltall og antall eiere hos Nordnet",
    "newsweb": "Børsmeldinger fra Oslo Børs, blant annet innsidehandel og tilbakekjøp",
    "fi-insider": "Svensk innsidehandel (Finansinspektionen)",
    "fi-short": "Svenske shortposisjoner (Finansinspektionen)",
    "no-short": "Norske shortposisjoner (Finanstilsynet)",
    "mfn": "Svenske pressemeldinger (MFN)",
    "yahoo": "Kurshistorikk og kursen SEK/NOK (Yahoo)",
    "pumpfun": "pump.fun-lanseringer til målingen av pump-and-dump-filteret (DexScreener, Solana)",
    "lekepenger": "Lekepengekontoens beslutninger etter børsslutt (henter ingenting selv)",
}


def recent_recommendations(store: Store, limit: int = 15) -> list[dict[str, Any]]:
    """The ones asked for on this page or the CLI; the play-money account's are on its own page."""
    r = store.table("recommendations")
    return [dict(row) for row in store.query(select(r).where(r.c.origin.is_(None)).order_by(r.c.id.desc())
                                             .limit(limit))]


def last_policy(store: Store) -> dict[str, Any] | None:
    r = store.table("recommendations")
    row = store.scalar(select(r.c.policy).where(r.c.origin.is_(None)).order_by(r.c.id.desc()).limit(1))
    return row or None


def recommendation_lines(store: Store, rec_id: int) -> list[dict[str, Any]]:
    s = store.table("scores")
    return [dict(row) for row in store.query(select(s).where(s.c.recommendation_id == rec_id)
                                             .order_by(s.c.rank.is_(None), s.c.rank))]


def short_signal_lines(store: Store, rec_id: int) -> list[dict[str, Any]]:
    sig, s = store.table("short_signals"), store.table("scores")
    rows = store.query(
        select(sig, s.c.symbol, s.c.name, s.c.country, s.c.score, s.c.currency)
        .join(s, (s.c.recommendation_id == sig.c.recommendation_id) & (s.c.instrument_id == sig.c.instrument_id))
        .where(sig.c.recommendation_id == rec_id)
        .order_by(sig.c.direction.desc(), sig.c.amount.desc())
    )
    return [dict(row) for row in rows]


def exclusion_counts(lines: list[dict[str, Any]]) -> list[tuple[str, int]]:
    return Counter(line["exclusion"] for line in lines if line["exclusion"]).most_common()


def source_status(store: Store) -> list[dict[str, Any]]:
    """Latest run and latest successful run for each source."""
    runs = store.table("runs")
    latest = {r["source"]: r for r in store.last_runs()}
    ok_rows = store.query(
        select(runs.c.source, func.max(runs.c.finished_at).label("at")).where(runs.c.ok.is_(True))
        .group_by(runs.c.source)
    )
    last_ok = {r["source"]: r["at"] for r in ok_rows}
    out = []
    for source, purpose in SOURCES.items():
        run = latest.get(source)
        out.append({
            "source": source,
            "purpose": purpose,
            "last_ok": _aware(last_ok.get(source)),
            "last_run": _aware(run["started_at"]) if run else None,
            "state": None if run is None else ("running" if run["ok"] is None else ("ok" if run["ok"] else "failed")),
            "error": run["error"] if run else None,
            "summary": run["summary"] if run else None,
        })
    return out


def stale_sources(statuses: list[dict[str, Any]], *, max_age: timedelta = timedelta(days=4)) -> list[str]:
    now = utcnow()
    core = ("nordnet", "newsweb", "fi-insider", "fi-short", "no-short")
    return [s["source"] for s in statuses if s["source"] in core and (not s["last_ok"] or now - s["last_ok"] > max_age)]


def signals(store: Store) -> dict[str, list[dict[str, Any]]]:
    """Fresh events across the universe, grouped by type, from the same features the model uses."""
    groups: dict[str, list[dict[str, Any]]] = {
        "insider_buy": [], "insider_notice": [], "buyback_start": [], "short_increase": []}
    for stock in build_features(store, utcnow()):
        for event in stock.events:
            item = {**event, "instrument_id": stock.instrument_id, "symbol": stock.symbol, "name": stock.name,
                    "country": stock.country}
            groups.setdefault(event["type"], []).append(item)
    for items in groups.values():
        items.sort(key=lambda e: e["at"], reverse=True)
    return groups


def stock_page(store: Store, instrument_id: int) -> dict[str, Any] | None:
    instrument = store.get("instruments", instrument_id=instrument_id)
    if instrument is None:
        return None
    s, r = store.table("scores"), store.table("recommendations")
    line = store.query(
        select(s).join(r, r.c.id == s.c.recommendation_id)
        .where(s.c.instrument_id == instrument_id, r.c.status == "done")
        .order_by(s.c.recommendation_id.desc()).limit(1)
    )
    since = utcnow() - timedelta(days=90)
    page: dict[str, Any] = {"instrument": dict(instrument), "line": dict(line[0]) if line else None,
                            "announcements": [], "insider_trades": [], "shorts": []}
    if instrument["exchange_country"] == "NO":
        c = store.table("newsweb_categories")
        names = {r["category_id"]: (r["name_no"] or "").capitalize() for r in store.query(select(c))}
        m, b = store.table("newsweb_messages"), store.table("newsweb_bodies")
        for row in store.query(
            select(m.c.message_id, m.c.title, m.c.category_en, m.c.category_ids, m.c.published_at, b.c.body)
            .outerjoin(b, b.c.message_id == m.c.message_id)
            .where(m.c.issuer_sign == instrument["symbol"], m.c.published_at >= since)
            .order_by(m.c.published_at.desc()).limit(40)
        ):
            first = (row["category_ids"] or [None])[0]
            item = {"at": _aware(row["published_at"]), "title": row["title"],
                    "category": names.get(first) or row["category_en"],
                    "url": f"https://newsweb.oslobors.no/message/{row['message_id']}"}
            if NEWSWEB_INSIDER in (row["category_ids"] or []):
                item["direction"] = insider_direction(f"{row['title']} {row['body'] or ''}")
            page["announcements"].append(item)
        page["shorts"] = _open_shorts_no(store, instrument["isin"])
    else:
        mi = store.table("mfn_items")
        for row in store.query(
            select(mi.c.title, mi.c.publish_date, mi.c.url, mi.c.isins, mi.c.lang)
            .where(mi.c.publish_date >= since).order_by(mi.c.publish_date.desc())
        ):
            if instrument["isin"] in (row["isins"] or []) and len(page["announcements"]) < 40:
                page["announcements"].append({"at": _aware(row["publish_date"]), "title": row["title"],
                                              "category": row["lang"], "url": row["url"]})
        it = store.table("se_insider_trades")
        page["insider_trades"] = [dict(row) for row in store.query(
            select(it.c.published_at, it.c.position, it.c.nature, it.c.volume, it.c.price, it.c.currency,
                   it.c.linked_to_share_program, it.c.instrument_type)
            .where(it.c.isin == instrument["isin"], it.c.published_at >= since, it.c.status == "Aktuell")
            .order_by(it.c.published_at.desc()).limit(40)
        )]
        page["shorts"] = _open_shorts_se(store, instrument["isin"])
    return page


def _open_shorts_no(store: Store, isin: str | None) -> list[dict[str, Any]]:
    """The positions listed at the instrument's latest register event; a total of 0 means none are open."""
    totals, positions = store.table("no_short_totals"), store.table("no_short_positions")
    latest = store.scalar(select(func.max(totals.c.date)).where(totals.c.isin == isin)) if isin else None
    if latest is None:
        return []
    rows = store.query(select(positions).where(positions.c.isin == isin, positions.c.date == latest))
    return _by_size([{"holder": r["holder"], "pct": r["short_pct"], "date": r["position_date"] or r["date"]}
                     for r in rows])


def _open_shorts_se(store: Store, isin: str | None) -> list[dict[str, Any]]:
    """The positions in FI's latest current-positions file (the table also holds closed ones from the history file)."""
    fetches, positions = store.table("fetches"), store.table("se_short_positions")
    current = store.scalar(select(func.max(fetches.c.id)).where(
        fetches.c.source == "fi-short", fetches.c.url.like("%/GetAktuellFile%"), fetches.c.status == 200))
    if current is None or not isin:
        return []
    rows = store.query(select(positions).where(positions.c.isin == isin, positions.c.last_fetch_id == current))
    return _by_size([{"holder": r["holder"], "pct": r["position_pct"], "date": r["position_date"]} for r in rows])


def _by_size(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: r["pct"] or 0, reverse=True)


def backfill_summary() -> str:
    return ", ".join(dict.fromkeys(source for source, _ in SETS["backfill"]))  # yahoo runs twice: FX and shares


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive UTC datetimes; make them aware so they can be compared and shown in Oslo time."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def to_local(dt: datetime | None) -> datetime | None:
    dt = _aware(dt)
    return dt.astimezone(NORDIC_TZ) if dt else None
