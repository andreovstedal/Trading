# B3: crypto, trade or hold

As pre-registered (`research/PREREGISTRATION.md`), run by `b3.py`: 31.25 % BTC and ETH, 12.5 % XRP, ADA and SOL; 20 % band; Firi's 0.7 % fee plus the account's spreads; 22 % tax on each year's net realised gain (FIFO), settled 1 January; both books sold at the end. Yahoo daily USD closes to 7 October 2026; Bitcoin 2010–18 from Coin Metrics. Without tax, the replay matches `crypto.account` to 1e-15 (`crosscheck.py`).

**No rule clears the bar: as pre-registered, buy and hold becomes the main crypto account, the 200-day rule stays beside it as the comparison, and the pump.fun part stays in both.**

## The bar

Net return a year after costs and tax, %, as *refund*/*carry*: a year's net loss refunded at 22 % in cash on 1 January (assumes other taxable income of up to 11 times the starting capital), or carried forward, any rest refunded at the end. A rule must clear in both.

| Rule | Jul 2018 | Nov 2020 | 3-yr median | BTC 2010–18 | DSR | Clears |
|---|---|---|---|---|---|---|
| *Buy and hold* | *40.3/40.2* | *51.7/51.6* | *62.3/62.3* | *296/296* | – | – |
| 50-day | 37.0/34.7 | 40.0/38.0 | 32.1/28.5 | 251/248 | 0.986 | **no** |
| 100-day | 33.8/32.9 | 34.0/33.1 | 21.5/20.4 | 267/266 | 0.982 | **no** |
| 150-day | 40.5/40.3 | 42.1/41.9 | 37.2/36.8 | 276/275 | 0.993 | **no** |
| 200-day | 37.9/37.8 | 44.6/44.6 | 41.3/41.3 | 277/275 | 0.989 | **no** |
| 250-day | 38.1/38.0 | 47.2/47.2 | 37.6/37.6 | 287/285 | 0.989 | **no** |
| Momentum | 23.3/22.5 | 27.7/26.9 | 16.4/16.3 | 275/274 | 0.939 | **no** |
| Volatility 60 % | 31.0/28.5 | 38.9/35.9 | 50.1/48.7 | – | 0.958 | **no** |
| Top 2 | 34.8/29.7 | 39.4/33.0 | 48.8/45.8 | – | 0.950 | **no** |

Failing in both readings: test 1, 8 of 8; test 2, 8 of 8; test 3, 6 of 6. The 150-day average beat holding from July 2018 by 0.2 points (refund), then lost from November 2020. Before tax, 4 of the 6 beat holding Bitcoin, after tax none: they pay tax yearly, holding once at the end. Refunds are large: top 2 got 249k on 2023-01-01, 64 % of its book; carrying losses forward, it ends at 29.7 % and 33.0 %, below its before-tax 31.2 % and 33.4 %. The DSR reaches 0.95 for 7 of 8, but only shows a Sharpe ratio above what the best of 8 skill-less trials would show (0.17 a year), not above holding's (0.90; rules 0.72–1.04).

## Before tax, from July 2018

| Rule | Return % | Worst fall % | Trades/yr | Costs/yr % | vs hold, log %/yr ±SE | Windows won after tax % |
|---|---|---|---|---|---|---|
| Buy and hold | 46.2 | −81 | 25 | 1.6 | – | – |
| 50-day | 38.7 | −62 | 59 | 16.5 | −5.5±17.3 | 25 |
| 100-day | 36.7 | −67 | 47 | 11.0 | −6.9±16.6 | 5 |
| 150-day | 46.0 | −55 | 39 | 8.5 | −0.3±16.4 | 20 |
| 200-day | 42.4 | −58 | 35 | 7.2 | −2.8±16.5 | 41 |
| 250-day | 42.5 | −64 | 34 | 6.6 | −2.6±16.0 | 34 |
| Momentum | 25.4 | −68 | 47 | 10.5 | −15.4±16.3 | 0 |
| Volatility 60 % | 32.7 | −77 | 51 | 2.4 | −9.7±6.0 | 27 |
| Top 2 | 31.2 | −84 | 28 | 15.3 | −10.8±11.9 | 25 |

Six of 8 rules cut the worst fall (−50 % to −68 % across both periods, against −81 %); volatility 60 % only to −77 %; top 2 fell further, −84 %. No difference reaches two standard errors (largest |t| 1.6, a loss). The 64 windows (starts 2018-07 to 2023-10; refund reading) overlap: about 2.8 independent spans.

## The README's 200-day gap

Ported to `readme_check.py`, the README's scratch script reproduces its table exactly (hold/200-day before tax: 35.4/33.8 % from 2018, 61.2/52.8 % from 2020); this engine gives 37.8/31.7 % and 61.2/51.9 %. Switching its differences one at a time (decide at 00:00 on the 1st; costs inside purchases; final sale at the bid; crypto.py's month) moves the gap −1.6 → −6.1 points from 2018 (−1.5, −1.5, +0.0, −1.5) and −8.5 → −9.2 from 2020 (−1.1, +0.7, +0.0, −0.4). B3's 2018 book also differs (SOL from 2020; XRP and ADA 12.5 %, not 18.75 %) and adds tax.

## Formulas and choices

- Net return a year = (V_end/100000)^(365.25/days)−1, V_end after the final sale and tax.
- Averages: hold while close > mean of the last N closes; momentum: close > close 84 days earlier; volatility: exposure = min(1, 0.60/σ), σ = √365·sd of the book's last 60 daily returns; top 2: equal halves by 3-month return. A coin short of history is held.
- Chosen by the analyst, not in the pre-registration: book-level σ, top 2's equal halves, settlement on 1 January, the refund reading, test 2 as median against median.
- SE = 365·sd(d)/√T, d = daily log-return difference before tax. DSR = Φ((SR−SR0)√(T−1)/√(1−γ3·SR+(γ4−1)/4·SR²)), SR0 = √V[SR]·((1−γ)Φ⁻¹(1−1/8)+γΦ⁻¹(1−1/(8e))), on daily before-tax returns from July 2018 (T = 3021).

## Limits

- Survivorship: the coins are 2026's survivors, which favours buy and hold: a coin that died (as LUNA and FTT did) would have cost holding its whole share, more with monthly top-ups, while a trend rule would have sold it. Yahoo starts ETH, XRP and ADA 9 November 2017, SOL 10 April 2020; no gaps.
- Spreads fixed at the account's first days; no market impact; USD, not NOK.

## Exploratory (not pre-registered)

Tax on 1 June, all tax at the end, or the book in NOK (refund reading): 0, 0 and 0 rules pass tests 1–2.

## After the check

Added the carry reading, which a rule must also clear (refunds had lifted top 2 above its before-tax return); trades and costs from the untaxed run (hold 25 a year, not 29); fixed the worst-fall and DSR sentences; added survivorship's direction; split the final sale from crypto.py's month, with 2020's steps; "fixed before running" (unverifiable) became "chosen by the analyst"; cut to under 900 words (pipes not counted).
