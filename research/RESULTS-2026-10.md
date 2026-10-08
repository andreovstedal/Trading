# Backtest results, October 2026

Three backtests were pre-registered on 8 October 2026 (`research/PREREGISTRATION.md`), then built, checked against the raw data by a second reviewer, corrected and re-run; details are in each folder's `results.md`. *Exploratory* marks anything not pre-registered: a lead to test, not a result. "±" is one standard error; t is the estimate divided by it, and t ≥ 2 is the usual bar.

**In short:** no short-term signal makes money after costs; the stock score's price part matched the index after costs, momentum pointing the right way; no crypto trading rule beat holding after costs and tax, so the crypto account switches to buy and hold, pump.fun kept.

## 1. Headlines against the bars

| Backtest | Bar | Result | Verdict |
|---|---|---|---|
| B1: new buyback programme, Oslo, 5-day trade | net excess > 0, t ≥ 2 | +0.23 % ± 0.35 % a trade (t 0.6; 220 trades, 2017–26) | not met |
| B1: Swedish insider cluster | same | −0.84 % ± 0.16 % (t −5.4; 4,615, 2016–26) | not met: loses |
| B1: Oslo insider purchase (comparison) | same | −0.63 % ± 0.25 % (t −2.5; ≈ 5,900, 2013–26) | not met: loses |
| B2: momentum + low volatility, top 12 | none (calibration) | +0.7 % ± 2.7 % a year over the index, after costs (t 0.26) | – |
| B3: 8 crypto trading rules | beat holding in 3 tests after tax; DSR ≥ 0.95 | 0 of 8 (DSR passes for 7; returns fail) | not met |

**B1.** Net excess = return from the opening after the evening decision to the 5th day's close, minus the round trip (0.30 % Oslo, 0.80 % Stockholm) and the index; errors clustered by month. Before costs the Swedish cluster matched the index (−0.04 %): costs are the whole loss. The price moves before the account can buy: previous close to buying opening +0.48 % (t 2.4) for buybacks, +0.30 % (t 5.0) for Swedish clusters, +0.54 % (t 5.4) for Oslo insider buys.

**B2** (162 months to September 2026). The book made 14.3 % a year after costs, the indexes in its country mix 13.6 %; before costs 18.3 % (excess +4.1 %, t 1.5). Costs 3.3 % a year: courtage 0.9, currency exchange 1.0, half-spread 1.4 (an estimate, 0.9–1.9). Turnover 25 % a month. Momentum's rank correlation with next month's return: 0.027 (t 2.4) pooled; Oslo t 2.4, Stockholm t 1.7. Worst fall −18 % against −13 %.

**B3** (net % a year after 22 % tax; losses refunded / carried forward):

| | From Jul 2018 | From Nov 2020 | Median 3 years | Bitcoin 2010–18 |
|---|---|---|---|---|
| Buy and hold | 40.3 / 40.2 | 51.7 / 51.6 | 62.3 / 62.3 | 296 / 296 |
| 200-day average | 37.9 / 37.8 | 44.6 / 44.6 | 41.3 / 41.3 | 277 / 275 |
| 150-day average | 40.5 / 40.3 | 42.1 / 41.9 | 37.2 / 36.8 | 276 / 275 |

Only the 150-day rule beat holding anywhere (0.2 points from 2018), and it lost from 2020. Before tax, 200-day minus holding from 2018 is −2.8 ± 16.5 points a year: the data cannot tell them apart, and no rule's gap reaches two standard errors. The trend rules cut the worst fall (200-day −58 % against −81 %) but the 200-day rule cost 7.2 % a year against 1.6 %, and the rules pay tax yearly where holding pays once.

## 2. The crypto decision

The pre-registered rule: "If none does, buy and hold becomes the main crypto account and the 200-day rule stays beside it as the comparison. The pump.fun part stays in both." None did, so:

- **Main Krypto account: buy and hold.** 25 % Bitcoin, 25 % Ether, 10 % each XRP, Cardano and Solana, 20 % pump.fun; monthly rebalance with the 20 % band.
- **Comparison: the 200-day rule**, same coins, start and pump.fun part.
- **pump.fun stays at 20 % in both, for fun, as you asked.** B3 left it out of both books, so nothing here speaks for or against it.

Can trading the coins extract value? Not on this evidence; the rules' one benefit is a smaller worst fall (holding means sitting through about −80 %). The decision does not depend on the post-check requirement to clear with losses carried forward too: with losses refunded alone, no rule clears either.

