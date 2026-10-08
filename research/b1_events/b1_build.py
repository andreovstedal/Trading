"""B1's events, built with the project's own rules (``advisor.features``).

Signal types (``kind``):
  buyback_start     pre-registered: NewsWeb own-shares category 1007 (from 2017-02-15), ``features.buyback_start``
  insider_cluster   pre-registered: FI register, >= 2 distinct insiders' purchases published within
                    ``features.EVENT_WINDOW``, seen at the evening decision as ``features._add_insider_se`` does,
                    with each row live from its own publication until the revision that replaced it was
                    published (FI's status today, 'Reviderad' or 'Makulerad', was not known that evening)
  insider_cluster_today  comparison: the same with only the rows FI shows as 'Aktuell' today (hindsight)
  insider_buy_no    pre-registered comparison: built in ``b1_oslo`` (title + body, as the code reads notices)
  insider_buy_no_title  subset: NewsWeb insider category 1102, ``features.insider_direction`` > 0 on the title
                    alone, from 2013-03-05 (the benchmark's start), without the company's own trades (buyback
                    words, treasury shares, own bonds), which sat in 1102 before 2017
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
            raw.append(_nw(m, "insider_buy_no_title" if at.date() >= INDEX_START else "insider_buy_no_pre2013", at))
    return merge(raw), dict(counts)


def _nw(m: dict, kind: str, at: datetime) -> dict:
    return {"kind": kind, "country": "NO", "key": m["issuer_sign"], "name": m["issuer_name"], "at": at,
            "title": m["title"], "message_ids": [m["message_id"]], "source": "newsweb"}


# Instrument names that are not a company's shares: paid subscribed shares and units (BTA, BTU), rights (TR,
# uniträtt), options (TO, KO, IL), warrants, bonds, notes, certificates, funds and structured products (often
# named by a maturity date such as 230619). Used only for rows FI left untyped (before 2018).
NON_SHARE = re.compile(
    r"(\w*BT[ABU]\d*[AB]?\b|\bBT\d|\b(TR[AB]?\d*|TO\s?\d*[AB]?|KO\s?\d*[AB]?|IL\s?[AB]?|IA|UR|KV|FC|RBO|STE\d*|"
    r"\w*rätt\w*|\w*option\w*|warrant\w*|obl\w*|bonds?|notes?|konvertib\w*|convertible|\w*certifikat\w*|aktiebevis|"
    r"förlagsbevis|debenture|float|interims?\w*|inlösen\w*|rights?|subscription|fund|fond\w*|\d{6}|\d{4}/\d{4})\b)",
    re.IGNORECASE)
ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def norm_isin(value: str | None) -> str:
    return (value or "").strip().upper()


def untyped_share_like(rows: list[dict], share_isins: set[str]) -> tuple[set[str], dict]:
    """ISINs of rows FI left untyped that look like a company's shares although FI never typed them 'Aktie' and
    Nordnet does not list them today (delisted companies, and old ISINs of live ones): a well-formed ISIN (the
    code matches rows to stocks by ISIN, so a mistyped one never counts) that is not a eurobond (XS), and
    most of the ISIN's rows say shares, a row voting against when FI typed it as something else or its instrument
    name names a paid subscribed share, a right, an option, a bond or the like (``NON_SHARE``)."""
    votes: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [share, not a share]
    for r in rows:
        isin = norm_isin(r["isin"])
        if not isin or isin in share_isins:
            continue
        against = bool(r["instrument_type"]) or bool(NON_SHARE.search(r["instrument_name"] or ""))
        votes[isin][against] += 1
    out, counts = set(), defaultdict(int)
    for isin, (share, against) in votes.items():
        counts["isins_not_known_shares"] += 1
        if not ISIN.match(isin) or isin.startswith("XS"):
            counts["malformed_or_eurobond_isin"] += 1
        elif against >= share:
            counts["mostly_typed_or_named_otherwise"] += 1
        else:
            out.add(isin)
    counts["share_like"] = len(out)
    return out, dict(counts)


def revisions(rows: list[dict]) -> tuple[dict[str, datetime], dict]:
    """When each revised row stopped being live: the publication of its correction (a later row from the same
    issuer for the same insider and transaction day marked as a correction; failing that, the same issuer,
    transaction day and volume). Revised rows without a correction found, and cancelled rows (FI does not
    publish when it cancelled them), stay live for the whole event window."""
    fold = lambda s: " ".join((s or "").lower().split())  # noqa: E731
    issuer = lambda r: r["lei"] or (r["issuer"] or "").lower()  # noqa: E731
    by_pdmr, by_volume = defaultdict(list), defaultdict(list)
    for r in rows:
        if r["is_correction"] and r["published_at"]:
            by_pdmr[(issuer(r), fold(r["pdmr"]), r["transaction_date"])].append(r)
            by_volume[(issuer(r), r["transaction_date"], r["volume"])].append(r)
    until, counts = {}, defaultdict(int)
    for r in rows:
        if r["status"] != "Reviderad" or not r["published_at"]:
            continue
        for how, pool in (("insider", by_pdmr[(issuer(r), fold(r["pdmr"]), r["transaction_date"])]),
                          ("volume", by_volume[(issuer(r), r["transaction_date"], r["volume"])])):
            later = [q["published_at"] for q in pool if q["published_at"] > r["published_at"]]
            if later:
                until[r["row_hash"]] = utc(min(later))
                counts[f"paired_by_{how}"] += 1
                break
        else:
            counts["unpaired"] += 1
    return until, dict(counts)


def fi_purchases(rows: list[dict], share_isins: set[str], share_like: set[str],
                 until: dict[str, datetime] | None) -> tuple[list[dict], dict]:
    """FI rows that ``features._add_insider_se`` counts as an insider's purchase: open-market acquisitions of
    shares not linked to a share programme. FI left the instrument type empty before about 2018; there a row
    counts when its ISIN is a share's (``share_isins``, or ``share_like``, counted apart).

    ``until`` given (point in time): every row counts from its publication, revised ones until their
    correction's publication (``revisions``). ``until`` None: only rows FI shows as 'Aktuell' today."""
    out, counts = [], defaultdict(int)
    for r in rows:
        counts["rows"] += 1
        if r["nature"] != "Förvärv" or r["linked_to_share_program"] is True:
            continue
        if until is None and r["status"] != "Aktuell":
            continue
        isin = norm_isin(r["isin"])
        if not isin or not r["published_at"]:
            continue
        if r["instrument_type"] == "Aktie":
            counts["purchases_typed_share"] += 1
        elif r["instrument_type"] == "" and isin in share_isins:
            counts["purchases_untyped_share_isin"] += 1
        elif r["instrument_type"] == "" and isin in share_like:
            counts["purchases_untyped_share_like"] += 1
        else:
            if r["instrument_type"] == "":
                counts["purchases_untyped_dropped"] += 1
            continue
        counts[f"status_{r['status']}"] += 1
        live_until = until.get(r["row_hash"]) if until is not None else None
        if r["status"] == "Reviderad" and live_until is not None:
            counts["revised_with_correction_found"] += 1
        out.append({**r, "isin": isin, "live_until": live_until})
    return out, dict(counts)


