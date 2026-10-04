"""The pump.fun page: what it shows, and the downloadable log of everything measured.

The page updates itself (``static/live.js``): it polls ``pumpfun.freshness`` and, when the stamp changes,
fetches the page again and swaps the parts marked ``data-live``. The measurement and the patterns change
only when the collector runs, so they are cached between those refreshes; the portfolio is worked out
again each time, because the live quotes move it every minute.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from .. import pumpfun
from ..collectors.pumpfun import PRICE_HISTORY
from ..store import Store, utcnow
from . import charts, exports

# Periods for the account chart: key in the address, label on the button, how far back.
PERIODS: dict[str, tuple[str, timedelta | None]] = {
    "6t": ("6 t", timedelta(hours=6)), "24t": ("24 t", timedelta(hours=24)),
    "7d": ("7 d", timedelta(days=7)), "alt": ("Alt", None),
}
DEFAULT_PERIOD = "24t"
CARDS = 12  # open positions shown as cards before "Vis alle"
CLOSED_ROWS = 20
TAPE_MAX = 40  # newest open positions on the ticker tape
TAPE_FILL = 12  # the tape repeats its items to at least this many, so a short list still fills the width
FRESH = timedelta(minutes=10)  # the newest data is at most this old: the page says it is live
NEW = timedelta(minutes=10)  # a position bought this recently is marked new
FIRST_HOUR = timedelta(hours=1)  # an open position's chart shows at least its first hour
MOVERS = 3  # best and worst open positions beside the account chart
SPARK_SLICES = 24  # about 50 points per position chart: plenty at card size, and the page stays light
NEON = ("#22d3ee", "#14f195", "#ff4fd8", "#b78bff")  # the avatars' gradients; decoration, not data


class Cache:
    """Values that only change when the collector runs, kept while the stamp of the last run is the same.

    The collector is the only writer of ``pf_tokens``, so the stamp covers every change to what is cached.
    """

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, name: str, key: str, compute: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._items.get(name)
        if hit and hit[0] == key:
            return hit[1]
        value = compute()
        with self._lock:
            self._items[name] = (key, value)
        return value


def context(store: Store, periode: str, cache: Cache, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    version, updated = pumpfun.freshness(store)
    run_key = version.rsplit(".", 1)[0]  # the run part of the stamp; the quotes do not change what is cached
    fresh = updated is not None and now - updated < FRESH
    periode = periode if periode in PERIODS else DEFAULT_PERIOD

    books = pumpfun.accounts(store)  # the same buys: sold at +100 % (the main account), after 24 hours, trailing
    p = books["take_profit"]
    closed = p["closed"][:CLOSED_ROWS]
    paths = pumpfun.histories(store, [*p["open"], *closed], now, slices=SPARK_SLICES)
    for position in p["open"]:
        _decorate(position, paths.get(position["mint"], []), now, closed=False)
    for position in closed:
        _decorate(position, paths.get(position["mint"], []), now, closed=True)

    back = PERIODS[periode][1]
    history = pumpfun.equity_history(store, since=now - back if back else None)
    live = fresh and p["started_at"] is not None and (not history or history[-1][0] < now)
    points = [*history, (now, p["equity"])] if live else history
    tape = p["open"][:TAPE_MAX]
    ranked = sorted(p["open"], key=lambda o: o["result"], reverse=True)
    movers = {"best": ranked[:MOVERS], "worst": ranked[::-1][:MOVERS]} if len(ranked) > MOVERS else None
    return {
        "version": version, "updated": updated, "fresh": fresh, "now": now,
        "paper": p, "hold": books["hold"], "trailing": books["trailing"], "closed": closed, "cards": CARDS,
        "movers": movers, "trail": pumpfun.TRAIL,
        "tape": tape * math.ceil(TAPE_FILL / len(tape)) if tape else [],
        "periode": periode, "periods": PERIODS, "history": history,
        "account_chart": charts.account_chart(points, p["start"], live=live),
        "result_chart": charts.result_bars(p["bins"]),
        "r": cache.get("results", run_key, lambda: pumpfun.results(store)),
        "patterns": cache.get("patterns", run_key, lambda: pumpfun.patterns(store)),
        "fee": pumpfun.FEE, "horizons": pumpfun.HORIZONS, "price_days": PRICE_HISTORY.days,
    }


def _decorate(position: dict[str, Any], path: list[tuple[datetime, float]], now: datetime, *, closed: bool) -> None:
    mint, result = position["mint"], position["result"]
    position["side"] = "up" if result >= 0 else "down"
    position["badge"] = _badge(result, position.get("lost", False))
    opened, sale = position["opened_at"], position["opened_at"] + pumpfun.PAPER_HOLD
    until = position["closed_at"] if closed else min(max(now, opened + FIRST_HOUR), sale)
    position["chart"] = charts.sparkline(path, opened=opened, until=until, key=mint,
                                         size="mini" if closed else "card", closed=closed)
    if not closed:
        position["held"] = min(max((now - opened) / pumpfun.PAPER_HOLD, 0.0), 1.0)
        position["left"] = _left(position["opened_at"] + pumpfun.PAPER_HOLD - now)
        position["new"] = now - position["opened_at"] < NEW
        digest = hashlib.sha256(mint.encode()).digest()
        first = digest[0] % len(NEON)
        position["colors"] = (NEON[first], NEON[(first + 1 + digest[1] % (len(NEON) - 1)) % len(NEON)])
        position["initial"] = next((c for c in (position["symbol"] or position["name"] or mint) if c.isalnum()),
                                   "?").upper()


def _badge(result: float, lost: bool) -> tuple[str, str, str] | None:
    """Emoji, visible word and what it means, for the cards and the closed trades. Doubled or more is
    written as a multiple, the way crypto traders say it: 3x."""
    if lost or result <= -0.9:
        return ("💀", "rekt", "Ned 90 % eller mer")
    if result >= 1.0:
        multiple = math.floor(1 + result)
        return ("🚀", f"{multiple}x", f"Verdt {multiple} ganger innsatsen eller mer")
    if result >= 0.5:
        return ("🚀", "", "Opp over 50 %")
    return None


def _left(remaining: timedelta) -> str:
    minutes = math.ceil(remaining.total_seconds() / 60)
    if minutes <= 0:
        return "ved neste kjøring"
    return f"om {minutes // 60} t" if minutes >= 60 else f"om {minutes} min"


# The downloadable log

def _feature(name: str) -> Callable[[dict[str, Any]], Any]:
    return lambda r: (r["features"] or {}).get(name)


def _sol(column: str) -> Callable[[dict[str, Any]], float | None]:
    """Prices as market value in SOL: every pump.fun token has a billion, so price × 1e9."""
    return lambda r: None if r[column] is None else r[column] * 1e9


def _percent(get: Callable[[dict[str, Any]], float | None]) -> Callable[[dict[str, Any]], float | None]:
    return lambda r: None if (v := get(r)) is None else v * 100


STATUS = {"new": "venter på vurdering", "tracking": "følges", "done": "ferdig", "missing": "forsvant",
          "scored": "vurdert, ikke fulgt"}
PAPER = {"open": "kjøpt, åpen", "sold": "kjøpt og solgt", "skipped": "hoppet over (kontantene var brukt opp)"}
SOCIALS = ("twitter", "telegram", "website")

# Header, value, decimals (None: written as text). Times in Norwegian time; prices as market value in SOL.
CSV_COLUMNS: tuple[tuple[str, Callable[[dict[str, Any]], Any], int | None], ...] = (
    ("Token (adresse)", lambda r: r["mint"], None),
    ("Navn", lambda r: r["name"], None),
    ("Symbol", lambda r: r["symbol"], None),
    ("Utsteder", lambda r: r["creator"], None),
    ("Lansert (norsk tid)", lambda r: r["created_at"], None),
    ("Vurdert (norsk tid)", lambda r: r["scored_at"], None),
    ("Filterversjon", lambda r: r["screen_version"], None),
    ("Status", lambda r: STATUS.get(r["status"], r["status"]), None),
    ("Handel ved vurderingen", lambda r: r["active"], None),
    ("Alle sjekker gjort", lambda r: r["complete"], None),
    ("Bestod filteret", lambda r: r["passed"], None),
    ("Varseltegn", lambda r: "; ".join(pumpfun.WARNINGS.get(w, w) for w in r["warnings"] or []), None),
    ("Markedsverdi ved vurdering (SOL)", _sol("price_t"), 3),
    ("Markedsverdi etter 1 t (SOL)", _sol("price_1h"), 3),
    ("Markedsverdi etter 6 t (SOL)", _sol("price_6h"), 3),
    ("Markedsverdi etter 24 t (SOL)", _sol("price_24h"), 3),
    ("Topp etter vurdering (SOL)", _sol("peak_after"), 3),
    ("Bunn etter vurdering (SOL)", _sol("low_after"), 3),
    ("Topp før vurdering (SOL)", _sol("peak_before"), 3),
    ("Markedsverdi i forhold til start", _feature("launch_multiple"), 3),
    ("Kollapset etter 1 t", lambda r: r["collapsed_1h"], None),
    ("Kollapset etter 6 t", lambda r: r["collapsed_6h"], None),
    ("Kollapset etter 24 t", lambda r: r["collapsed_24h"], None),
    ("Ingen handel etter 1 t", lambda r: r["quiet_1h"], None),
    ("Ingen handel etter 6 t", lambda r: r["quiet_6h"], None),
    ("Ingen handel etter 24 t", lambda r: r["quiet_24h"], None),
    ("Avkastning etter 1 t (%)", _percent(lambda r: r["return_1h"]), 2),
    ("Avkastning etter 6 t (%)", _percent(lambda r: r["return_6h"]), 2),
    ("Avkastning etter 24 t (%)", _percent(lambda r: r["return_24h"]), 2),
    ("Markedsverdi ved vurdering (USD)", _feature("market_cap_usd"), 0),
    ("Handler siste 5 min", _feature("trades_5m"), 0),
    ("Kjøp siste time", _feature("buys_1h"), 0),
    ("Salg siste time", _feature("sells_1h"), 0),
    ("Volum siste time (USD)", _feature("volume_1h_usd"), 0),
    ("Handelsplass", _feature("dex"), None),
    ("Graduert ved vurderingen", _feature("graduated"), None),
    ("Andre lanseringer fra utstederen", _feature("serial"), 0),
    ("Utstederens transaksjoner (av siste 200)", _feature("creator_tx"), 0),
    ("Hele historikken lest", _feature("creator_history_complete"), None),
    ("Utstederens lommebok, alder (timer)", _feature("creator_age_h"), 2),
    ("Utstederens transaksjoner per time", _feature("creator_tx_per_h"), 2),
    ("Ti største eieres andel (%)", _percent(_feature("top10_share")), 2),
    ("Nettside eller sosiale medier", lambda r: any((r["launch"] or {}).get(k) for k in SOCIALS), None),
    ("Fiktiv handel", lambda r: PAPER.get(r["paper"], ""), None),
    ("Fiktivt resultat (%)", _percent(lambda r: r["paper_result"]), 2),
    ("Halvert (stup), tidspunkt", lambda r: r["cliff_at"], None),
    ("Kurs ved stup (SOL)", _sol("cliff_price"), 3),
    ("Verdt det dobbelte (+100 %), tidspunkt", lambda r: r["profit_at"], None),
    ("Kurs ved +100 % (SOL)", _sol("profit_price"), 3),
    ("Fiktiv handel, hovedkontoen (selger ved +100 %)", lambda r: PAPER.get(r["paper_take_profit"], ""), None),
    ("Fiktivt resultat, hovedkontoen (%)", _percent(lambda r: r["paper_take_profit_result"]), 2),
    ("Høyeste kurs (SOL)", _sol("trail_peak"), 3),
    ("Falt 25 % fra toppen, tidspunkt", lambda r: r["trail_at"], None),
    ("Kurs da (SOL)", _sol("trail_price"), 3),
    ("Fiktiv handel, følger toppen", lambda r: PAPER.get(r["paper_trailing"], ""), None),
    ("Fiktivt resultat, følger toppen (%)", _percent(lambda r: r["paper_trailing_result"]), 2),
    ("Lenker ved lanseringen", lambda r: pumpfun._links(r["launch"]), 0),
    ("Betalt DexScreener-profil", _feature("dex_profile"), None),
    ("Betalte DexScreener-boost", _feature("boosts"), 0),
)


def export_csv(store: Store) -> Iterator[str]:
    """Semicolons, decimal commas and a byte-order mark, so Excel with Norwegian settings opens it directly."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([header for header, _, _ in CSV_COLUMNS])
    yield "﻿" + exports.drain(out)
    for i, r in enumerate(pumpfun.log_rows(store), 1):
        writer.writerow([exports.cell(get(r), digits) for _, get, digits in CSV_COLUMNS])
        if i % 500 == 0:
            yield exports.drain(out)
    yield exports.drain(out)


