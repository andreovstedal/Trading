"""Finanstilsynet's short-sale register (Norway).

    GET https://ssr.finanstilsynet.no/api/v2/instruments

Keyless JSON (verified live 2026-10-02): a list of instruments, each with
``isin``, ``issuerName`` and ``events`` of ``{date, shortPercent, shares,
activePositions[{date, shortPercent, shares, positionHolder}]}``. Only
positions of at least 0.5% are public, the register updates around 15:30 on
business days, and the API keeps just two years, so snapshot it daily.
"""

from __future__ import annotations

from typing import Any

from .base import Collector, RunSummary

URL = "https://ssr.finanstilsynet.no/api/v2/instruments"


def parse_instruments(payload: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    totals, positions = [], []
    for instrument in payload:
        isin = instrument["isin"]
        for event in instrument.get("events", []):
            day = event["date"][:10]
            totals.append({
                "isin": isin,
                "date": day,
                "issuer_name": instrument.get("issuerName"),
                "short_pct": event.get("shortPercent"),
                "short_shares": event.get("shares"),
            })
            for p in event.get("activePositions", []):
                positions.append({
                    "isin": isin,
                    "date": day,
                    "holder": p.get("positionHolder"),
                    "position_date": (p.get("date") or "")[:10] or None,
                    "short_pct": p.get("shortPercent"),
                    "short_shares": p.get("shares"),
                })
    return totals, positions


class NoShortCollector(Collector):
    source = "no-short"

    def run(self) -> RunSummary:
        resp, fetch_id = self.fetch("GET", URL)
        totals, positions = parse_instruments(resp.json())
        self.save("no_short_totals", totals, fetch_id)
        self.save("no_short_positions", positions, fetch_id)
        return self.summary
