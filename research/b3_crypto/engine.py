"""The crypto book replayed on daily closes, the way ``nordic_signals.crypto`` replays the account, with tax.

* **When.** A decision is at 00:00 UTC on a day, on the closes of the days before it, and is carried out at the
  close of the day before (Yahoo's and Coin Metrics' crypto day ends at midnight UTC, so that close is the first
  price after the decision). The start, the first of each month and, for the weekly rules, each Monday; a Monday
  that is the first is the month's (``crypto.decisions``).
* **Prices.** A trade buys at close x (1 + spread) and sells at close x (1 - spread), each paying Firi's fee
  (``crypto.FEE``) on top: a purchase spends the money set for it, fees and spread included. The book is valued at
  the close (the middle price).
* **Rebalancing** follows ``crypto._Book.decide`` and ``_settle`` line by line, without the pump.fun part (the same
  in both books, so it stays out): the parts a rule switches trade to their target; on the first of the month every
  part outside its 20 % band goes back to target, the cash of the coins the rule does not hold counts as a part of
  its own, a shortfall is paid by the parts above target, and money left over goes to the parts below it. Rules
  whose target moves by degrees (volatility scaling) also trade at a weekly check when a coin is outside its band.
* **Tax.** 22 % of each calendar year's net realised gain (FIFO cost, as Skatteetaten requires for crypto; fees and
  spread are part of the cost and of the proceeds), settled on 1 January of the next year before that night's trades
  (``tax_month`` moves it); any shortfall in cash is sold pro rata from the coins. At the end everything is sold
  at the bid and the years not yet settled are. A year's net loss is read two ways (``losses``):

  - ``"refund"``: deducted from other income that year, so 22 % of it comes back in cash at the settlement. This
    assumes other taxable income as large as the loss, which for the top-2 rule in 2022 is 11 times the start.
  - ``"carry"``: carried forward against later years' gains, with no cash until the end; any loss still unused at
    the end is refunded then (it keeps its worth against later income).
"""

from __future__ import annotations

import bisect
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import fmean, pstdev

from nordic_signals import crypto

FEE = crypto.FEE  # Firi, 0.7 % of each trade
TOLERANCE = crypto.TOLERANCE  # the 20 % band
START = crypto.START  # 100 000
MIN_TRADE = crypto.MIN_TRADE  # smaller trades are left out
CASH = crypto.CASH
TAX = 0.22


@dataclass(frozen=True)
class Rule:
    name: str
    kind: str  # "hold", "sma", "mom", "vol", "top"
    n: int = 0  # days for "sma" and "mom"; the window of daily returns for "vol"
    target_vol: float = 0.0
    top: int = 0
    months: int = 0

    @property
    def weekly(self) -> bool:
        return self.kind in ("sma", "mom", "vol")

    @property
    def continuous(self) -> bool:
        return self.kind == "vol"


RULES = (
    Rule("50-day average", "sma", 50),
    Rule("100-day average", "sma", 100),
    Rule("150-day average", "sma", 150),
    Rule("200-day average", "sma", 200),
    Rule("250-day average", "sma", 250),
    Rule("12-week momentum", "mom", 84),
    Rule("Buy and hold at 60 % volatility", "vol", 60, target_vol=0.60),
    Rule("Top 2 by 3-month return", "top", top=2, months=3),
)
HOLD = Rule("Buy and hold", "hold")


class Series:
    """A coin's daily closes, one per day with no gaps (``data.fill``)."""

    def __init__(self, closes: dict[date, float]):
        self.days = sorted(closes)
        self.values = [closes[d] for d in self.days]
        self.first = self.days[0]
        self.index = {d: i for i, d in enumerate(self.days)}

    def upto(self, day: date) -> int:
        """How many closes there are on or before ``day``."""
        return bisect.bisect_right(self.days, day)

    def close(self, day: date) -> float:
        return self.values[self.index[day]]

    def on_or_before(self, day: date) -> float | None:
        k = self.upto(day)
        return self.values[k - 1] if k else None