def export_json(store: Store, now: datetime | None = None) -> Iterator[str]:
    """Everything, for analysis in code: the tokens, the fake trades, the account value and the price paths."""
    books = pumpfun.accounts(store)
    yield '{"meta": ' + exports.to_json(_meta(books["take_profit"], now)) + ',\n"tokens": ['
    yield from exports.items(exports.to_json(row) for row in pumpfun.log_rows(store))
    yield '],\n"trades": ' + exports.to_json({name: _trades(a) for name, a in books.items()})
    e = store.table("pf_equity")
    yield ',\n"equity": ['
    yield from exports.items(exports.to_json(dict(r)) for r in store.query(select(e).order_by(e.c.at)))
    prices = store.table("pf_prices")
    yield '],\n"price_history": ['
    with store.engine.connect() as conn:
        rows = conn.execution_options(yield_per=2000).execute(select(prices).order_by(prices.c.mint, prices.c.at))
        yield from exports.items(exports.to_json(dict(r)) for r in rows.mappings())
    yield "]}\n"


def export_analysis_json(store: Store, now: datetime | None = None) -> Iterator[str]:
    """Small enough to send on: every measured token (tradable and fully checked) without pump.fun's launch
    fields, how many tokens there are of every other kind, the fake accounts' trades and the account value.
    About 1 MB a day; the full log is some 30 MB, nearly all of it launches that were never followed."""
    books = pumpfun.accounts(store)
    meta = {**_meta(books["take_profit"], now),
            "kind": "analysis: measured tokens only, and the price paths of this version's tokens that passed"}
    yield '{"meta": ' + exports.to_json(meta) + ',\n"funnel": ' + exports.to_json(pumpfun.funnel(store)) + ',\n"tokens": ['
    yield from exports.items(exports.to_json(_compact(row)) for row in pumpfun.log_rows(store, measured_only=True))
    yield '],\n"trades": ' + exports.to_json({name: _trades(a) for name, a in books.items()})
    e = store.table("pf_equity")
    yield ',\n"equity": ['
    yield from exports.items(exports.to_json(dict(r)) for r in store.query(select(e).order_by(e.c.at)))
    yield '],\n"price_paths": ' + exports.to_json(_price_paths(store)) + "}\n"


