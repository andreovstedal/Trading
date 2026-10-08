"""The raw inputs of B1: NewsWeb lists, FI's insider register, the ticker maps and Yahoo's daily bars."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from b1_fetch import Cache, fi_range, newsweb_range, nordnet_list, yahoo_chart, yahoo_search

from nordic_signals.collectors.base import NORDIC_TZ
from nordic_signals.collectors.yahoo import parse_chart, yahoo_symbol

# Fixed so that a second run asks for exactly the same files.
END = date(2026, 10, 7)  # the last day of events
NEWSWEB_OWN_SHARES_FROM = date(2017, 2, 15)  # category 1007 starts here
NEWSWEB_INSIDER_FROM = date(2005, 1, 1)  # 1102; before 2013-03 only for the labelled pre-index check
FI_FROM = date(2016, 7, 1)  # the register starts on 2016-07-03
YAHOO_P1 = int(datetime(2004, 6, 1, tzinfo=timezone.utc).timestamp())
YAHOO_P2 = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
OSEBX, OMXSB, SEKNOK = "OSEBX.OL", "^OMXSBGI", "SEKNOK=X"


def newsweb(cache: Cache, warnings: list[str]) -> dict[int, list[dict]]:
    return {
        1007: newsweb_range(cache, 1007, NEWSWEB_OWN_SHARES_FROM, END, warnings),
        1102: newsweb_range(cache, 1102, NEWSWEB_INSIDER_FROM, END, warnings),
    }


def fi(cache: Cache, warnings: list[str]) -> list[dict]:
    return fi_range(cache, FI_FROM, END, warnings)


def nordnet(cache: Cache) -> dict[str, list[dict]]:
    return {c: nordnet_list(cache, c) for c in ("NO", "SE")}


def map_se_isins(cache: Cache, wanted: dict[str, str], nordnet_se: list[dict]) -> dict[str, tuple[str, str]]:
    """ISIN -> (Yahoo symbol, how it was found) for the Swedish shares in ``wanted`` (ISIN -> FI instrument name):
    Nordnet's list of today's shares first, then Yahoo's search by ISIN, then by the exact instrument name."""
    by_isin = {r["isin"]: r for r in nordnet_se if r.get("isin") and r.get("symbol")}
    out: dict[str, tuple[str, str]] = {}
    for isin, name in sorted(wanted.items()):
        if isin in by_isin:
            out[isin] = (yahoo_symbol(by_isin[isin]["symbol"], "SE"), "nordnet")
            continue
        quotes = [q for q in yahoo_search(cache, isin) if str(q.get("symbol", "")).endswith(".ST")
                  and q.get("quoteType") == "EQUITY"]
        if quotes:
            out[isin] = (quotes[0]["symbol"], "yahoo-isin")
            continue
        if name:
            norm = _norm(name)
            quotes = [q for q in yahoo_search(cache, name) if str(q.get("symbol", "")).endswith(".ST")
                      and q.get("quoteType") == "EQUITY" and _norm(q.get("shortname") or "") == norm]
            if quotes:
                out[isin] = (quotes[0]["symbol"], "yahoo-name")
    return out


def _norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


_SUFFIXES = {"asa", "as", "ab", "publ", "ltd", "limited", "plc", "inc", "sa", "se", "nv", "a", "s", "the", "bv",
             "corp", "corporation", "co"}


def _name_key(text: str) -> tuple[str, ...]:
    words = "".join(c.lower() if c.isalnum() else " " for c in text or "").split()
    return tuple(w for w in words if w not in _SUFFIXES)


def map_no_signs(cache: Cache, signs: dict[str, str], nordnet_no: list[dict]) -> dict[str, tuple[str, str]]:
    """NewsWeb issuer sign -> (Yahoo symbol, how it was found). The sign is the issuer's code, usually today's
    ticker; when Yahoo has no ``<SIGN>.OL``, the issuer's name is looked up in Nordnet's list of today's Oslo
    shares, then in Yahoo's search, accepting only an Oslo share whose name matches word for word (without
    ASA/AS/Ltd and the like)."""
    by_name: dict[tuple, str] = {}
    for r in nordnet_no:
        if r.get("symbol"):
            for n in (r.get("issuer_name"), r.get("name"), r.get("long_name")):
                if n:
                    by_name.setdefault(_name_key(n), r["symbol"])
    out: dict[str, tuple[str, str]] = {}
    for sign, issuer in sorted(signs.items()):
        direct = f"{sign.strip().replace(' ', '-')}.OL"
        if load_bars(cache, direct) is not None:
            out[sign] = (direct, "issuer-sign")
            continue
        key = _name_key(issuer)
        if not key:
            continue
        if key in by_name:
            symbol = yahoo_symbol(by_name[key], "NO")
            if load_bars(cache, symbol) is not None:
                out[sign] = (symbol, "nordnet-name")
                continue
        quotes = [q for q in yahoo_search(cache, issuer) if str(q.get("symbol", "")).endswith(".OL")
                  and q.get("quoteType") == "EQUITY"
                  and key in (_name_key(q.get("longname") or ""), _name_key(q.get("shortname") or ""))]
        if quotes and load_bars(cache, quotes[0]["symbol"]) is not None:
            out[sign] = (quotes[0]["symbol"], "yahoo-name")
    return out


class Bars:
    """One symbol's daily bars, by Oslo/Stockholm local date."""

    def __init__(self, symbol: str, bars: list[dict], meta: dict):
        self.symbol = symbol
        self.meta = meta
        rows = []
        for b in bars:
            day = datetime.fromtimestamp(b["ts"], tz=NORDIC_TZ).date()
            rows.append((day, b["open"], b["high"], b["low"], b["close"], b["adjclose"] or b["close"],
                         b["volume"]))
        rows.sort()
        dedup: dict[date, tuple] = {}
        for r in rows:
            dedup[r[0]] = r  # Yahoo sometimes repeats the latest day; keep the last
        self.rows = list(dedup.values())
        self.days = [r[0] for r in self.rows]
        self.index = {d: i for i, d in enumerate(self.days)}


def load_bars(cache: Cache, symbol: str) -> Bars | None:
    memo = cache.__dict__.setdefault("bars_memo", {})
    if symbol not in memo:
        memo[symbol] = _load_bars(cache, symbol)
    return memo[symbol]


def _load_bars(cache: Cache, symbol: str) -> Bars | None:
    payload = yahoo_chart(cache, symbol, YAHOO_P1, YAHOO_P2)
    if payload is None:
        return None
    try:
        bars, _, _ = parse_chart(payload)
    except ValueError:
        return None
    if not bars:
        return None
    meta = payload["chart"]["result"][0].get("meta", {})
    return Bars(symbol, bars, {k: meta.get(k) for k in ("longName", "shortName", "currency", "exchangeName",
                                                        "instrumentType", "firstTradeDate")})


def prefetch(cache_dir: Path) -> None:
    cache = Cache(cache_dir)
    warnings: list[str] = []
    lists = newsweb(cache, warnings)
    print({k: len(v) for k, v in lists.items()}, "requests", cache.requests, flush=True)
    rows = fi(cache, warnings)
    print("fi rows", len(rows), "requests", cache.requests, flush=True)
    nn = nordnet(cache)
    print({k: len(v) for k, v in nn.items()}, "requests", cache.requests, flush=True)
    for s in (OSEBX, OMXSB, SEKNOK):
        load_bars(cache, s)
    print("warnings", json.dumps(warnings), flush=True)
    cache.close()


if __name__ == "__main__":
    import sys

    prefetch(Path(sys.argv[1]))
