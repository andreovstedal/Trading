# Pre-registration: the first backtests (8 October 2026)

Written and committed before any of these backtests was run, so the results cannot shape the questions or the
bars. Anything not listed here is exploratory, and is reported as such.

## The crypto decision: trade or hold?

The question: can trading the coins extract value over holding them, on Firi, after its costs?

- **Data:** Yahoo daily closes for BTC, ETH, XRP, ADA and SOL in USD; Bitcoin alone from July 2010 to June 2018
  as a holdout (Coin Metrics or another public series), which no rule in this project was chosen on.
- **The book:** the account's coin part, 31.25 % BTC and ETH, 12.5 % XRP, ADA and SOL (the 80 % of coins scaled
  to 100 %; the pump.fun part is the same in both books and stays out), rebalanced on the first of each month
  with the 20 % band. A coin without enough history for a rule is held.
- **Costs per trade:** Firi's 0.7 % fee plus the spreads seen in the account, each way: BTC 0.33 %, ETH 1.5 %,
  XRP 1 %, ADA 0.7 %, SOL 1.1 %. Bitcoin's holdout pays Bitcoin's.
- **The rules, all checked on Mondays on Sunday's close unless stated:** the 50-, 100-, 150-, 200- and 250-day
  average; 12-week time-series momentum; buy and hold scaled to 60 % annual volatility; and every month, the 2 of
  the 5 coins with the best 3-month return. Eight rules; no others are tried for this decision.
- **Bar:** a rule is "trading that extracts value" if its net return a year beats buy and hold
  1. from July 2018 and from November 2020 (the README's two periods),
  2. in the median of all 3-year windows starting each month from July 2018,
  3. and, for the average rules and the momentum rule, on Bitcoin alone in the 2010-2018 holdout,

  each after Norwegian tax of 22 % on realised gains (both books sold at the end; losses deductible), and its
  deflated Sharpe ratio for 8 trials is at least 0.95.
- **Decision:** if one or more rules clear the bar, the one with the highest median 3-year net return becomes the
  main crypto account, and buy and hold stays as its yardstick. If none does, buy and hold becomes the main crypto
  account and the 200-day rule stays beside it as the comparison. The pump.fun part stays in both.

## B1: event study of the short-term signals

- **Events, each counted once** (the Norwegian and English versions of a notice are one event):
  new buyback programmes on Oslo (NewsWeb, own shares category, classified by `features.buyback_start`, model v3);
  Swedish insider cluster buying (Finansinspektionen's register, as `features.py` defines a cluster); and, for
  comparison, Norwegian insider purchase notices (NewsWeb).
- **Entry as the account trades:** an event published by the 20:45 UTC decision on day D is bought at the next
  opening; later ones a day later. **Exit** at the close of the 5th trading day, the buying day being the first.
  Also reported: the gap from the previous close to that opening, and 20, 60 and 250 days.
- **Costs:** a round trip of 0.30 % in Oslo and 0.80 % in Stockholm (`paper.costs`).
- **Benchmark:** the market's gross index over the same days (OSEBX GI, OMX Stockholm Benchmark GI).
- **Statistic:** mean net excess return per event, its t-statistic with standard errors clustered by calendar
  month.
- **Bar:** the 5-day trade earns money only if the mean net excess is above 0 with t of at least 2 (the effects are
  published, so this is a replication). Events whose stock Yahoo no longer has are counted and reported.

## B2: the score's price-only part

Momentum (12-1) and low volatility, as `scoring.py` computes them, in equal parts; the top 12 bought, held while
in the top 24, rebalanced monthly; Nordnet's fees and an estimated half-spread. Universe: today's Oslo and
Stockholm stocks on Nordnet's list, so delisted stocks are missing (stated with every number). Benchmark: OSEBX
GI and OMX Stockholm Benchmark GI in the book's country mix, March 2013 to September 2026. This calibrates
turnover, costs and the direction of the momentum effect; it sets no bar and moves no money.

## B4: trading less (added 9 October 2026, before it was run)

B2 found the score's price part earned about what the indexes did after costs of 3.3 % a year, with a quarter of
the book changing every month. The question: does trading less keep the return and cut the costs?

- **The book, data, costs, universe and benchmark are B2's** (`research/b2_prices/`): momentum and low volatility in
  equal parts, the top 12 in equal weights, Nordnet's fees and the estimated half-spread, March 2013 to September
  2026.
- **Three rules, and no others:**
  1. *current:* keep a holding while it ranks in the top 24, check every month (what the account does today);
  2. *wide:* keep it while it ranks in the top 36, check every month;
  3. *quarterly:* keep it while it ranks in the top 24, check in January, April, July and October only.
- **Bar:** a rule replaces *current* in the next stock account if its net return a year beats *current*'s over the
  whole period and in each half (March 2013 to December 2019, January 2020 to September 2026). If both clear it,
  the one with the higher net return over the whole period. Reported with it: turnover, costs, and the monthly
  difference from *current* with its standard error.
- **Caveat:** the account ranks on the whole score (value and quality too), which B4 cannot test, so its turnover
  will differ; the direction of the result is what carries over.
