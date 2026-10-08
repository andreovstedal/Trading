"""B1's events, built with the project's own rules (``advisor.features``).

Signal types (``kind``):
  buyback_start     pre-registered: NewsWeb own-shares category 1007 (from 2017-02-15), ``features.buyback_start``
  insider_cluster   pre-registered: FI register, >= 2 distinct insiders' purchases published within
                    ``features.EVENT_WINDOW``, seen at the evening decision as ``features._add_insider_se`` does
  insider_buy_no    pre-registered comparison: NewsWeb insider category 1102, ``features.insider_direction`` > 0
                    on the title, from 2013-03-05 (the benchmark's start), without the company's own trades
                    (buyback words, treasury shares, own bonds), which sat in 1102 before 2017
  buyback_start_1102   exploratory: before 2017-02-15 buyback notices sat in 1102; same title rule, 2013-03-05..
  insider_buy_no_pre2013  exploratory: 1102 purchases 2005-01..2013-03-04, against an equal-weighted benchmark
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from nordic_signals.advisor.features import (
    _BUYBACK_WORDS,
    EVENT_WINDOW,
    NEWSWEB_INSIDER,
    NEWSWEB_OWN_SHARES,
    buyback_start,
    insider_direction,
)
from nordic_signals.advisor.paper import EVENING

INDEX_START = date(2013, 3, 5)
# The company's own trades, which sat in 1102 before 2017: not an insider's purchase. ``features._BUYBACK_WORDS``
# plus treasury shares and own bonds, which it does not name.
_COMPANY_OWN = re.compile(r"treasury|egne obligasjon|own bonds", re.IGNORECASE)
OWN_SHARES_START = date(2017, 2, 15)


def utc(value: str | datetime) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def merge(raw: list[dict]) -> list[dict]:
    """One event per stock and signal: notices of the same kind for the same stock published within
    EVENT_WINDOW of the event they would join (the Norwegian and English versions, repeats, several insiders'
    notices) are one event, timed by the first. The window is the one in which the advisor's flag stays on."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in raw:
        groups[(r["kind"], r["key"])].append(r)
    out = []
    for items in groups.values():
        items.sort(key=lambda r: r["at"])
        current = None
        for r in items:
            if current is not None and r["at"] - current["at"] <= EVENT_WINDOW:
                current["notices"] += 1
                current["message_ids"].extend(r.get("message_ids", []))
                continue
            current = {**r, "notices": 1, "message_ids": list(r.get("message_ids", []))}
            out.append(current)
    out.sort(key=lambda e: (e["at"], e["kind"], e["key"]))
    return out


def newsweb_events(lists: dict[int, list[dict]], end: date) -> tuple[list[dict], dict]:
    """Buyback starts and Norwegian insider purchase notices, plus counts of what was dropped and why."""
    raw: list[dict] = []
    counts: dict[str, int] = defaultdict(int)
    for m in lists[NEWSWEB_OWN_SHARES]:
        if m.get("is_test") or not m["published_at"]:
            continue
        at = utc(m["published_at"])
        if not OWN_SHARES_START <= at.date() <= end:
            continue
        counts["1007_messages"] += 1
        title = m["title"] or ""
        if NEWSWEB_OWN_SHARES in (m["category_ids"] or []) and buyback_start(title):
            counts["1007_buyback_start_titles"] += 1
            raw.append(_nw(m, "buyback_start", at))
    for m in lists[NEWSWEB_INSIDER]:
        if m.get("is_test") or not m["published_at"]:
            continue
        at = utc(m["published_at"])
        if at.date() > end:
            continue
        title = m["title"] or ""
        cats = set(m["category_ids"] or [])
        counts["1102_messages"] += 1
        own_shares = bool(_BUYBACK_WORDS.search(title) or _COMPANY_OWN.search(title)) or NEWSWEB_OWN_SHARES in cats
        if at.date() < OWN_SHARES_START and own_shares and buyback_start(title) and at.date() >= INDEX_START:
            counts["1102_pre2017_buyback_start_titles"] += 1
            raw.append(_nw(m, "buyback_start_1102", at))
        direction = insider_direction(title)
        counts[f"1102_direction_{direction:+d}"] += 1
        if direction > 0 and own_shares:
            counts["1102_purchase_titles_dropped_as_own_shares"] += 1
            continue
        if direction > 0:
            counts["1102_purchase_titles"] += 1
            raw.append(_nw(m, "insider_buy_no" if at.date() >= INDEX_START else "insider_buy_no_pre2013", at))
    return merge(raw), dict(counts)


