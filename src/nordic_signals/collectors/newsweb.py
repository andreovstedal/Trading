"""Euronext Oslo Børs NewsWeb: every announcement from Oslo-listed issuers.

newsweb.oslobors.no is a single-page app whose data comes from a keyless JSON
API on api3.oslo.oslobors.no (verified live 2026-10-02):

* ``GET  /v1/newsreader/list?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD[&category=ID]``
  Dates are Oslo local dates. One response holds at most about 600 messages
  and sets ``data.overflow`` when more matched, so we ask for one day at a time.
* ``GET  /v1/newsreader/message?messageId=ID``: full text plus attachment list.
* ``GET  /v1/newsreader/attachment?messageId=ID&attachmentId=ID``: file bytes.
* ``POST /v1/newsreader/categories``: category ids and names (GET answers 405).

Insider trades are category 1102 ("Meldepliktig handel for primærinnsidere");
their details are free text, often with the official form as a PDF attachment.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from datetime import date
from typing import Any

from .base import Collector, RunSummary, date_range

API = "https://api3.oslo.oslobors.no/v1/newsreader"

# Categories whose full text is fetched by default: insider trades, inside
# information, major shareholdings, own-share (buyback) reports, and annual
# and half-year reports.
DETAIL_CATEGORIES = frozenset({1102, 1005, 1006, 1007, 1001, 1002})


def parse_categories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    items = data.get("categories", []) if isinstance(data, dict) else data or []
    return [
        {"category_id": c["id"], "name_no": c.get("category_no"), "name_en": c.get("category_en")}
        for c in items
    ]


def parse_list(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    data = payload["data"]
    messages = [_message_row(m) for m in data.get("messages", [])]
    return messages, bool(data.get("overflow"))


def parse_message(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = payload["data"]
    m = data.get("message", data)
    attachments = [{"attachment_id": a["id"], "name": a.get("name")} for a in m.get("attachments", [])]
    body = {"message_id": int(m["messageId"]), "body": m.get("body"), "attachments": attachments}
    return body, attachments


def _message_row(m: dict[str, Any]) -> dict[str, Any]:
    categories = m.get("category") or []
    return {
        "message_id": int(m["messageId"]),
        "news_id": m.get("newsId"),
        "published_at": m.get("publishedTime"),
        "issuer_id": m.get("issuerId"),
        "issuer_sign": m.get("issuerSign"),
        "issuer_name": m.get("issuerName"),
        "title": m.get("title"),
        "category_ids": [c["id"] for c in categories],
        "category_en": "; ".join(c.get("category_en") or "" for c in categories),
        "markets": m.get("markets") or [],
        "instrument_id": m.get("instrId") or None,
        "instrument_name": m.get("instrumentName") or None,
        "correction_for_message_id": m.get("correctionForMessageId") or None,
        "corrected_by_message_id": m.get("correctedByMessageId") or None,
        "num_attachments": m.get("numbAttachments"),
        "is_test": m.get("test"),
        "client_announcement_id": m.get("clientAnnouncementId"),
    }


class NewsWebCollector(Collector):
    source = "newsweb"

    def run(
        self,
        *,
        start: date,
        end: date,
        detail_categories: Collection[int] = DETAIL_CATEGORIES,
        attachments: bool = False,
    ) -> RunSummary:
        category_ids = self._categories()
        for day in date_range(start, end):
            messages = self._list_day(day, category_ids)
            wanted = [m for m in messages if set(m["category_ids"]) & set(detail_categories)]
            for m in wanted:
                if not self._has_body(m["message_id"]):
                    self._detail(m["message_id"], attachments)
        return self.summary

    def _categories(self) -> list[int]:
        resp, fetch_id = self.fetch("POST", f"{API}/categories")
        rows = parse_categories(resp.json())
        self.save("newsweb_categories", rows, fetch_id)
        return [r["category_id"] for r in rows]

    def _list_day(self, day: date, category_ids: list[int]) -> list[dict[str, Any]]:
        params = {"fromDate": day.isoformat(), "toDate": day.isoformat()}
        resp, fetch_id = self.fetch("GET", f"{API}/list", params=params)
        messages, overflow = parse_list(resp.json())
        self.save("newsweb_messages", messages, fetch_id)
        if not overflow:
            return messages

        # Too many for one response: ask category by category.
        by_id = {m["message_id"]: m for m in messages}
        for category in category_ids:
            resp, fetch_id = self.fetch("GET", f"{API}/list", params={**params, "category": category})
            more, still_overflow = parse_list(resp.json())
            if still_overflow:
                self.warn(f"{day}: category {category} still overflows; some messages are missing")
            self.save("newsweb_messages", more, fetch_id)
            by_id.update((m["message_id"], m) for m in more)
        return list(by_id.values())

    def _has_body(self, message_id: int) -> bool:
        return self.store.get("newsweb_bodies", message_id=message_id) is not None

    def _detail(self, message_id: int, download_attachments: bool) -> None:
        resp, fetch_id = self.fetch("GET", f"{API}/message", params={"messageId": message_id})
        body, attachments = parse_message(resp.json())
        self.save("newsweb_bodies", [body], fetch_id)
        if not download_attachments:
            return
        for a in attachments:
            params = {"messageId": message_id, "attachmentId": a["attachment_id"]}
            file, file_fetch_id = self.fetch("GET", f"{API}/attachment", params=params)
            row = {
                "message_id": message_id,
                "attachment_id": a["attachment_id"],
                "name": a["name"],
                "sha256": hashlib.sha256(file.body).hexdigest(),
                "content_type": file.content_type,
                "size": len(file.body),
            }
            self.save("newsweb_attachments", [row], file_fetch_id)