def _price_paths(store: Store) -> dict[str, list[list[float]]]:
    """Every price seen for this version's tokens that passed, checks and quotes: [seconds after scoring, price].
    Enough to try other exit rules on, at a few hundred kilobytes a day."""
    t, p = store.table("pf_tokens"), store.table("pf_prices")
    out: dict[str, list[list[float]]] = {}
    for r in store.query(select(p.c.mint, p.c.at, p.c.price, t.c.scored_at).join(t, t.c.mint == p.c.mint)
                         .where(t.c.passed.is_(True), t.c.screen_version == pumpfun.SCREEN_VERSION)
                         .order_by(p.c.mint, p.c.at)):
        seconds = (pumpfun._aware(r["at"]) - pumpfun._aware(r["scored_at"])).total_seconds()
        out.setdefault(r["mint"], []).append([round(seconds), r["price"]])
    return out


def _compact(row: dict[str, Any]) -> dict[str, Any]:
    """A token without what only identifies it on pump.fun; the links its creator added are kept as a count."""
    out = {k: v for k, v in row.items() if k not in ("launch", "discovered_at", "sampled")}
    out["links"] = pumpfun._links(row["launch"])
    return out


def _trades(p: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"mint": t["mint"], "name": t["name"], "symbol": t["symbol"], "opened_at": t["opened_at"],
             "buy_price": t["price_t"], "stake_sol": p["stake"], "closed_at": t.get("closed_at"),
             "sell_price": t.get("exit_price"), "proceeds_sol": t.get("proceeds"), "lost": t.get("lost"),
             "profit": t.get("profit"), "trail": t.get("trail"), "value_now_sol": t.get("value"),
             "result": t["result"]}
            for t in sorted((*p["open"], *p["closed"]), key=lambda t: t["opened_at"])]


