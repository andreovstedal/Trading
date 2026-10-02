"""Nordnet stock list: the tradable universe plus a daily observation per stock.

The public Nordnet website loads its stock lists from an unauthenticated JSON
endpoint (verified live 2026-10-02; the ``client-id: NEXT`` header is required):

    GET https://www.nordnet.no/api/2/instrument_search/query/stocklist
        ?apply_filters=exchange_country%3DNO&limit=100&offset=0

Each row has ISIN, symbol and segment (e.g. "Nasdaq Stockholm Large Cap",
"Euronext Oslo"), delayed price, bid/ask/spread and turnover, key ratios, the
next report and dividend dates, and the number of Nordnet customers who own
the stock (``statistical_info.number_of_owners``, updated daily; identical on
nordnet.no and nordnet.se). Sorting by ``number_of_owners`` is rejected with
HTTP 400, so sort locally.

This is an unofficial endpoint. robots.txt does not disallow ``/api/``, but
Nordnet's customer terms may restrict automated collection: poll it at most
once a day and never redistribute the data.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .base import Collector, RunSummary, ms_to_iso, ms_to_local_date

URL = "https://www.nordnet.no/api/2/instrument_search/query/stocklist"
HEADERS = {"client-id": "NEXT", "Accept": "application/json"}


def parse_stocklist(payload: dict[str, Any], observed_at: datetime | str) -> tuple[list[dict], list[dict]]:
    instruments, observations = [], []
    for r in payload.get("results", []):
        info = r.get("instrument_info") or {}
        price = r.get("price_info") or {}
        market = r.get("market_info") or {}
        exchange = r.get("exchange_info") or {}
        ratios = r.get("key_ratios_info") or {}
        company = r.get("company_info") or {}
        stats = r.get("statistical_info") or {}
        returns = r.get("historical_returns_info") or {}
        nnx = r.get("nnx_info") or {}
        instrument_id = info.get("instrument_id")
        if instrument_id is None:
            continue

        instruments.append({
            "instrument_id": instrument_id,
            "isin": info.get("isin"),
            "symbol": info.get("symbol"),
            "name": info.get("name"),
            "long_name": info.get("long_name"),
            "issuer_id": info.get("issuer_id"),
            "issuer_name": info.get("issuer_name"),
            "instrument_type": info.get("instrument_type"),
            "currency": info.get("currency"),
            "exchange_country": exchange.get("exchange_country"),
            "exchanges": exchange.get("exchanges") or [],
            "market_id": market.get("market_id"),
            "identifier": market.get("identifier"),
            "is_tradable": info.get("is_tradable"),
            "is_shortable": info.get("is_shortable"),
            "display_slug": nnx.get("display_slug"),
        })
        observations.append({
            "instrument_id": instrument_id,
            "observed_at": observed_at,
            "tick_at": ms_to_iso(price.get("tick_timestamp")),
            "realtime": price.get("realtime"),
            "last": _price(price, "last"),
            "open": _price(price, "open"),
            "high": _price(price, "high"),
            "low": _price(price, "low"),
            "close": _price(price, "close"),
            "bid": _price(price, "bid"),
            "ask": _price(price, "ask"),
            "spread_pct": price.get("spread_pct"),
            "diff_pct": price.get("diff_pct"),
            "turnover": price.get("turnover"),
            "turnover_volume": price.get("turnover_volume"),
            "market_cap": company.get("market_cap"),
            "pe": ratios.get("pe"),
            "pb": ratios.get("pb"),
            "ps": ratios.get("ps"),
            "eps": ratios.get("eps"),
            "dividend_per_share": ratios.get("dividend_per_share"),
            "dividend_yield": ratios.get("dividend_yield"),
            "number_of_owners": stats.get("number_of_owners"),
            "statistics_at": ms_to_iso(stats.get("statistics_timestamp")),
            "report_date": ms_to_local_date(company.get("report_date")),
            "report_type": company.get("report_type"),
            "ex_date": ms_to_local_date(company.get("excluding_date")),
            "dividend_date": ms_to_local_date(company.get("dividend_date")),
            "dividend_amount": company.get("dividend_amount"),
            "dividend_currency": company.get("dividend_currency"),
            "yield_1w": returns.get("yield_1w"),
            "yield_1m": returns.get("yield_1m"),
            "yield_3m": returns.get("yield_3m"),
            "yield_ytd": returns.get("yield_ytd"),
            "yield_1y": returns.get("yield_1y"),
        })
    return instruments, observations


def _price(price: dict[str, Any], key: str) -> float | None:
    value = price.get(key)
    return value.get("price") if isinstance(value, dict) else value


class NordnetCollector(Collector):
    source = "nordnet"

    def run(self, *, countries: Iterable[str] = ("NO", "SE"), page_size: int = 100) -> RunSummary:
        for country in countries:
            offset, total = 0, None
            while total is None or offset < total:
                params = {
                    "apply_filters": f"exchange_country={country}",
                    "limit": page_size,
                    "offset": offset,
                }
                resp, fetch_id = self.fetch("GET", URL, params=params, headers=HEADERS)
                payload = resp.json()
                total = payload.get("total_hits", 0)
                instruments, observations = parse_stocklist(payload, resp.fetched_at)
                self.save("instruments", instruments, fetch_id)
                self.save("nordnet_observations", observations, fetch_id)
                if not payload.get("results"):
                    break
                offset += page_size
        return self.summary