def _nw(m: dict, kind: str, at: datetime) -> dict:
    return {"kind": kind, "country": "NO", "key": m["issuer_sign"], "name": m["issuer_name"], "at": at,
            "title": m["title"], "message_ids": [m["message_id"]], "source": "newsweb"}


def fi_purchases(rows: list[dict], share_isins: set[str]) -> tuple[list[dict], dict]:
    """FI rows that ``features._add_insider_se`` counts as an insider's purchase: current, open-market
    acquisitions of shares not linked to a share programme. FI left the instrument type empty before about
    2018; there a row counts when its ISIN is a share's (``share_isins``)."""
    out, counts = [], defaultdict(int)
    for r in rows:
        counts["rows"] += 1
        if r["status"] != "Aktuell" or r["nature"] != "Förvärv" or r["linked_to_share_program"] is True:
            continue
        if not r["isin"] or not r["published_at"]:
            continue
        if r["instrument_type"] == "Aktie":
            counts["purchases_typed_share"] += 1
        elif r["instrument_type"] == "" and r["isin"] in share_isins:
            counts["purchases_untyped_share_isin"] += 1
        else:
            continue
        out.append(r)
    return out, dict(counts)


def fi_clusters(purchases: list[dict], evenings: list[date]) -> tuple[list[dict], dict]:
    """A cluster event on the first decision evening at which >= 2 distinct insiders (by ``pdmr``, as the code
    counts them) have purchases published within EVENT_WINDOW before the decision, after an evening without.
    The evening decision is at ``paper.EVENING`` (20:45 UTC) on each day either market trades."""
    by_isin: dict[str, list[tuple[datetime, str, dict]]] = defaultdict(list)
    for r in purchases:
        by_isin[r["isin"]].append((utc(r["published_at"]), r["pdmr"], r))
    decision_times = [datetime.combine(d, EVENING, timezone.utc) for d in evenings]
    events, counts = [], defaultdict(int)
    for isin, items in by_isin.items():
        items.sort(key=lambda x: x[0])
        candidates = sorted({e for t, _, _ in items for e in _evenings_after(decision_times, t)})
        previous_on, previous_e = False, None
        for e in candidates:
            buyers = {p for t, p, _ in items if e - EVENT_WINDOW <= t <= e}
            on = len(buyers) >= 2
            contiguous = previous_e is not None and _next_evening(decision_times, previous_e) == e
            if on and not (previous_on and contiguous):
                inside = [r for t, _, r in items if e - EVENT_WINDOW <= t <= e]
                folded = {" ".join((p or "").lower().split()) for p in buyers}
                counts["clusters"] += 1
                if len(folded) < 2:
                    counts["clusters_only_by_name_spelling"] += 1
                events.append({
                    "kind": "insider_cluster", "country": "SE", "key": isin, "name": inside[0]["issuer"],
                    "instrument_name": inside[0]["instrument_name"], "at": e, "buyers": len(buyers),
                    "notices": len(inside), "value": sum((r["volume"] or 0) * (r["price"] or 0) for r in inside),
                    "currency": inside[0]["currency"], "first_published": min(t for t, _, _ in items
                                                                              if e - EVENT_WINDOW <= t <= e),
                    "source": "fi", "message_ids": [],
                })
            previous_on, previous_e = on, e
    merged = merge(events)
    counts["cluster_events_after_merge"] = len(merged)
    return merged, dict(counts)


def _evenings_after(decision_times: list[datetime], t: datetime) -> list[datetime]:
    from bisect import bisect_left

    i = bisect_left(decision_times, t)
    out = []
    while i < len(decision_times) and decision_times[i] - t <= EVENT_WINDOW:
        out.append(decision_times[i])
        i += 1
    return out


def _next_evening(decision_times: list[datetime], e: datetime) -> datetime | None:
    from bisect import bisect_right

    i = bisect_right(decision_times, e)
    return decision_times[i] if i < len(decision_times) else None


def decision_date(at: datetime, evenings: list[date]) -> date | None:
    """The evening whose 20:45 UTC decision first sees an event published at ``at``."""
    from bisect import bisect_left

    day = at.date() if at.time() <= EVENING else at.date() + timedelta(days=1)
    i = bisect_left(evenings, day)
    return evenings[i] if i < len(evenings) else None