For the accounts: today's main account (200-day rule) and its yardstick (buy and hold) swap roles. Both started on 6 October 2026 with the same money, so no restart is needed; the labels and the README's "Why the 200-day average" paragraph must change. This report changes nothing in `src/` or the README.

## 3. What to change (exploratory unless stated)

Pre-registered reading: no signal's 5-day trade earns money, so the short-term part stays on paper (its default). The rest are suggestions to pre-register and test first.

**Short-term part**

1. *Drop the Swedish insider cluster as a buy signal:* −0.84 % a trade after costs, about 210 NOK on each 25,000 NOK Lekepenger trade.
2. *Buyback starts leave no edge by evening:* +1.78 % (t 6.4) comes between the last close before the notice and the buying opening. 11 of 19 hand-checked "new programmes" only supply shares to employee schemes.
3. *The default 90/10 split leaves 10 % in cash* while the short-term part is on paper; 100/0 for real money would invest it. Lekepenger can keep its short-term part as a forward test; expect it to trail.

**Stock score**

4. *Keep momentum and low volatility.* Momentum's direction is positive (pre-registered); low volatility's rank correlation was larger, 0.059 (t 5.0).
5. *The score mostly avoids losers.* Score fifths, best first: 18.6, 17.0, 17.5, 14.3 and 5.1 % a year before costs (missing failures flatter the last). The top fifth barely beats the next two, so holding longer (keep while in the top 36, or rebalance quarterly) could cut costs at little loss. Untested.
6. *Costs are the lever:* 3.3 of the 4.1 points of gross excess. Currency exchange (0.25 % each way on Swedish shares, 1.0 % a year) is worth checking against Nordnet's options for holding SEK.
7. *The overlays get no support at longer horizons* (after the round trip; Newey–West t), at 20 and 250 days: Swedish clusters −1.0 % (t −3.1), −2.1 % (t −0.5); buyback starts +0.2 % (t 0.3), +4.0 % (t 0.9); Oslo insider buys −0.6 % (t −1.3), +7.7 % (t 1.4). The score's 90-day overlays were not tested directly; nothing supports a positive Swedish insider tilt. *Post hoc:* Oslo insider notices about share schemes, allotments or issues did worse (−1.18 %, t −2.4) than the rest (−0.46 %, t −1.6); worth testing without them.

## 4. Caveats

**Survivorship.** B1 events without Yahoo prices (delisted, listed abroad, late series) are missing, not zero: 16 % of 261 buyback starts, 23 % of 6,042 Swedish clusters, 28 % of ≈ 8,250 Oslo insider buys. B2 uses today's 1,260 Nordnet shares; delisted ones are missing, including at least 7 takeover targets the book would often have held, so the bias against the index has no known direction. B3's coins are 2026's survivors, which favours holding: a dead coin (LUNA, FTT) costs holding its whole share; a trend rule sells it.

**Sample sizes.** B1: 87, 124 and 163 months. B2: an edge needs about 5.4 % a year to show; a true edge below 7.5 % is missed more than one time in five. B3: 64 overlapping three-year windows, about 2.8 independent spans.

**Not done or approximated.**
- B1: Swedish buyback starts; the account's slot limits. Oslo insider row: all 1,358 title-stated notices plus a weighted random 1,500 of 22,497 others.
- B2: only the score's price part (value, quality, overlays untested); no tax, price impact or waiting orders; trades a day before the paper account; half-spread estimated.
- B3: spreads from the account's first days; USD, not NOK (an exploratory NOK run agrees); no market impact; pump.fun untested; five analyst choices, listed in its `results.md`.
- Repairs after the checks (Yahoo's Oslo ex-dates a day late 2021 to mid-2024, a split-adjusted 5 NOK floor, a frozen series) each move B2's excess by at most 0.6 points.

## 5. How to re-run

From `/home/user/Trading`:

```sh
.venv/bin/python research/b1_events/b1_events.py --offline   # about 45 s
.venv/bin/python research/b2_prices/b2.py --offline          # about 4 min; --no-attribution is faster
.venv/bin/python research/b3_crypto/b3.py --offline          # about 40 s
/root/.local/bin/ruff check research/
```

Each writes `results.json` and `results.md` to its folder (or `--out DIR`); `--cache DIR` sets the cache, by default `/tmp/claude-0/-home-user-Trading/0a31d734-cb89-583d-8276-7cd774b8c998/scratchpad/data/<folder>/`, outside the repo. Without `--offline`, missing files download at about one request a second: about 9,300 files for B1 (hours), 1,700 for B2, 7 for B3. On 8 October 2026 all three re-ran from the cache with no requests and reproduced their results byte for byte.
