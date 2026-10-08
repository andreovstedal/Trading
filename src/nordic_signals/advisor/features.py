"""Point-in-time features for every stock in the Nordnet universe.

Every query filters on ``first_seen_at <= asof``, so a recommendation can be
rebuilt later from exactly the data the app had when it was made.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, select

from ..collectors.base import NORDIC_TZ
from ..collectors.yahoo import yahoo_symbol
from ..store import Store

# Look-back windows.
OBSERVATION_MAX_AGE = timedelta(days=5)  # older Nordnet snapshots are too stale to price from
INSIDER_WINDOW = timedelta(days=90)
EVENT_WINDOW = timedelta(days=4)  # "fresh" events for the short-term sleeve
SHORT_CHANGE_WINDOW = timedelta(days=28)
OWNERS_CHANGE_WINDOW = timedelta(days=28)

# NewsWeb category ids.
NEWSWEB_INSIDER = 1102
NEWSWEB_OWN_SHARES = 1007

_BUY_WORDS = re.compile(r"\b(purchase[sd]?|bought|buys?|acquire[sd]?|kjøp(?:t|er|e)?|ervervet|tegnet|subscribed)\b",
                        re.IGNORECASE)
_SELL_WORDS = re.compile(r"\b(sold|sells?|sale|disposed?|solgt|selger|salg|avhendet)\b", re.IGNORECASE)
_BUYBACK = r"buy[- ]?backs?|repurchase|tilbakekjøp|återköp"
_BUYBACK_WORDS = re.compile(rf"{_BUYBACK}|egne aksjer|own shares", re.IGNORECASE)
# A new programme: a word for starting or deciding one near a word for the buyback, either way round.
_START = (r"launch|initiat|commenc|\bstart|\bnew\b|\bnytt?\b|announc|resol|decid|decision|approv|iverksett|"
          r"igangsett|vedt|beslut|inled")
_BUYBACK_START = re.compile(
    rf"(?:{_START}).{{0,60}}(?:{_BUYBACK})|(?:{_BUYBACK}).{{0,60}}(?:{_START})|\bto (?:repurchase|buy[- ]?back)",
    re.IGNORECASE,
)
# What is not a new programme: the weekly reports on one already running, its end, buybacks for employees' share
# schemes, a general meeting's authorisation, flagging and corrections of earlier notices.
_NOT_A_START = re.compile(
    r"transa[ck]tion|transaksjon|status|week|\buke\b|vecka|update|result|notification of trades|rapport|complet|"
    r"avslut|genomfört|gjennomført|fullført|\bclosed?\b|\bends?\b|\bended\b|tranche|transje|employee|ansatte|"
    r"aksjeprogram|incentive|authori[sz]|fullmakt|bemyndig|threshold|flagg|correction|rättelse|korreksjon|rettelse",
    re.IGNORECASE,
)


@dataclass
class Stock:
    instrument_id: int
    issuer_id: int | None
    isin: str | None
    symbol: str
    name: str
    country: str
    segments: list[str]
    instrument_type: str | None
    currency: str | None
    observed_at: datetime
    price: float | None
    features: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)  # recent events, for reasons and the stock page

    @property
    def is_regulated_market(self) -> bool:
        """Nordnet marks MTF listings (First North, Spotlight, NGM, Euronext Growth) as ESHMTF."""
        return self.instrument_type == "ESH"


def build_features(store: Store, asof: datetime, countries: tuple[str, ...] = ("NO", "SE")) -> list[Stock]:
    stocks = _load_universe(store, asof, countries)
    by_id = {s.instrument_id: s for s in stocks}
    _add_history(store, by_id, asof)
    _add_yahoo_history(store, stocks, asof)
    _add_insider_se(store, stocks, asof)
    _add_newsweb(store, stocks, asof)
    _add_mfn_buybacks(store, stocks, asof)
    _add_shorts(store, stocks, asof)
    return stocks


def _load_universe(store: Store, asof: datetime, countries: tuple[str, ...]) -> list[Stock]:
    o, i = store.table("nordnet_observations"), store.table("instruments")
    latest = (
        select(o.c.instrument_id, func.max(o.c.observed_at).label("observed_at"))
        .where(o.c.first_seen_at <= asof, o.c.observed_at >= asof - OBSERVATION_MAX_AGE)
        .group_by(o.c.instrument_id)
        .subquery()
    )
    rows = store.query(
        select(o, i.c.isin, i.c.symbol, i.c.name, i.c.exchange_country, i.c.exchanges,
               i.c.instrument_type, i.c.currency, i.c.issuer_id)
        .join(latest, and_(o.c.instrument_id == latest.c.instrument_id, o.c.observed_at == latest.c.observed_at))
        .join(i, i.c.instrument_id == o.c.instrument_id)
        .where(i.c.exchange_country.in_(countries), i.c.instrument_type.in_(("ESH", "ESHMTF")))
    )
    stocks = []
    for r in rows:
        # Between Nordnet's morning reset (about 06:30 for Oslo) and the first trade, "last" and "turnover" are 0
        # and "close" holds the previous close, which is then the latest real price.
        traded = bool(r["last"] and r["last"] > 0)
        price = r["last"] if traded else r["close"]
        f: dict[str, Any] = {
            "price": price,
            "market_cap": r["market_cap"],
            "turnover": r["turnover"] if traded else None,
            "pe": r["pe"],
            "pb": r["pb"],
            "eps": r["eps"],
            "dividend_yield": (r["dividend_yield"] or 0.0) / 100,
            "ret_1m": _pct(r["yield_1m"]),
            "ret_3m": _pct(r["yield_3m"]),
            "ret_1y": _pct(r["yield_1y"]),
            "owners": r["number_of_owners"],
            "report_date": r["report_date"].isoformat() if r["report_date"] else None,
            "report_type": r["report_type"],
            "ex_date": r["ex_date"].isoformat() if r["ex_date"] else None,
        }
        pe, pb = f["pe"], f["pb"]
        f["earnings_yield"] = 1 / pe if pe and pe > 0 else None
        f["book_to_price"] = 1 / pb if pb and pb > 0 else None
        f["roe"] = pb / pe if pe and pe > 0 and pb and pb > 0 else None
        if f["ret_1y"] is not None and f["ret_1m"] is not None and f["ret_1m"] > -1:
            f["momentum"] = (1 + f["ret_1y"]) / (1 + f["ret_1m"]) - 1  # 12-1 month momentum
        else:
            f["momentum"] = None
        stocks.append(Stock(
            instrument_id=r["instrument_id"], issuer_id=r["issuer_id"], isin=r["isin"] or None,
            symbol=r["symbol"], name=r["name"],
            country=r["exchange_country"], segments=list(r["exchanges"] or []),
            instrument_type=r["instrument_type"], currency=r["currency"],
            observed_at=_utc(r["observed_at"]), price=price, features=f,
        ))
    return stocks


def _add_history(store: Store, by_id: dict[int, Stock], asof: datetime) -> None:
    """Median daily turnover over recent snapshots, and the change in Nordnet owner counts."""
    o = store.table("nordnet_observations")
    rows = store.query(
        select(o.c.instrument_id, o.c.observed_at, o.c.tick_at, o.c.last, o.c.turnover, o.c.number_of_owners)
        .where(o.c.first_seen_at <= asof, o.c.observed_at >= asof - timedelta(days=45),
               o.c.instrument_id.in_(list(by_id)))
        .order_by(o.c.observed_at)
    )
    turnover: dict[int, dict] = defaultdict(dict)
    owners: dict[int, list] = defaultdict(list)
    for r in rows:
        if r["turnover"] and r["last"]:
            day = trading_day(r["tick_at"], r["observed_at"])
            turnover[r["instrument_id"]][day] = r["turnover"]  # last snapshot of each trading day wins
        if r["number_of_owners"] is not None:
            owners[r["instrument_id"]].append((_utc(r["observed_at"]), r["number_of_owners"]))
    for instrument_id, stock in by_id.items():
        daily = list(turnover.get(instrument_id, {}).values())[-20:]
        stock.features["adv"] = statistics.median(daily) if daily else stock.features["turnover"]
        stock.features["adv_days"] = len(daily)
        past = [n for t, n in owners.get(instrument_id, []) if t <= asof - OWNERS_CHANGE_WINDOW + timedelta(days=3)]
        now = stock.features["owners"]
        stock.features["owners_change"] = (now / past[-1] - 1) if past and past[-1] and now else None


def _add_yahoo_history(store: Store, stocks: list[Stock], asof: datetime) -> None:
    """Annualised volatility over the last ~60 sessions from Yahoo bars, and turnover where Nordnet has none yet."""
    p = store.table("price_bars")
    symbols = {yahoo_symbol(s.symbol, s.country): s for s in stocks if s.symbol}
    rows = store.query(
        select(p.c.symbol, p.c.ts, p.c.adjclose, p.c.close, p.c.volume)
        .where(p.c.interval == "1d", p.c.first_seen_at <= asof, p.c.ts_utc >= asof - timedelta(days=100),
               p.c.ts_utc <= asof, p.c.symbol.in_(list(symbols)))
        .order_by(p.c.symbol, p.c.ts)
    )
    closes: dict[str, list[float]] = defaultdict(list)
    traded: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        value = r["adjclose"] or r["close"]
        if value:
            closes[r["symbol"]].append(value)
        if r["close"] and r["volume"]:
            traded[r["symbol"]].append(r["close"] * r["volume"])
    for symbol, stock in symbols.items():
        series = closes.get(symbol, [])[-61:]
        rets = [math.log(b / a) for a, b in zip(series, series[1:], strict=False) if a > 0 and b > 0]
        stock.features["volatility"] = statistics.stdev(rets) * math.sqrt(252) if len(rets) >= 40 else None
        # A new database whose first Nordnet snapshot came before the open has no turnover history at all.
        if not stock.features.get("adv_days") and traded.get(symbol):
            stock.features["adv"] = statistics.median(traded[symbol][-20:])


def _add_insider_se(store: Store, stocks: list[Stock], asof: datetime) -> None:
    """Open-market insider buys and sells from Finansinspektionen's register (Swedish shares)."""
    t = store.table("se_insider_trades")
    by_isin = {s.isin: s for s in stocks if s.isin and s.country == "SE"}
    rows = store.query(
        select(t.c.isin, t.c.pdmr, t.c.position, t.c.nature, t.c.volume, t.c.price, t.c.currency,
               t.c.published_at, t.c.transaction_date)
        .where(t.c.first_seen_at <= asof, t.c.published_at >= asof - INSIDER_WINDOW, t.c.published_at <= asof,
               t.c.status == "Aktuell", t.c.instrument_type == "Aktie", t.c.nature.in_(("Förvärv", "Avyttring")),
               t.c.linked_to_share_program.is_not(True), t.c.isin.in_(list(by_isin)))
    )
    for stock in by_isin.values():
        stock.features.update(insider_buy_value=0.0, insider_sell_value=0.0, insider_buyers=0, insider_sellers=0)
    buyers: dict[str, set] = defaultdict(set)
    sellers: dict[str, set] = defaultdict(set)
    recent_buyers: dict[str, set] = defaultdict(set)
    for r in rows:
        stock = by_isin[r["isin"]]
        value = (r["volume"] or 0) * (r["price"] or 0)
        published = _utc(r["published_at"])
        if r["nature"] == "Förvärv":
            stock.features["insider_buy_value"] += value
            buyers[r["isin"]].add(r["pdmr"])
            if published >= asof - EVENT_WINDOW:
                recent_buyers[r["isin"]].add(r["pdmr"])
                stock.events.append({"type": "insider_buy", "at": published.isoformat(), "value": value,
                                     "currency": r["currency"], "role": r["position"]})
        else:
            stock.features["insider_sell_value"] += value
            sellers[r["isin"]].add(r["pdmr"])
    for isin, stock in by_isin.items():
        f = stock.features
        f["insider_buyers"], f["insider_sellers"] = len(buyers[isin]), len(sellers[isin])
        f["insider_recent_buyers"] = len(recent_buyers[isin])
        net = f["insider_buy_value"] - f["insider_sell_value"]
        f["insider_net_bps"] = net / f["market_cap"] * 1e4 if f.get("market_cap") else None


