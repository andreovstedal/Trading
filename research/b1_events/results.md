# B1: event study of the short-term signals

Pre-registered in `research/PREREGISTRATION.md`; made by `b1_events.py`; other parts marked exploratory or post hoc.

**Verdict: no signal clears the bar (mean 5-day net excess > 0 with t ≥ 2).** The Stockholm insider cluster and the Oslo insider purchase lose money after costs (t ≤ −2).

## Method

Seen at the first 20:45 UTC decision after publication (Swedish cluster: the first evening with purchases by ≥ 2 distinct insiders published in the last 4 days and not yet revised); bought at the next opening; sold at the 5th market day's close, the buying day first. gross = adjclose[exit] / (open[entry] · adjclose[entry]/close[entry]) − 1; net excess = gross − round trip (+0.30 % Oslo, +0.80 % Stockholm, `paper.costs`) − index (OSEBX GI, OMXSBGI), same opening to close. A stock's notices within 4 days are one event. m = Σw·x/Σw; t = m/SE, SE² = G/(G−1)·Σ_g(Σ_{i∈g} w_i(x_i−m))²/(Σw)², g = entry month; w = 1 except below.

Oslo insider notices are read as the code reads them, title and body: all 1358 whose title states a purchase (census), and a random 1500 of the 22497 with a silent title (seed 1102). An event found only through the sample has w = (N/n)/m = 15.00/m, m = its silent-title purchase notices (Hansen–Hurwitz; events built from the bodies of neighbouring notices). n: rows ≈ estimated events. Read with its body, a title-stated purchase is dropped 263 times: 187 turn ambiguous on a sell word (often shares sold to employees, or boilerplate such as Yara's "salg til mer enn 150 land"), 76 name own or treasury shares.

## Headline: the 5-day trade

| Signal | n | months | mean net excess | SE | t | median | > 0 | gross | index |
|---|---|---|---|---|---|---|---|---|---|
| New buyback programme, Oslo | 220 | 87 | +0.23 % | +0.35 % | 0.64 | -0.06 % | 49 % | +0.86 % | +0.33 % |
| Insider cluster, Stockholm | 4615 | 124 | -0.84 % | +0.16 % | -5.39 | -1.18 % | 39 % | +0.12 % | +0.16 % |
| ↳ comparison: FI's status today (hindsight) | 4476 | 124 | -0.88 % | +0.17 % | -5.18 | -1.20 % | 38 % | +0.08 % | +0.16 % |
| Insider purchase notice, Oslo | 1177 ≈ 5924 | 163 | -0.63 % | +0.25 % | -2.47 | -0.95 % | 40 % | -0.14 % | +0.19 % |
| ↳ subset: purchase stated in the title | 726 | 153 | -0.33 % | +0.29 % | -1.13 | -0.56 % | 45 % | +0.24 % | +0.26 % |

The title subset, the Oslo row before the check, is 12 % of the estimated events.

Cells: mean % (t by month / Newey–West t; n). Gap: previous close to entry opening.

| Signal | gap | gap − index | 5 days | 20 days | 60 days | 250 days |
|---|---|---|---|---|---|---|
| Buyback start | +0.48 (2.4; 220) | +0.46 (2.3; 220) | +0.23 (0.6; 220) | +0.16 (0.3 / 0.3; 216) | +0.42 (0.4 / 0.4; 206) | +4.05 (1.2 / 0.9; 175) |
| SE cluster | +0.30 (5.0; 4620) | +0.30 (6.3; 4620) | -0.84 (-5.4; 4615) | -1.04 (-3.2 / -3.1; 4577) | -0.78 (-1.1 / -0.9; 4494) | -2.12 (-1.1 / -0.5; 3996) |
| NO insider buy | +0.54 (5.4; 1178 ≈ 5939) | +0.53 (5.2; 1178 ≈ 5939) | -0.63 (-2.5; 1177 ≈ 5924) | -0.63 (-1.3 / -1.3; 1170 ≈ 5875) | +0.19 (0.2 / 0.2; 1156 ≈ 5778) | +7.73 (1.8 / 1.4; 1087 ≈ 5367) |

Beyond 5 days holdings overlap across months, inflating the month-clustered t; the Newey–West t treats month sums as a series (2, 4, 13 lags).

## By year of entry (5-day net excess, % (t))

| Year | Buyback start | SE cluster | NO insider buy |
|---|---|---|---|
| 2013 | – | – | -0.11 (-0.1) |
| 2014 | – | – | -1.11 (-0.9) |
| 2015 | – | – | -0.69 (-1.0) |
| 2016 | – | -1.39 (-2.3) | +0.51 (0.8) |
| 2017 | -0.91 (-0.6) | -1.30 (-4.5) | -0.25 (-0.3) |
| 2018 | +1.30 (1.1) | -0.45 (-1.3) | -1.32 (-1.8) |
| 2019 | +1.04 (0.8) | -0.40 (-0.9) | -0.84 (-1.0) |
| 2020 | -0.82 (-0.5) | -0.86 (-0.9) | +0.35 (0.3) |
| 2021 | -0.17 (-0.2) | -0.94 (-2.6) | -1.39 (-1.9) |
| 2022 | +1.50 (1.0) | -1.31 (-3.6) | -0.08 (-0.1) |
| 2023 | -1.34 (-1.5) | -0.91 (-2.2) | -0.87 (-0.9) |
| 2024 | +1.50 (1.1) | -0.44 (-1.0) | +0.14 (0.2) |
| 2025 | -0.34 (-0.6) | -0.46 (-1.3) | -1.22 (-2.0) |
| 2026 | +0.09 (0.2) | -1.18 (-2.0) | -1.78 (-1.3) |

## What happens (buyback / SE cluster / NO insider)

- **The move comes before the account can buy** (exploratory; gross, last close before publication to entry opening): +1.78 (6.4; 220) / +1.09 (8.4; 4588) / +0.93 (3.6; 1178 ≈ 5939). After entry, gross minus index is +0.53 % / -0.04 % / -0.33 %.
- **Robust** (exploratory): winsorized 1/99 % +0.20 (0.6) / -0.94 (-7.0) / -0.63 (-2.5); Newey–West t (1 lag) 0.6 / -5.3 / -2.7; liquid stocks (≥ 1 MNOK a day) +0.11 (0.3; 158) / -0.93 (-5.2; 2855) / -0.75 (-2.5; 702 ≈ 3428); without events while the stock is held +0.24 (0.7) / -0.77 (-4.9) / -0.57 (-2.2).
- **Oslo strata:** title-stated events -0.02 (-0.1; 590), sample-only -0.70 (-2.5; 587 ≈ 5334).
- **Post hoc splits:** buybacks for employee/incentive schemes +0.48 (1.1; 146), others -0.27 (-0.4; 74); Oslo insider notices naming a scheme, allotment, share issue, offer or exercise -1.18 (-2.4; 322 ≈ 1396), others -0.46 (-1.6; 855 ≈ 4528).
- **Exploratory sets:** buyback starts in 1102 titles, 2013-03 to 2017-02, -1.25 (-1.2; 9); Oslo title purchases 2005 to 2013-02 against equal-weighted event-free stocks -0.16 (-0.5; 278).

## Hand check: 20 random buyback starts

19 of 20 announce a new programme (the miss: SMCRT, a termination). 11 of the 19 only supply shares to employee or board schemes, often NOK 1–20m (the post hoc keywords agree on 16).

## Coverage and survivorship

| Signal | events | no Yahoo series (delisted, merged) | listed abroad / foreign ISIN | Yahoo starts after event | lapsed | with 5-day result |
|---|---|---|---|---|---|---|
| Buyback start | 261 | 32 (12 %) | 9 (3 %) | 0 (0 %) | 0 | 220 |
| SE cluster | 6042 | 1225 (20 %) | 36 (1 %) | 147 (2 %) | 13 | 4615 |
| NO insider buy | ≈ 8251 | 2080 (25 %) | 196 (2 %) | 22 (0 %) | 13 | 5924 |
| SE cluster, today's status | 5824 | 1157 (20 %) | 30 (1 %) | 141 (2 %) | 13 | 4476 |
| NO title subset | 918 | 178 (19 %) | 6 (1 %) | 5 (1 %) | 3 | 726 |
| Buyback start in 1102 | 11 | 1 (9 %) | 1 (9 %) | 0 (0 %) | 0 | 9 |
| NO title buy pre-2013 | 530 | 231 (44 %) | 4 (1 %) | 1 (0 %) | 16 | 278 |

- Missing events are missing, not zero. Oslo issuers listed abroad: BOL.ST, DANSKE.CO, DFDS.CO, DSX, FLNG, G2M.ST, NORION.ST, RCL, SBLK, SDRL, SPEONE.ST. Yahoo series starting after a venue or ticker change: BESQAB.ST (from 2021-06-16), NEOBO.ST (from 2023-02-13), SDS.ST (from 2024-01-15).
- FI typed no instrument before 2018-09-18: 9958 untyped purchases count by an ISIN typed 'Aktie' elsewhere or on Nordnet's list, 627 by 190 ISINs whose rows mostly name shares; 818 dropped (rights, options, bonds, malformed ISINs).
- 51 clusters rest on one name spelt two ways (kept, as the code counts them); 76 Oslo trades lack dividends (broken adjusted close). Not tested: Swedish buyback starts (MFN), the account's slot limits.

## What changed after the check

All seven problems were real and are fixed. Before → after, 5-day net excess:

1. **Oslo insider row:** it held only title-stated purchases. Now title + body, census plus weighted sample: -0.36 % (t -1.24; n 726) → -0.63 % (t -2.47; n 1177 ≈ 5924). The subset is kept, labelled; the scheme split is post hoc.
2. **Point in time:** FI's 3602 revised and 1322 cancelled share purchases count from publication, revised ones until their correction (3211 found), the rest for the window (FI gives no time): -0.87 % (t -5.07; n 4470) → -0.84 % (t -5.39; n 4615) with all fixes; on today's status -0.88 %.
3. **Untyped ISINs:** share-like ones now enter: 52 cluster events, 8 traded, the rest counted missing.
4. **Missing data:** split into delisted, listed abroad and late Yahoo series.
5. **Calendar:** the days missing from Yahoo's index (20 Oslo, 7 Stockholm) are added from 8 large stocks, the index unchanged over them. Buyback starts, changed by this alone: +0.16 % (t 0.45; n 220) → +0.23 % (t 0.64; n 220).
6. **Overlap:** Newey–West t added beyond 5 days (Swedish cluster, 250 days: t -1.1 → -0.5).
7. **Double counting:** events merged by Yahoo symbol (10 Swedish clusters folded); events the account would skip, as it still holds the stock, are dropped under Robust.