def _meta(p: dict[str, Any], now: datetime | None) -> dict[str, Any]:
    return {
        "exported_at": now or utcnow(),
        "screen_version": pumpfun.SCREEN_VERSION,
        "limits": pumpfun.LIMITS,
        "warnings": pumpfun.WARNINGS,
        "fee_per_trade": pumpfun.FEE,
        "collapse_level": pumpfun.COLLAPSE_LEVEL,
        "paper": {"start_sol": p["start"], "stake_sol": p["stake"], "hold_hours": p["hold_hours"],
                  "take_profit": pumpfun.TAKE_PROFIT, "trail": pumpfun.TRAIL},
        "notes": {
            "tokens": "Every sampled launch, oldest first. Launches outside the sample are left out: they are "
                      "kept for a week only to spot creators who launch token after token.",
            "prices": "SOL per token. Every pump.fun token has a billion, so market value in SOL is price * 1e9.",
            "features": "What was seen when the token was scored, about 10 minutes after launch.",
            "return_*": "Buying at the scoring price and selling at that horizon, after pump.fun's fee on both "
                        "trades. Slippage is not included.",
            "collapsed_*": "The price at that horizon was at most 10 % of the highest price since scoring.",
            "quiet_*": "Nobody traded it from scoring until that horizon: the price never moved.",
            "screen_version": "pf1 (from 2 October 2026) counted any token with a trade in the 5 minutes before "
                              "scoring. pf2 also needs a market value at least 10 % above pump.fun's launch value "
                              "(features.launch_multiple >= 1.1), and scores every new launch. pf3 (from late on "
                              "3 October 2026) also stops tokens already at twice the launch value or more "
                              "(launch_multiple >= 2, warning 'pumped'). Only measured tokens (status tracking or "
                              "done) are followed, whether they passed or not; the rest stay 'scored'.",
            "paper": "The 24-hour account: open, sold, skipped (passed while the cash was used up) or null "
                     "(never bought).",
            "paper_take_profit": "The same for the main account (from 4 October 2026): sold once a position is "
                                 "worth twice its cost after fees, credited at exactly that line even if the price "
                                 "seen (profit_at, profit_price) was higher, otherwise after 24 hours.",
            "paper_trailing": "The same for the trailing account (from 4 October 2026): once a position is worth "
                              "twice its cost after fees, sold at the first price seen at least 25 % below its "
                              "highest since buying (trail_at, trail_price; trail_peak is the highest so far), "
                              "otherwise after 24 hours. The stup account (cliff_at, cliff_price) left the page "
                              "then: nothing pf3 buys can halve on the bonding curve, whose floor is the launch "
                              "price.",
            "trades": "Each account's buys, oldest first: take_profit (the main account), hold (24 hours) and "
                      "trailing. sell_price is the price the sale was credited at.",
            "price_paths": "Analysis export: for this version's tokens that passed, every price seen as [seconds "
                           "after scoring, price]: the checks, and the quotes of the open positions, fetched every "
                           "minute and stored when the price changed. Kept for 7 days.",
            "equity": "The main account's value after every collector run. account is null for the 24-hour "
                      "account, the main account until 4 October 2026.",
            "hype": "features.links: social links added at launch; features.dex_profile and features.boosts: paid "
                    "promotion on DexScreener when scored (recorded from 3 October 2026).",
            "price_history": "Every price seen for tokens that passed, and the open positions' quotes; the "
                             f"last {PRICE_HISTORY.days} days only.",
            "funnel": "Analysis export: how many sampled tokens there are of each kind, since only the measured "
                      "ones are listed.",
        },
    }
