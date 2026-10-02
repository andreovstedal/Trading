"""Turning scores into whole-share positions for a given account value.

Rules from the research report: a fixed, user-set split between the
long-term sleeve, the short-term sleeve and cash; equal weights inside the
long sleeve; a minimum position size so Nordnet's minimum courtage stays a
small share of each trade (NOK 29 on the Mini class stops binding at about
NOK 19 300); and a short-term sleeve that stays on paper until its own track
record justifies real money.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .. import text
from .features import Stock
from .scoring import PARAMS, Scored

SHORT_HORIZON_DAYS = 5
MAX_SHORT_POSITIONS = 3


@dataclass
class Policy:
    account_value: float
    long_pct: float = 85.0
    short_pct: float = 10.0
    cash_pct: float = 5.0
    max_positions: int = 12
    min_position: float = 20_000.0
    short_paper_only: bool = True
    ask_only: bool = False
    countries: tuple[str, ...] = ("NO", "SE")

    def __post_init__(self) -> None:
        self.countries = tuple(self.countries)
        if self.account_value <= 0:
            raise ValueError("Kontoverdien må være positiv")
        if min(self.long_pct, self.short_pct, self.cash_pct) < 0:
            raise ValueError("Prosentandelene kan ikke være negative")
        if abs(self.long_pct + self.short_pct + self.cash_pct - 100) > 0.01:
            raise ValueError("Langsiktig, kortsiktig og kontanter må til sammen utgjøre 100 %")
        if self.max_positions < 1 or self.min_position <= 0:
            raise ValueError("Antall posisjoner og minste posisjon må være større enn null")

    @property
    def long_capital(self) -> float:
        return self.account_value * self.long_pct / 100

    @property
    def short_capital(self) -> float:
        return self.account_value * self.short_pct / 100

    @property
    def position_count(self) -> int:
        return min(self.max_positions, math.floor(self.long_capital / self.min_position))

    @property
    def target_position(self) -> float:
        return self.long_capital / self.position_count if self.position_count else self.long_capital

    def as_dict(self) -> dict:
        return asdict(self) | {"countries": list(self.countries)}


@dataclass
class Position:
    scored: Scored
    amount: float  # NOK
    shares: int
    weight: float  # share of the whole account

    @property
    def stock(self) -> Stock:
        return self.scored.stock


@dataclass
class ShortSignal:
    scored: Scored
    signal: str  # buyback_start, insider_cluster, short_increase
    direction: int  # +1 candidate to buy, -1 avoid
    description: str
    amount: float = 0.0
    shares: int = 0
    paper: bool = True

    @property
    def stock(self) -> Stock:
        return self.scored.stock


def allocate_long(scored: list[Scored], policy: Policy) -> tuple[list[Position], list[str]]:
    """Equal-weight the best-ranked eligible stocks; skip any whose share price is too high to buy."""
    notes: list[str] = []
    count = policy.position_count
    if count == 0:
        notes.append(
            f"Den langsiktige delen ({text.nok(policy.long_capital)}) er mindre enn én minste posisjon"
            f" ({text.nok(policy.min_position)}). Vurder et bredt indeksfond i stedet for enkeltaksjer."
        )
        return [], notes
    ranked = sorted((s for s in scored if s.eligible), key=lambda s: s.rank)
    target = policy.long_capital / count
    positions: list[Position] = []
    for item in ranked:
        if len(positions) == count:
            break
        price_nok = item.stock.price * item.fx
        shares = math.floor(target / price_nok)
        if shares == 0:
            continue
        amount = shares * price_nok
        positions.append(Position(item, amount, shares, amount / policy.account_value))
    if len(positions) < count:
        notes.append(f"Bare {len(positions)} aksjer besto filtrene; resten av den langsiktige delen står i kontanter.")
    if count < 5:
        notes.append(f"{count} posisjoner gir tynn spredning; hver utgjør {text.percent(1 / count, 0)} av delen.")
    return positions, notes


def short_sleeve(scored: list[Scored], policy: Policy) -> tuple[list[ShortSignal], list[str]]:
    """Event-driven candidates for the short-term sleeve, plus stocks to avoid.

    Per the research, only fresh buyback programme announcements (and, as a
    weaker confirmation, several insiders buying at once) qualify as
    candidates; a jump in disclosed short interest is an avoid flag.
    """
    notes: list[str] = []
    candidates: list[ShortSignal] = []
    avoid: list[ShortSignal] = []
    for item in scored:
        f = item.stock.features
        if f.get("short_new"):
            avoid.append(ShortSignal(item, "short_increase", -1,
                                     f"Offentliggjort shortandel økte til {text.points(f['short_pct'])}"))
        liquid = item.adv_nok is not None and item.adv_nok >= PARAMS["adv_multiple"] * policy.min_position
        if not liquid or not item.stock.price or f.get("short_new"):
            continue
        if f.get("buyback_start"):
            candidates.append(ShortSignal(item, "buyback_start", 1, "Nytt tilbakekjøpsprogram annonsert"))
        elif f.get("insider_recent_buyers", 0) >= 2:
            candidates.append(ShortSignal(item, "insider_cluster", 1,
                                          f"{f['insider_recent_buyers']} innsidere kjøpte de siste dagene"))

    # Buyback starts first (stronger evidence), then the long-term score as a tie-breaker.
    candidates.sort(key=lambda c: (c.signal != "buyback_start", -(c.scored.score or 0)))
    slots = min(MAX_SHORT_POSITIONS, math.floor(policy.short_capital / policy.min_position))
    if slots == 0 and policy.short_capital > 0:
        notes.append("Den kortsiktige delen er mindre enn én minste posisjon, så signalene vises bare for oppfølging.")
    for signal in candidates[:slots]:
        price_nok = signal.stock.price * signal.scored.fx
        signal.shares = math.floor(policy.short_capital / slots / price_nok)
        signal.amount = signal.shares * price_nok
        signal.paper = policy.short_paper_only
    if policy.short_paper_only and policy.short_capital > 0:
        notes.append("Kun på papir: handlene loggføres for å bygge historikk, og pengene står i kontanter.")
    if not candidates:
        notes.append("Ingen ferske hendelsessignaler akkurat nå.")
    return candidates + avoid, notes