def _add_newsweb(store: Store, stocks: list[Stock], asof: datetime) -> None:
    """Norwegian insider notices (direction read from the text) and buyback reports from NewsWeb."""
    m, b = store.table("newsweb_messages"), store.table("newsweb_bodies")
    by_symbol = {s.symbol: s for s in stocks if s.country == "NO"}
    rows = store.query(
        select(m.c.message_id, m.c.issuer_sign, m.c.title, m.c.category_ids, m.c.published_at, b.c.body)
        .outerjoin(b, b.c.message_id == m.c.message_id)
        .where(m.c.first_seen_at <= asof, m.c.published_at >= asof - INSIDER_WINDOW, m.c.published_at <= asof,
               m.c.issuer_sign.in_(list(by_symbol)))
    )
    for stock in by_symbol.values():
        stock.features.update(insider_buy_notices=0, insider_sell_notices=0, buyback_notices=0, buyback_start=False)
    for r in rows:
        stock = by_symbol[r["issuer_sign"]]
        categories = set(r["category_ids"] or [])
        published = _utc(r["published_at"])
        fresh = published >= asof - EVENT_WINDOW
        text = f"{r['title'] or ''} {r['body'] or ''}"
        if NEWSWEB_INSIDER in categories:
            direction = insider_direction(text)
            if direction > 0:
                stock.features["insider_buy_notices"] += 1
            elif direction < 0:
                stock.features["insider_sell_notices"] += 1
            if fresh:
                stock.events.append({"type": "insider_notice", "at": published.isoformat(), "direction": direction,
                                     "title": r["title"], "message_id": r["message_id"]})
        if NEWSWEB_OWN_SHARES in categories and _BUYBACK_WORDS.search(text):
            stock.features["buyback_notices"] += 1
            if fresh and buyback_start(r["title"] or ""):
                stock.features["buyback_start"] = True
                stock.events.append({"type": "buyback_start", "at": published.isoformat(), "title": r["title"],
                                     "message_id": r["message_id"]})


