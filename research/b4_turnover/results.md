# B4: trading less

Pre-registered (`research/PREREGISTRATION.md`, "B4"); *italics* are exploratory. B2's book, data, costs, universe (today's Nordnet list: delisted stocks missing) and benchmark; 162 months, April 2013 to September 2026. `.venv/bin/python research/b4_turnover/b4.py --offline`.

- **current:** keep a holding while it ranks in the top 24, check every month (B2's book).
- **wide:** top 36, every month.
- **quarterly:** top 24, check in January, April, July and October only (B2's December, March, June and September month-end signals); no trades in other months.

**Check:** *current*'s 162 monthly returns, costs and turnover are identical to B2's published net book (passed).

## The bar

Net return a year (compound, as B2's "Return a year"); a rule must beat *current* in all three. Halves: April 2013–December 2019 (81 months), January 2020–September 2026 (81).

| Rule | Whole period | 2013–2019 | 2020–2026 | Beats current in all three |
|---|---|---|---|---|
| current | 14.33 % | 15.17 % | 13.49 % | – |
| wide | 15.54 % | 16.59 % | 14.51 % | yes |
| quarterly | 15.55 % | 15.87 % | 15.23 % | yes |

**Outcome:** both clear the bar. By the tie-break (higher whole-period net return) **quarterly** replaces *current* in the next stock account: 15.551 % against wide's 15.543 %, a margin of 0.008 percentage points a year.

## Difference from current

Rule's net monthly return minus *current*'s. SE = sd/√n; a year = 12 × a month.

| Rule, period | Mean a month (SE) | A year (SE) | t |
|---|---|---|---|
| wide, whole | +0.096 % (0.085 %) | +1.15 % (1.03 %) | 1.12 |
| wide, 2013–19 | +0.107 % (0.110 %) | +1.29 % (1.32 %) | 0.97 |
| wide, 2020–26 | +0.085 % (0.132 %) | +1.01 % (1.58 %) | 0.64 |
| quarterly, whole | +0.097 % (0.114 %) | +1.16 % (1.37 %) | 0.85 |
| quarterly, 2013–19 | +0.055 % (0.141 %) | +0.66 % (1.70 %) | 0.39 |
| quarterly, 2020–26 | +0.139 % (0.180 %) | +1.67 % (2.16 %) | 0.77 |

## Turnover and costs

| | current | wide | quarterly |
|---|---|---|---|
| Turnover a year, one way | 300 % | 209 % | 180 % |
| Trades a year | 74 | 52 | 45 |
| Costs a year | 3.34 % | 2.34 % | 1.95 % |
| – courtage | 0.90 % | 0.62 % | 0.54 % |
| – currency exchange | 1.03 % | 0.70 % | 0.62 % |
| – half-spread (estimate) | 1.42 % | 1.03 % | 0.79 % |
| *Months a position is held* | 3.9 | 5.5 | 6.3 |
| *Volatility* | 12.9 % | 13.5 % | 13.5 % |
| *Max drawdown* | −18.0 % | −23.4 % | −22.8 % |

## Reading

- Costs fall by 1.00 % a year (wide) and 1.39 % a year (quarterly). *Before costs, compound a year: current 18.26 %, wide 18.29 %, quarterly 17.86 %; difference from current wide +0.11 % a year (t 0.10), quarterly −0.25 % a year (t −0.18): the gross return is about kept.*
- The largest |t| of the net differences above is 1.12: none is distinguishable from zero. The bar asks for point estimates only, and the gap between wide and quarterly is far inside the noise.

*The quarterly check's other two phases (not part of the bar), net:*

| *Check months* | *Whole* | *2013–19* | *2020–26* | *Vs current a year (t)* | *Costs* |
|---|---|---|---|---|---|
| *Feb/May/Aug/Nov* | 14.86 % | 15.05 % | 14.66 % | +0.54 % (0.35) | 2.14 % |
| *Mar/Jun/Sep/Dec* | 15.45 % | 17.15 % | 13.78 % | +1.04 % (0.79) | 2.19 % |

## Caveats

- The account ranks on the whole score (value and quality too), which B4 cannot test; its turnover will differ. The direction carries over, not the size.
- B2's caveats apply: survivorship, the half-spread is an estimate, no price impact or tax, 15 % Swedish withholding in every book.