def fi_clusters(purchases: list[dict], evenings: list[date], kind: str = "insider_cluster") -> tuple[list[dict], dict]:
    """A cluster event on the first decision evening at which >= 2 distinct insiders (by ``pdmr``, as the code
    counts them) have purchases published within EVENT_WINDOW before the decision and still live then, after an
    evening without. The evening decision is at ``paper.EVENING`` (20:45 UTC) on each day either market trades."""
    by_isin: dict[str, list[tuple[datetime, str, dict]]] = defaultdict(list)
    for r in purchases:
        by_isin[r["isin"]].append((utc(r["published_at"]), r["pdmr"], r))
    decision_times = [datetime.combine(d, EVENING, timezone.utc) for d in evenings]
    events, counts = [], defaultdict(int)

    def live(t: datetime, r: dict, e: datetime) -> bool:
        return e - EVENT_WINDOW <= t <= e and (r["live_until"] is None or e < r["live_until"])

    for isin, items in by_isin.items():
        items.sort(key=lambda x: x[0])
        candidates = sorted({e for t, _, _ in items for e in _evenings_after(decision_times, t)})
        previous_on, previous_e = False, None
        for e in candidates:
            buyers = {p for t, p, r in items if live(t, r, e)}
            on = len(buyers) >= 2
            contiguous = previous_e is not None and _next_evening(decision_times, previous_e) == e
            if on and not (previous_on and contiguous):
                inside = [r for t, _, r in items if live(t, r, e)]
                seen: set = set()
                formed = e
                for t, p, r in items:  # the filing that made it a cluster: the second distinct insider's
                    if live(t, r, e):
                        seen.add(p)
                        if len(seen) >= 2:
                            formed = t
                            break
                folded = {" ".join((p or "").lower().split()) for p in buyers}
                counts["clusters"] += 1
                if len(folded) < 2:
                    counts["clusters_only_by_name_spelling"] += 1
                if any(r["status"] != "Aktuell" for r in inside):
                    counts["clusters_with_rows_revised_or_cancelled_later"] += 1
                events.append({
                    "kind": kind, "country": "SE", "key": isin, "name": inside[0]["issuer"],
                    "instrument_name": inside[0]["instrument_name"], "at": e, "buyers": len(buyers),
                    "notices": len(inside), "value": sum((r["volume"] or 0) * (r["price"] or 0) for r in inside),
                    "currency": inside[0]["currency"], "first_published": min(t for t, _, r in items
                                                                              if live(t, r, e)),
                    "published": formed, "source": "fi", "message_ids": [], "isins": [isin],
                })
            previous_on, previous_e = on, e
    merged = merge(events)
    counts["cluster_events_after_merge"] = len(merged)
    return merged, dict(counts)


def merge_by_symbol(events: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """After the tickers are known: one event per traded stock, not per ISIN or issuer sign. A company that
    changed ISIN (a split, a redemption) can form a cluster under each in the same week; the later is folded
    into the earlier when it comes within EVENT_WINDOW of it, as ``merge`` does. Weighted (sampled) rows are left
    alone."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    out = []
    for e in events:
        if e.get("symbol") and e.get("weight", 1.0) == 1.0:
            groups[(e["kind"], e["symbol"])].append(e)
        else:
            out.append(e)
    folded: dict[str, int] = defaultdict(int)
    for items in groups.values():
        items.sort(key=lambda e: (e["at"], e["key"]))
        current = None
        for e in items:
            if current is not None and e["at"] - current["at"] <= EVENT_WINDOW:
                current["notices"] += e.get("notices") or 0
                current["message_ids"] = current.get("message_ids", []) + e.get("message_ids", [])
                current["isins"] = sorted(set(current.get("isins", [])) | set(e.get("isins", [])))
                folded[e["kind"]] += 1
                continue
            current = e
            out.append(e)
    out.sort(key=lambda e: (e["at"], e["kind"], e["key"]))
    return out, dict(folded)


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