def buyback_start(title: str) -> bool:
    """Whether a buyback notice's title announces a new programme, rather than reporting on one already running.

    Most notices are the weekly reports of programmes under way ("transactions in week 40", "status etter uke
    40"), which say nothing new; the research's announcement effect is about the start."""
    return bool(_BUYBACK_START.search(title)) and not _NOT_A_START.search(title)


def insider_direction(text: str) -> int:
    """+1 for a purchase, -1 for a sale, 0 when the notice text is ambiguous or silent."""
    buy, sell = bool(_BUY_WORDS.search(text)), bool(_SELL_WORDS.search(text))
    return (buy and not sell) - (sell and not buy)


def _add_mfn_buybacks(store: Store, stocks: list[Stock], asof: datetime) -> None:
    """Swedish buyback reports and programme starts from MFN press releases."""
    t = store.table("mfn_items")
    by_isin = {s.isin: s for s in stocks if s.isin and s.country == "SE"}
    rows = store.query(
        select(t.c.news_id, t.c.isins, t.c.tags, t.c.title, t.c.publish_date, t.c.lang)
        .where(t.c.first_seen_at <= asof, t.c.publish_date >= asof - INSIDER_WINDOW, t.c.publish_date <= asof)
    )
    for stock in by_isin.values():
        stock.features.setdefault("buyback_notices", 0)
        stock.features.setdefault("buyback_start", False)
    seen_titles: set[tuple[str, str]] = set()
    for r in rows:
        tags = r["tags"] or []
        if not any(tag.startswith("sub:ca:shares:repurchase") for tag in tags):
            continue
        for isin in r["isins"] or []:
            stock = by_isin.get(isin)
            if stock is None:
                continue
            published = _utc(r["publish_date"])
            day_key = (isin, published.date().isoformat())
            if day_key in seen_titles:  # Swedish and English versions of the same release
                continue
            seen_titles.add(day_key)
            stock.features["buyback_notices"] += 1
            if published >= asof - EVENT_WINDOW and buyback_start(r["title"] or ""):
                stock.features["buyback_start"] = True
                stock.events.append({"type": "buyback_start", "at": published.isoformat(), "title": r["title"]})


