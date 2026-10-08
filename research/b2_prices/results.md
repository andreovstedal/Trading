# B2: the score's price-only part

Pre-registered: the book vs the index blend, momentum's direction, turnover, costs; no bar. The rest, in *italics*, is exploratory. 162 months, April 2013 to September 2026. `.venv/bin/python research/b2_prices/b2.py [--cache DIR] [--offline]`.

**Survivorship:** the universe is today's Nordnet list. Missing failures flatter the EW universe and the bottom quintile; missing takeover targets (Yahoo has nothing for SWMA.ST, ICA.ST, HNA.OL, EKO.OL, OCY.OL, ADE.OL, KIND-SDB.ST), low-volatility names the book would often have held, cost it their bid premiums. Against the indices the direction is unknown.

## Method

- **Universe:** 1260 shares (293 Oslo, 967 Stockholm); Yahoo has 1230, 389 from early 2012. Eligible: quoted price ≥ 5 NOK (close × later splits), 12 months of prices, 12-month rise ≤ 300 %, volume on ≥ 10 of 20 sessions, median turnover ≥ 1.875 mill. NOK, one share class per issuer; no market-cap or P/E filter.
- **Score** (`scoring.py`): mom = (1 + r₁₂ₘ)/(1 + r₁ₘ) − 1; vol = sd(log total returns, last 61 closes) × √252; ranks within country; score = mean(rank_mom, 1 − rank_vol).
- **Book:** signal at the month-end close, trade at the next opening (the paper account: a trading day later); top 12 bought, kept while ≤ 24.
- **Costs:** `paper.costs` plus an EDGE half-spread (`bidask.edge(sign=True)`, 63 days, negatives as 0, cap 5 %).
- **Statistics:** a year = 12 × mean monthly excess; SE = 12 × sd/√n; t = mean/(sd/√n).

## Results

| | Book net | Gross | Index blend | *EW universe* |
|---|---|---|---|---|
| Return a year | 14.3 % | 18.3 % | 13.6 % | 14.1 % |
| Volatility | 12.9 % | 12.9 % | 12.5 % | 15.5 % |
| Max drawdown | −18.0 % | −16.2 % | −13.4 % | −30.2 % |

| Excess a year | Net | Fees only | Gross |
|---|---|---|---|
| vs index blend | +0.7 % (0.26) | +2.1 % (0.80) | +4.1 % (1.53) |
| *vs EW universe, book's country mix* | −1.6 % (−0.49) | −0.2 % (−0.05) | +1.8 % (0.56) |

t in brackets. Net vs index: SE 2.7 %, Newey–West (6 lags) t 0.34. All books pay 15 % Swedish withholding; indices and EW universe are untaxed.

## Turnover and costs

Turnover 25 % a month, one way. Costs 3.34 % a year: courtage 0.90 %, FX 1.03 %, half-spread 1.42 %, an estimate: 0.87 % with each bucket's mean signed estimate, 1.88 % with |estimate| (net vs index +1.2 %, +0.2 %). 37 % of estimates are negative (47–55 % over 50 mill. NOK a day): there EDGE is mostly noise. 19 % of buys and 20 % of sells fill at an opening equal to the previous close, probably Yahoo's filler (mean gaps +0.08 %, +0.10 %: no bias); EDGE without them: 0.27 % on the buys, not 0.24 %.

## Rank IC

Spearman per month and country vs the next month's return from the next opening; pooled weights by stocks.

| Theme | Oslo IC (t) | Stockholm | Pooled |
|---|---|---|---|
| Momentum 12-1 | 0.041 (2.36) | 0.022 (1.70) | 0.027 (2.37) |
| *Low volatility* | 0.052 (3.15) | 0.062 (4.90) | 0.059 (4.95) |
| *Score* | 0.068 (3.64) | 0.057 (4.44) | 0.060 (4.85) |

## Reading

- Net excess over the index blend +0.7 % a year (t 0.26): not distinguishable from zero. An observed edge needs about 5.4 % a year for t = 2; a true edge below about 7.5 % is missed more often than 1 time in 5.
- Momentum's direction is positive (59 % of months above zero); Stockholm alone: t 1.70.
- *Exploratory:* net vs index 2013–2019 +2.6 % (t 0.73), 2020–2026 −1.2 % (t −0.31). Score quintiles (EW gross, best first): 18.6 %, 17.0 %, 17.5 %, 14.3 %, 5.1 %.

## Repairs and gaps

- Yahoo's Oslo ex-dates 2021-01 to 2024-06 are a trading day late: median fall (in dividends) on Yahoo's date / the day before, 2012–20 0.72…0.93 / −0.08…0.00, 2021–23 −0.10…0.00 / 0.89…0.93. 694 moved a day earlier (after: 0.88…0.93 / −0.10…0.00); volatility uses our total return.
- 236 one-day spikes, 137 openings outside the day's range, 44 dividends over 20 % without a price drop. Not modelled: tax, price impact, waiting orders.

## Changed after the check

A review found four real errors, fixed: (1) the 5 NOK floor used the split-adjusted close, admitting 1250 stock-months quoted under 5 NOK (BNOR: 35 500 for 3.55); (2) the late ex-dates; (3) negative EDGE estimates charged as positive (costs were 3.88 %); (4) frozen series (BNOR ranked 1st, volatility 0): the volume rule drops 23 eligible stock-months. Added: book-mix EW, cost ranges; reworded survivorship, labels, power. Each w/o turns one repair off (`--undo`):

| | Before | After | w/o 1 | w/o 2 | w/o 3 |
|---|---|---|---|---|---|
| Net vs index, % | +0.7 | +0.7 | +1.3 | +1.1 | +0.2 |
| *EW universe, %* | 12.7 | 14.1 | 12.7 | 14.1 | 14.1 |
| Momentum IC, t | 3.03 | 2.37 | 3.05 | 2.35 | 2.37 |
| *Low-vol IC* | 0.073 | 0.059 | 0.073 | 0.058 | 0.059 |
| *Bottom quintile, %* | 1.4 | 5.1 | 1.0 | 5.2 | 5.1 |

Each repair moves the book's excess by at most 0.6 points, inside its SE.