def add_months(day: date, months: int) -> date:
    m = day.month - 1 + months
    return date(day.year + m // 12, m % 12 + 1, 1) if day.day == 1 else date(day.year + m // 12, m % 12 + 1, day.day)


# The rules' targets

def sma_view(s: Series, last: date, n: int) -> bool | None:
    """Above its average of the last ``n`` closes up to ``last`` (``crypto.trend``); None without n closes."""
    k = s.upto(last)
    if k < n:
        return None
    return s.values[k - 1] > fmean(s.values[k - n:k])


def mom_view(s: Series, last: date, n: int) -> bool | None:
    k = s.upto(last)
    if k < n + 1:
        return None
    return s.values[k - 1] > s.values[k - 1 - n]


def targets(rule: Rule, series: dict[str, Series], weights: dict[str, float], decided: date) -> dict[str, float]:
    """Each coin's target share of the book at a decision at 00:00 on ``decided``, on the closes before it. Coins
    that have no close yet are left out and the book's weights are scaled over the rest."""
    last = decided - timedelta(days=1)
    present = [c for c in weights if series[c].first <= last]
    total = sum(weights[c] for c in present)
    w = {c: weights[c] / total for c in present}
    if rule.kind == "hold":
        return w
    if rule.kind in ("sma", "mom"):
        view = sma_view if rule.kind == "sma" else mom_view
        out = {}
        for c in present:
            v = view(series[c], last, rule.n)
            out[c] = w[c] if v is None or v else 0.0  # a coin without enough history is held
        return out
    if rule.kind == "vol":
        exposure = vol_exposure(rule, series, w, last)
        return {c: w[c] * (exposure if series[c].upto(last) >= rule.n + 1 else 1.0) for c in present}
    if rule.kind == "top":
        back = add_months(decided, -rule.months) - timedelta(days=1)  # the close a whole number of months before
        returns, held = {}, {}
        for c in present:
            then = series[c].on_or_before(back)
            if then is None:
                held[c] = w[c]  # without enough history: held at its share
            else:
                returns[c] = series[c].close(last) / then - 1
        best = sorted(returns, key=lambda c: -returns[c])[:rule.top]
        rest = 1.0 - sum(held.values())
        out = {c: 0.0 for c in returns} | held
        for c in best:
            out[c] = rest / len(best)
        return out
    raise ValueError(rule.kind)


def vol_exposure(rule: Rule, series: dict[str, Series], w: dict[str, float], last: date) -> float:
    """min(1, target / sigma): sigma is the annualised volatility (sqrt 365) of the book's daily returns at its
    target weights over the last ``rule.n`` days, from the coins with that much history (the others are held)."""
    have = [c for c in w if series[c].upto(last) >= rule.n + 1]
    if not have:
        return 1.0
    total = sum(w[c] for c in have)
    rets = []
    for j in range(rule.n):
        day = last - timedelta(days=j)
        r = 0.0
        for c in have:
            s = series[c]
            i = s.index[day]
            r += w[c] / total * (s.values[i] / s.values[i - 1] - 1)
        rets.append(r)
    sigma = pstdev(rets) * math.sqrt(365)
    return min(1.0, rule.target_vol / sigma) if sigma > 0 else 1.0


# The book

@dataclass
class Holding:
    units: float = 0.0
    lots: deque = field(default_factory=deque)  # [units, cost] in the order bought, for FIFO

    def cost_of(self, units: float) -> float:
        cost, left = 0.0, units
        while left > 1e-15 and self.lots:
            lot = self.lots[0]
            take = min(left, lot[0])
            part = lot[1] * take / lot[0]
            cost += part
            lot[0] -= take
            lot[1] -= part
            left -= take
            if lot[0] <= 1e-15 * max(1.0, take):
                self.lots.popleft()
        return cost


@dataclass
class Result:
    rule: str
    start: date  # the first decision
    end: date  # the last close
    pre_tax: float  # value after selling everything, before the last tax
    after_tax: float
    tax_paid: float
    fees: float
    spread: float
    trades: int
    curve: list[tuple[date, float]]  # the value at each close, at the middle price, before tax
    settlements: list[dict] = field(default_factory=list)  # each settlement: day, net gain, tax (< 0 a refund), book

    @property
    def years(self) -> float:
        return (self.end - (self.start - timedelta(days=1))).days / 365.25

    def cagr(self, after_tax: bool = True) -> float:
        final = self.after_tax if after_tax else self.pre_tax
        return (final / START) ** (1 / self.years) - 1

    def max_drawdown(self) -> float:
        peak, worst = 0.0, 0.0
        for _, v in self.curve:
            peak = max(peak, v)
            worst = min(worst, v / peak - 1)
        return worst

    def daily_returns(self, since: date | None = None) -> list[float]:
        pts = [(d, v) for d, v in self.curve if since is None or d >= since - timedelta(days=1)]
        return [pts[i][1] / pts[i - 1][1] - 1 for i in range(1, len(pts))]


class Book:
    def __init__(self, rule: Rule, weights: dict[str, float], spreads: dict[str, float], *, tax: bool = True,
                 losses: str = "refund"):
        if losses not in ("refund", "carry"):
            raise ValueError(losses)
        self.rule = rule
        self.weights = weights
        self.spreads = spreads
        self.tax = tax
        self.losses = losses
        self.carried = 0.0  # a net loss carried forward (<= 0), with losses="carry"
        self.settlements: list[dict] = []
        self.cash = START
        self.coins = {c: Holding() for c in weights}
        self.fractions: dict[str, float] = {}  # the targets at the latest decision
        self.today: date | None = None  # the decision being carried out; its year is a sale's tax year
        self.gains: dict[int, float] = {}  # realised gains not yet taxed, by year
        self.tax_paid = 0.0
        self.fees = self.spread = 0.0
        self.trades = 0

    def value(self, close: dict[str, float]) -> float:
        return self.cash + sum(h.units * close[c] for c, h in self.coins.items() if h.units)

    def decide(self, decided: date, kind: str, close: dict[str, float], series: dict[str, Series]) -> None:
        fractions = targets(self.rule, series, self.weights, decided)
        wanted = {c: f > 0 for c, f in fractions.items()}
        value = self.value(close)
        parts = {c: (self.coins[c].units * close[c], fractions[c] * value, fractions[c]) for c in fractions}
        switched = {c for c in fractions if kind != "start" and wanted[c] != (self.fractions.get(c, 0.0) > 0)}
        moves: dict[str, float] = {}
        for c, (held, target, _) in parts.items():
            if kind == "start" or c in switched:
                moves[c] = target - held
            elif (kind == "month" or (kind == "week" and self.rule.continuous)) \
                    and abs(held - target) > TOLERANCE * target:
                moves[c] = target - held
        keep = self._settle(moves, parts, value, switched) if kind == "month" else 0.0
        for c, change in moves.items():  # sales first, so their money is there for the purchases
            if change < -MIN_TRADE:
                received = self._sell(c, -change, parts[c][1] == 0, close)
                if kind == "month" and c in switched:  # a coin the rule leaves pays its costs from its own cash
                    keep -= -change - received
        for c, change in moves.items():
            if change > MIN_TRADE:
                self._buy(c, min(change, self.cash - keep), close)
        self.fractions = fractions

    def _settle(self, moves: dict[str, float], parts: dict[str, tuple[float, float, float]], value: float,
                switched: set[str]) -> float:
        """``crypto._Book._settle`` without the pump.fun part."""
        share = max(0.0, value - sum(target for _, target, _ in parts.values()))
        cash = self.cash - sum(change for key, change in moves.items() if key in switched)
        keep = cash if abs(cash - share) <= TOLERANCE * share else share
        spare = self.cash - keep - sum(moves.values())
        others = {key: p for key, p in parts.items() if key not in moves and p[1] > 0}
        if keep == cash and share > 0:
            others[CASH] = (cash, share, share / value)
        if spare < -MIN_TRADE:
            gaps = {key: held - target for key, (held, target, _) in others.items() if held > target}
        elif spare > MIN_TRADE:
            gaps = {key: target - held for key, (held, target, _) in others.items() if held < target and key}
        else:
            return keep
        total = sum(gaps.values())
        moved = min(abs(spare), total)
        for key, gap in gaps.items():
            change = moved * gap / total * (1 if spare > 0 else -1)
            if key == CASH:
                keep += change
                continue
            moves[key] = change
        return keep

    def _sell(self, c: str, amount: float, everything: bool, close: dict[str, float]) -> float:
        h = self.coins[c]
        units = h.units if everything else min(amount / close[c], h.units)
        return self._sell_units(c, units, close)

    def _sell_units(self, c: str, units: float, close: dict[str, float]) -> float:
        h = self.coins[c]
        if units <= 0:
            return 0.0
        mid = close[c]
        bid = mid * (1 - self.spreads[c])
        received = units * bid * (1 - FEE)
        if units >= h.units * (1 - 1e-9):
            units = h.units
            cost = sum(lot[1] for lot in h.lots)
            h.lots.clear()
            h.units = 0.0
        else:
            cost = h.cost_of(units)
            h.units -= units
        self.cash += received
        year = self.today.year
        self.gains[year] = self.gains.get(year, 0.0) + received - cost
        self.fees += units * bid * FEE
        self.spread += units * (mid - bid)
        self.trades += 1
        return received

    def _buy(self, c: str, amount: float, close: dict[str, float]) -> None:
        spend = min(amount, self.cash)
        if spend < MIN_TRADE:
            return
        mid = close[c]
        ask = mid * (1 + self.spreads[c])
        units = spend / (ask * (1 + FEE))
        h = self.coins[c]
        h.units += units
        h.lots.append([units, spend])
        self.cash -= spend
        self.fees += units * ask * FEE
        self.spread += units * (ask - mid)
        self.trades += 1

    def due(self, before: int, *, final: bool = False, book: float = 0.0) -> float:
        """The tax on the years before ``before`` not yet settled, and settles them. A net loss is refunded at 22 %
        (``losses="refund"``) or carried forward to the next settlement (``"carry"``), and refunded only if
        ``final``."""
        years = [y for y in self.gains if y < before]
        net = sum(self.gains.pop(y) for y in years)
        if not self.tax:
            return 0.0
        taxable = net
        if self.losses == "carry":
            taxable = net + self.carried
            if taxable < 0 and not final:
                self.carried, taxable = taxable, 0.0
            else:
                self.carried = 0.0
        due = TAX * taxable
        self.tax_paid += due
        if years or final:
            self.settlements.append({"day": self.today.isoformat(), "net_gain": net, "tax": due,
                                     "carried": self.carried, "book": book})
        return due

    def pay_tax(self, close: dict[str, float]) -> None:
        """Last year's tax, from cash, selling the coins pro rata for any shortfall."""
        due = self.due(self.today.year, book=self.value(close))
        self.cash -= due
        if self.cash >= 0:
            return
        need = -self.cash
        net = {c: h.units * close[c] * (1 - self.spreads[c]) * (1 - FEE) for c, h in self.coins.items() if h.units}
        share = min(1.0, need / sum(net.values()))
        for c in net:
            self._sell_units(c, self.coins[c].units * share, close)

    def liquidate(self, close: dict[str, float]) -> float:
        for c, h in self.coins.items():
            if h.units:
                self._sell_units(c, h.units, close)
        return self.cash


def decision_kind(day: date, start: date, weekly: bool) -> str | None:
    if day == start:
        return "start"
    if day.day == 1:
        return "month"
    if weekly and day.weekday() == 0:
        return "week"
    return None


def run(rule: Rule, series: dict[str, Series], weights: dict[str, float], spreads: dict[str, float],
        start: date, end: date, *, tax: bool = True, tax_month: int = 1, losses: str = "refund") -> Result:
    """The book from the decision at 00:00 UTC on ``start`` (carried out at the close the day before) to the close
    of ``end``, when everything is sold. A year's tax is settled on the first of ``tax_month`` the year after; a net
    loss is refunded or carried forward (``losses``)."""
    book = Book(rule, weights, spreads, tax=tax, losses=losses)
    curve: list[tuple[date, float]] = []
    day = start - timedelta(days=1)  # the close a decision at 00:00 the next day is carried out at
    while day <= end:
        close = {c: s.close(day) for c, s in series.items() if c in weights and s.first <= day}
        decided = day + timedelta(days=1)
        book.today = decided
        if decided.month == tax_month and decided.day == 1 and decided > start and day < end:
            book.pay_tax(close)
        kind = decision_kind(decided, start, rule.weekly) if day < end else None
        if kind:
            book.decide(decided, kind, close, series)
        curve.append((day, book.value(close)))
        if day == end:
            pre_tax = book.liquidate(close)
            due = book.due(decided.year + 1, final=True, book=pre_tax)
            return Result(rule.name, start, end, pre_tax, pre_tax - due, book.tax_paid, book.fees, book.spread,
                          book.trades, curve, book.settlements)
        day += timedelta(days=1)
    raise ValueError("end before start")