def _add_shorts(store: Store, stocks: list[Stock], asof: datetime) -> None:
    """Disclosed short interest: Finanstilsynet (Norway) and FI's aggregate file (Sweden).

    Both sources list states that hold until the next change, so a stock's
    short interest is its latest state. A jump only counts as new when the
    source's history reaches back before the comparison window; otherwise
    "no earlier data" would look like "rose from zero".
    """
    by_isin = {s.isin: s for s in stocks if s.isin}
    for stock in stocks:
        stock.features.update(short_pct=0.0, short_change=None, short_new=False)

    nt = store.table("no_short_totals")
    rows = store.query(
        select(nt.c.isin, nt.c.date, nt.c.short_pct)
        .where(nt.c.first_seen_at <= asof, nt.c.isin.in_(list(by_isin))).order_by(nt.c.date)
    )
    coverage = store.scalar(select(func.min(nt.c.date)).where(nt.c.first_seen_at <= asof))
    _apply_short_history(by_isin, [(r["isin"], r["date"], r["short_pct"]) for r in rows], asof, coverage)

    # FI's file only lists issuers currently at 0.1% or more; one missing from the latest download has dropped out.
    agg = store.table("se_short_aggregate")
    lei_to_isin = _lei_to_isin(store, asof)
    rows = store.query(
        select(agg.c.lei, agg.c.position_date, agg.c.total_pct, agg.c.last_seen_at)
        .where(agg.c.first_seen_at <= asof).order_by(agg.c.position_date)
    )
    first_seen = store.scalar(select(func.min(agg.c.first_seen_at)).where(agg.c.first_seen_at <= asof))
    latest_download = max((_utc(r["last_seen_at"]) for r in rows), default=None)
    cutoff = latest_download - timedelta(hours=12) if latest_download else None
    current = {r["lei"] for r in rows if cutoff and _utc(r["last_seen_at"]) >= cutoff}
    series = [(lei_to_isin[r["lei"]], r["position_date"], r["total_pct"] if r["lei"] in current else None)
              for r in rows if r["lei"] in lei_to_isin]
    coverage = _utc(first_seen).astimezone(NORDIC_TZ).date() if first_seen else None
    _apply_short_history(by_isin, series, asof, coverage)


