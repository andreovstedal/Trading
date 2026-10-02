"""MFN (Modular Finance News): Swedish and other Nordic company press releases.

We read MFN's per-company feeds on feed.mfn.se, the interface MFN provides
for issuer websites (verified live 2026-10-02):

    GET https://feed.mfn.se/v1/feed/{entity_id}.json?limit=N[&lang=sv|en]
        -> {"items": [...], "next_url": "...&offset=N"}

Feeds are keyed by MFN's entity UUID, and the company page on mfn.se
(``https://mfn.se/all/a/{slug}``) embeds it as ``var entityId = "..."``.
So each slug is resolved once and cached in ``mfn_entities``.

mfn.se's robots.txt disallows ``*.json``, ``*.rss``, ``*.xml`` and ``*.atom``
URLs on mfn.se itself, so this collector never requests those; the HTML
company pages are allowed, and feed.mfn.se publishes no robots.txt.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .base import Collector, RunSummary

COMPANY_PAGE = "https://mfn.se/all/a/{slug}"
FEED_URL = "https://feed.mfn.se/v1/feed/{entity_id}.json"

_ENTITY_ID = re.compile(r'var entityId = "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"')
_LEGAL_SUFFIXES = re.compile(r"\b(ab|asa|as|oyj|abp|a/s|plc|ltd|se)\b|\(publ\)", re.IGNORECASE)


def parse_entity_id(html: str) -> str | None:
    match = _ENTITY_ID.search(html)
    return match.group(1) if match else None


def slug_candidates(name: str) -> list[str]:
    """Likely mfn.se slugs for a company name, most specific first.

    "NIBE Industrier AB" -> ["nibe-industrier-ab", "nibe-industrier"].
    """
    candidates = [_slugify(name), _slugify(_LEGAL_SUFFIXES.sub(" ", name))]
    return [c for i, c in enumerate(candidates) if c and c not in candidates[:i]]


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ø", "o").replace("æ", "ae").replace("&", " ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def parse_feed(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    items = []
    for item in payload.get("items", []):
        author = item.get("author") or {}
        props = item.get("properties") or {}
        content = item.get("content") or {}
        items.append({
            "news_id": item["news_id"],
            "group_id": item.get("group_id"),
            "entity_id": author.get("entity_id"),
            "issuer_name": author.get("name"),
            "slug": author.get("slug"),
            "isins": author.get("isins") or [],
            "leis": author.get("leis") or [],
            "tickers": author.get("tickers") or [],
            "lang": props.get("lang"),
            "type": props.get("type"),
            "tags": props.get("tags") or [],
            "scopes": props.get("scopes") or [],
            "title": content.get("title"),
            "publish_date": content.get("publish_date"),
            "url": item.get("url"),
            "html": content.get("html"),
            "attachments": content.get("attachments") or [],
        })
    return items, payload.get("next_url")


class MfnCollector(Collector):
    source = "mfn"

    def run(
        self,
        *,
        slugs: Iterable[str] = (),
        company_names: Iterable[str] = (),
        since: datetime | None = None,
        page_size: int = 50,
        max_pages: int = 5,
    ) -> RunSummary:
        entities: dict[str, str] = {}
        for slug in slugs:
            entity_id = self.resolve(slug)
            if entity_id:
                entities[entity_id] = slug
            else:
                self.warn(f"no MFN company page found for slug {slug!r}")
        for name in company_names:
            entity_id = next(filter(None, (self.resolve(s) for s in slug_candidates(name))), None)
            if entity_id:
                entities[entity_id] = name
            else:
                self.warn(f"could not match {name!r} to an MFN company page")

        for entity_id in entities:
            self._read_feed(entity_id, since=since, page_size=page_size, max_pages=max_pages)
        return self.summary

    def resolve(self, slug: str) -> str | None:
        """Entity UUID for a company slug, read from its mfn.se page once."""
        row = self.store.conn.execute(
            "SELECT entity_id FROM mfn_entities WHERE slug = ?", (slug,)
        ).fetchone()
        if row is not None:
            return row[0] or None
        resp, fetch_id = self.fetch("GET", COMPANY_PAGE.format(slug=slug), allow_status=(404,))
        entity_id = parse_entity_id(resp.body.decode("utf-8", "replace")) if resp.status == 200 else None
        # Misses are cached too (entity_id NULL) so a large name list isn't re-probed every run;
        # delete the row to retry a slug.
        self.save("mfn_entities", [{"slug": slug, "entity_id": entity_id, "name": None}], fetch_id)
        return entity_id

    def _read_feed(self, entity_id: str, *, since: datetime | None, page_size: int, max_pages: int) -> None:
        url = FEED_URL.format(entity_id=entity_id)
        params: dict[str, Any] | None = {"limit": page_size}
        for _ in range(max_pages):
            resp, fetch_id = self.fetch("GET", url, params=params)
            items, next_url = parse_feed(resp.json())
            self.save("mfn_items", items, fetch_id)
            dates = [i["publish_date"] for i in items if i["publish_date"]]
            if not dates or not next_url:
                return
            if since is not None and datetime.fromisoformat(min(dates).replace("Z", "+00:00")) < since:
                return
            url, params = next_url, None
