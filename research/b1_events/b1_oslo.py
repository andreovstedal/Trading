"""Oslo insider purchase notices as the project's code reads them: ``insider_direction`` on title + body
(``features._add_newsweb``), not on the title alone.

Reading every body would take some 6 hours of requests (22,497 notices whose title states no direction), so the
estimate is a two-phase one:

  census   every event that contains a notice whose title states a purchase (all 1,358 such bodies are read,
           and the notice counts only if title + body still read as a purchase);
  sample   the title-silent notices are sampled at random (seed BODY_SAMPLE_SEED, n = 1,500 of N); each sampled
           notice that title + body read as a purchase is followed to its event, and an event without a
           title-stated purchase enters with the Hansen-Hurwitz weight

               w = (N / n) / m,     m = the number of title-silent purchase notices in the event,

           so that sum over sampled notices of w * y estimates the sum of y over all such events.

An event is built exactly as ``b1_build.merge`` builds one (a stock's purchase notices within EVENT_WINDOW of the
event's first notice), from all of the stock's notices around the seed: the bodies of the same issuer's notices
are read backwards until a 4-day gap without a purchase, and forwards to the end of the seed's event. Notices
whose body names the company's own shares or bonds are the company's trades, not an insider's, as in the title
rule; a notice whose body could not be fetched is read on its title alone, as the code would.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date

from b1_build import _COMPANY_OWN, EVENT_WINDOW, INDEX_START, utc
from b1_fetch import Cache, newsweb_body

from nordic_signals.advisor.features import (
    _BUY_WORDS,
    _BUYBACK_WORDS,
    _SELL_WORDS,
    NEWSWEB_OWN_SHARES,
    insider_direction,
)

BODY_SAMPLE_SEED, BODY_SAMPLE_N = 1102, 1500


def _own_title(m: dict) -> bool:
    title = m["title"] or ""
    return bool(_BUYBACK_WORDS.search(title) or _COMPANY_OWN.search(title)) or NEWSWEB_OWN_SHARES in (
        m["category_ids"] or [])


class OsloNotices:
    """The 1102 notices from 2013-03-05 that could be an insider's purchase, by issuer, with their bodies read on
    demand (cached)."""

    def __init__(self, cache: Cache, messages: list[dict], end: date):
        self.cache = cache
        self.notices: list[dict] = []
        for m in messages:
            if m.get("is_test") or not m["published_at"]:
                continue
            at = utc(m["published_at"])
            if not INDEX_START <= at.date() <= end or _own_title(m):
                continue
            title = m["title"] or ""
            direction = insider_direction(title)
            if direction < 0:  # a sale in the title stays a sale or ambiguous with any body
                continue
            self.notices.append({**m, "at": at, "title_direction": direction,
                                 # both words in the title: ambiguous with any body, no need to read it
                                 "title_ambiguous": direction == 0 and bool(_BUY_WORDS.search(title))
                                 and bool(_SELL_WORDS.search(title))})
        self.notices.sort(key=lambda m: (m["at"], m["message_id"]))
        self.by_issuer: dict[str, list[dict]] = defaultdict(list)
        for m in self.notices:
            self.by_issuer[m["issuer_sign"]].append(m)
        self._purchase: dict[int, bool] = {}
        self.counts: dict[str, int] = defaultdict(int)

    def title_purchases(self) -> list[dict]:
        return [m for m in self.notices if m["title_direction"] > 0]

    def title_silent(self) -> list[dict]:
        """The sampling frame: titles with no direction, sorted by message id (as the sample was first drawn)."""
        return sorted((m for m in self.notices if m["title_direction"] == 0), key=lambda m: m["message_id"])

    def is_purchase(self, m: dict) -> bool:
        mid = m["message_id"]
        if mid not in self._purchase:
            if m["title_ambiguous"]:
                self._purchase[mid] = False
            else:
                body = newsweb_body(self.cache, mid)
                self.counts["bodies_read"] += 1
                if body is None:
                    self.counts["no_body"] += 1
                text = f"{m['title'] or ''} {body or ''}"
                own = bool(body and (_BUYBACK_WORDS.search(body) or _COMPANY_OWN.search(body)))
                direction = insider_direction(text)
                if direction > 0 and own:
                    self.counts["purchase_but_own_shares_in_body"] += 1
                self._purchase[mid] = direction > 0 and not own
                m["text_direction"] = direction
        return self._purchase[mid]

    def event_of(self, seed: dict) -> dict:
        """The event (as ``merge`` would build it from all purchase notices) that contains ``seed``."""
        items = self.by_issuer[seed["issuer_sign"]]
        key = lambda m: (m["at"], m["message_id"])  # noqa: E731
        first = seed
        while True:  # back to a purchase with no purchase notice in the 4 days before it
            before = [m for m in items if first["at"] - EVENT_WINDOW <= m["at"] and key(m) < key(first)
                      and self.is_purchase(m)]
            if not before:
                break
            first = min(before, key=key)
        start, members = None, []
        for m in items:
            if key(m) < key(first):
                continue
            if start is not None and m["at"] - start["at"] > EVENT_WINDOW:
                if any(x["message_id"] == seed["message_id"] for x in members):
                    break
                if not self.is_purchase(m):
                    continue
                start, members = m, [m]
                continue
            if not self.is_purchase(m):
                continue
            if start is None:
                start = m
            members.append(m)
        return {"start": start, "members": members,
                "census": any(x["title_direction"] > 0 for x in members),
                "m_silent": sum(1 for x in members if x["title_direction"] == 0)}


def events(cache: Cache, messages: list[dict], end: date) -> tuple[list[dict], dict]:
    """The pre-registered Oslo insider-purchase events, census rows weighted 1 and sample rows weighted as above."""
    data = OsloNotices(cache, messages, end)
    frame = data.title_silent()
    sample = random.Random(BODY_SAMPLE_SEED).sample(frame, min(BODY_SAMPLE_N, len(frame)))
    expand = len(frame) / len(sample)
    out: list[dict] = []
    seen_census: set[int] = set()
    counts = {"title_purchase_notices": len(data.title_purchases()), "title_silent_notices": len(frame),
              "sampled": len(sample)}
    title_kept = 0
    for m in data.title_purchases():
        if not data.is_purchase(m):
            reason = "ambiguous_on_body" if m.get("text_direction", 0) <= 0 else "own_shares_in_body"
            counts[f"title_purchases_{reason}"] = counts.get(f"title_purchases_{reason}", 0) + 1
            continue
        title_kept += 1
        e = data.event_of(m)
        if e["start"]["message_id"] in seen_census:
            continue
        seen_census.add(e["start"]["message_id"])
        out.append(_event(e, 1.0, "census"))
    sample_purchases = 0
    in_census = 0
    for m in sorted(sample, key=lambda m: (m["at"], m["message_id"])):
        if not data.is_purchase(m):
            continue
        sample_purchases += 1
        e = data.event_of(m)
        if e["census"]:
            in_census += 1  # already counted with weight 1 through its title-stated notice
            continue
        out.append(_event(e, expand / e["m_silent"], "sample", seed=m["message_id"]))
    counts.update(title_purchases_on_title_and_body=title_kept, census_events=len(seen_census),
                  sampled_purchases=sample_purchases, sampled_purchases_in_census_events=in_census,
                  sample_rows=sum(1 for e in out if e["stratum"] == "sample"),
                  estimated_events=sum(e["weight"] for e in out), expansion=expand)
    sample_directions: dict[str, int] = defaultdict(int)
    for m in sample:
        data.is_purchase(m)
        sample_directions[f"{m.get('text_direction', 0):+d}"] += 1
    counts["sample_text_directions"] = dict(sample_directions)
    counts.update(data.counts)
    out.sort(key=lambda e: (e["at"], e["key"]))
    return out, counts


def _event(e: dict, weight: float, stratum: str, seed: int | None = None) -> dict:
    s = e["start"]
    return {"kind": "insider_buy_no", "country": "NO", "key": s["issuer_sign"], "name": s["issuer_name"],
            "at": s["at"], "title": s["title"], "notices": len(e["members"]),
            "message_ids": [x["message_id"] for x in e["members"]], "source": "newsweb", "weight": weight,
            "stratum": stratum, "m_silent": e["m_silent"], "seed": seed}