def _apply_short_history(by_isin: dict[str, Stock], series: list[tuple], asof: datetime, coverage: Any) -> None:
    """``series`` holds (isin, effective date, percent) states in date order; None means no longer listed."""
    window_start = (asof - EVENT_WINDOW).date()
    history: dict[str, list[tuple]] = defaultdict(list)
    for isin, day, pct in series:
        if isin in by_isin and day <= asof.date():
            history[isin].append((day, pct or 0.0))
    for isin, points in history.items():
        f = by_isin[isin].features
        latest_day, latest = points[-1]
        f["short_pct"] = latest
        month_ago = _state_before(points, (asof - SHORT_CHANGE_WINDOW).date(), coverage)
        f["short_change"] = latest - month_ago if month_ago is not None else None
        prior = _state_before(points, window_start, coverage)
        if latest_day >= window_start and prior is not None and latest - prior >= 0.5:
            f["short_new"] = True
            by_isin[isin].events.append({"type": "short_increase", "at": latest_day.isoformat(),
                                         "from": prior, "to": latest})


def _state_before(points: list[tuple], day: Any, coverage: Any) -> float | None:
    """The percentage in force just before ``day``; 0 if the source covered that time and the stock wasn't listed."""
    earlier = [pct for d, pct in points if d < day]
    if earlier:
        return earlier[-1]
    return 0.0 if coverage is not None and coverage < day else None


def _lei_to_isin(store: Store, asof: datetime) -> dict[str, str]:
    """Map issuer LEIs to share ISINs using the insider register and MFN, which both carry both codes."""
    mapping: dict[str, str] = {}
    t = store.table("se_insider_trades")
    for r in store.query(
        select(t.c.lei, t.c.isin).distinct()
        .where(t.c.first_seen_at <= asof, t.c.instrument_type == "Aktie", t.c.isin != "", t.c.lei != "")
    ):
        mapping.setdefault(r["lei"], r["isin"])
    m = store.table("mfn_items")
    for r in store.query(select(m.c.leis, m.c.isins).where(m.c.first_seen_at <= asof)):
        leis, isins = r["leis"] or [], r["isins"] or []
        if len(leis) == 1 and isins:
            mapping.setdefault(leis[0], isins[0])
    return mapping


def _pct(value: float | None) -> float | None:
    return value / 100 if value is not None else None


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def trading_day(tick_at: datetime | None, observed_at: datetime) -> date:
    """The local date a Nordnet price or turnover belongs to: that of the last trade, not of the snapshot.

    Early-morning snapshots still show yesterday's last price and turnover.
    """
    return _utc(tick_at or observed_at).astimezone(NORDIC_TZ).date()
