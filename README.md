# Nordic signals

A personal web app for Nordnet-tradable Norwegian and Swedish shares. It gathers insider trades, company announcements, short positions, prices and other public data. When you enter an account value, it suggests how to split the account between a long-term value sleeve and a short-term trading sleeve. It never places trades. Every input and recommendation is logged, so the formula can be scored against outcomes and improved over time.

The app speaks Norwegian (bokmål), with Norwegian number and date formats. The code, logs and this README are in English.

## Status

| Part | State |
|---|---|
| Research | Done: [`reports/Nordic stock signal data sources.md`](reports/Nordic%20stock%20signal%20data%20sources.md) covers sources, evidence per sleeve, allocation rules and the logging design. The per-topic notes are in `research_notes/` |
| Collectors | Done for the six core sources (see below), deployable on Railway with PostgreSQL |
| Features, scoring and allocation | Model v1 (`src/nordic_signals/advisor/`) |
| Prediction and outcome log | Done: every recommendation stores every stock's score and inputs; outcomes are added nightly |
| Web app | Done (`src/nordic_signals/web/`) |

## Setup

Python 3.11 or newer.

```sh
uv venv && uv pip install -e ".[dev]"
# or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## The web app

```sh
nordic-signals web                     # http://127.0.0.1:8000, or --host/--port; uses $PORT when set
```

| Page | What it does |
|---|---|
| **Råd** (`/`) | Enter the account value and the split between the long-term sleeve and the short-term sleeve (90 / 10 by default), then press **Hent data og foreslå fordeling**. With **Oppdater data først** ticked it refreshes prices, announcements and insider trades first (about 30 seconds). The result lists whole-share positions, runners-up, short-term signals, an avoid list and the reasons behind each pick, and can be downloaded as CSV (semicolons and decimal commas, for Excel with Norwegian settings). |
| **Signaler** | Fresh events from the last four days: Swedish insider purchases, Norwegian insider notices, new buyback programmes and rising short interest. |
| **Resultater** | The track record: excess return, hit rate and rank IC per model version and horizon, and per short-term signal type. |
| **Lekepenger** | A play-money Nordnet account that trades on the advice by itself, with Nordnet's fees and the exchanges' opening hours: its value day by day, holdings, orders waiting for the opening, trades and each evening's decisions, with the whole log to download. See [Lekepenger](#lekepenger-a-play-money-account). |
| **Krypto** | A play-money crypto account on Firi: 50 % in Bitcoin and Ether, 30 % in XRP, Cardano and Solana, 20 % on pump.fun, trading on a trend rule beside a buy-and-hold yardstick. It has the pump.fun page's neon look and updates itself. See [Krypto](#krypto-a-play-money-crypto-account). |
| pump.fun (`/pumpfun`) | The pump-and-dump filter's measurement, and the fake accounts that trade it: the detail page of Krypto's pump.fun part, reached from there (it has no tab of its own). See [pump.fun measurement](#pumpfun-measurement). |
| **Data** | When each source last ran, row counts, and buttons for a manual refresh and the one-off history load (**Hent historikk**). |

Each stock links to a page with its score, themes, key figures, announcements, insider trades and open short positions.

How a recommendation is made (model v2, explained in the app under **Slik ble dette beregnet**): every stock gets a percentile rank within its own country on momentum, value, quality and low volatility; small capped adjustments are added for insider trading, buybacks and short interest. Filters remove unprofitable, illiquid and very small companies, penny stocks and duplicate share classes, and the top-ranked stocks get equal weights in whole shares. Since v2 the filters also remove windfalls: a P/E below 4 (usually a one-off gain, changes in the value of holdings, or a short-lived peak) and a rise of more than 300 % in 12 months (an event, not momentum). The low-volatility theme only counts once the price history is loaded (**Hent historikk**). The short-term sleeve follows new buyback programmes and clusters of insider buying, and stays on paper by default, so its track record builds up before any money goes in.

Set `APP_PASSWORD` to require a login, and `SECRET_KEY` so sessions survive restarts. On Railway the app refuses to serve pages until `APP_PASSWORD` is set.

The same advice is available from the command line:

```sh
nordic-signals recommend --account-value 300000 [--long 90 --short 10] [--max-positions 12]
                         [--min-position 20000] [--ask] [--trade-short] [--refresh]
nordic-signals evaluate                        # score past recommendations against later closing prices
```

## Lekepenger: a play-money account

The **Lekepenger** page runs the advice the way a Nordnet customer in Norway would trade it, with 500,000 NOK of play money, so the model can be calibrated on realistic results before any real money is involved. Nothing is traded. Code: `src/nordic_signals/advisor/paper.py`.

What it follows: the advisor's own default policy, 90 % in the long-term part and 10 % in the short-term part (no cash part), at most 12 positions of at least 20,000 NOK. Both parts trade, since it is all play money.
- **Long-term part.** Rebalanced on the first trading evening of each month, from that evening's recommendation, which is logged like any other so the track record measures it too:
  - Holdings the advisor still ranks among the best 24 eligible stocks stay.
  - The rest are sold.
  - The best-ranked stocks it doesn't hold are bought until it holds 12.

  This is the research report's buy/hold spread: stricter to enter than to stay, which keeps turnover and courtage down.
- **Short-term part.** Every evening it buys the advisor's event signals (a new buyback programme, several insiders buying):
  - at most 2 new ones an evening
  - as many at once as its 50,000 NOK allows (two slots of 25,000)
  - each sold after 5 trading days, the signals' horizon

How it trades:
- **Timing.** Orders are decided in the evening, after both markets have closed and the nightly data is in. They fill at the opening price of the stock's next trading day, in the opening auction, where every order gets the same price, so no spread is paid.
  - The evening's decision waits until Nordnet's evening snapshot has that day's closing prices from both Oslo and Stockholm. A decision retried after midnight, behind the nightly price job, still belongs to that evening.
  - An order waits while its stock doesn't trade, and lapses after 5 of its market's trading days.
  - Oslo Børs trades 09:00–16:25 and Nasdaq Stockholm 09:00–17:30, Norwegian time.
  - Holidays come from Euronext's and Nasdaq's calendars (2026–2027; add each new year's dates to `MARKETS`).
- **Fees.** Nordnet's Norwegian price list, class Mini, checked 4 October 2026: 0.15 % of each trade in Nordic shares, at least 29 NOK. Swedish shares bought from a NOK account also pay 0.25 % on each automatic currency exchange. A buy is cut to the cash there is at the opening, and sales come before the day's buys, so their money can pay for them.
  - The evening orders no buy smaller than the smallest position (20,000 NOK) for want of cash.
  - A buy cut to the cash at the opening shows as `delvis utført` in the log. If the cut leaves less than 90 % of its shares and less than the smallest position, the buy lapses instead; a smaller cut, from a higher opening price, is kept.
- **Dividends** are credited on the ex-date, from Yahoo's dividend events. Swedish dividends are paid after 15 % withholding tax. As on an ASK, there is no Norwegian tax.
- **Value.** The account is valued at each day's closing price, as Nordnet shows an account; the cost of selling is paid when a position is sold.
- **During the day.** While Oslo or Stockholm is open, and for an hour after, the stocks the account holds or has orders for, and SEK/NOK, are fetched from Yahoo every 30 minutes. The morning's orders then show as filled at the opening price soon after 09:00, and the account is valued at the latest prices, then at the closing auction's, until Nordnet's evening snapshot replaces them. Swedish trades use that day's evening SEK/NOK rate, not the rate at the opening (about 0.1 % apart on the first day).
- **Orders still waiting** for their opening, after a holiday on one exchange or a day the stock did not trade, are counted as done the next evening: a sale is not ordered again, their money is spoken for, and a buy takes its place among the 12 long-term or the short-term slots.
- **Not modelled:** a large order moving the price, and the delay between seeing a signal and trading. The orders are small next to the stocks' turnover, since the advisor only picks liquid stocks.

The account is a replay: only the orders are stored (`paper_orders`, and each evening's decision in `paper_days`). Fills, fees, dividends and the daily value are worked out from the prices every time, so late data corrects the history. Change `ACCOUNT` when the rules change, and a new account starts from scratch.

The page has two downloads:
- `/lekepenger/export.json`: everything, for analysis. It has each evening's decisions, the orders and what became of them, the trades, holdings, dividends and the daily value.
- `/lekepenger/export.csv`: the trades, for Excel with Norwegian settings.

## Krypto: a play-money crypto account

The **Krypto** page runs a crypto strategy with 100,000 NOK of play money on Firi, the Norwegian exchange that trades crypto against NOK, with Firi's fees and spreads. Nothing is traded. Code: `src/nordic_signals/crypto.py`, prices from `src/nordic_signals/collectors/crypto.py`.

The parts:
- **Big coins, 50 %:** Bitcoin and Ether, 25 % each.
- **Smaller coins, 30 %:** XRP, Cardano and Solana, 10 % each. Firi also trades Polkadot, Litecoin and BNB against NOK, but with wider spreads (Polkadot's was almost 5 %).
- **pump.fun, 20 %:** SOL in a wallet that follows the [pump.fun page's](#pumpfun-measurement) main fake account up and down, as a share of it would, and the price of SOL. SOL is bought on Firi and sent to the wallet for 0.05 SOL (Firi's fee from 1 December 2026; 0.045 before); sending it back is free. A new filter version, whose account starts again at 10 SOL, carries on from where the last one ended.

Two accounts make the same start:
- **The main account follows a trend rule.** Every Monday at 00:00 UTC, on Sunday's close, a coin is held only while its price is above its average over the last 200 days. Below it, the coin is sold and its share waits in NOK until a later Monday finds it above again. A coin with less than 200 days of closes is held.
- **The yardstick holds every coin all the time:** what the trend rule is up against.

Both rebalance on the first of each month at 00:00 UTC: every coin the account holds, and the pump.fun part, go back to their share of the account, unless they are already within a fifth of it. When those trades need more money than is spare, the parts above their share pay for it; money left over goes to the coins below theirs, then to the pump.fun part, so none sits idle (but SOL is only sent to the wallet when the 0.05 SOL fee is at most 5 % of it). The kroner of the coins the trend rule has sold count as a part of their own, with those coins' share as its target, and pay their own selling costs. That night's check also applies the trend rule.

How it trades:
- **Fees.** Firi's price list, checked 5 October 2026: 0.7 % of each trade.
- **Prices.** A trade is a market order at the first prices collected after the decision: it buys at the best ask and sells at the best bid of Firi's NOK order book, so the spread is paid too. In the first days it was about 0.3 % for Bitcoin, 0.6–1.2 % for Cardano, XRP and Solana and 1–2.3 % for Ether, each way, at any hour: Firi's market maker moves its quotes every few minutes, so a fill's spread is partly luck. 25,000 NOK filled at the best price in all five books. A purchase spends the money set for it, fees and spread included, so each part pays its own costs. Starting the account on 6 October cost 1.9 % (fee 0.7 %, spread 1.15 %, sending SOL 0.06 %).
- **XRP's book barely moves:** Firi showed the same best bid and ask for XRP for a whole day, so XRP is valued at a price that can lag the market.
- **Value.** Coins are valued at the middle of Firi's best bid and ask, and the pump.fun part at its SOL's value. The cost of selling is paid when something is sold.
- **Not modelled:** tax (22 % on gains), and a large order moving the price in Firi's thin order books.

Why the 200-day average, checked weekly? Each rule was tested on daily closes (USD, from Yahoo) with Firi's fee and the spreads seen in the account's first days (Bitcoin 0.33 %, Ether 1.5 %, XRP 1 %, Cardano 0.7 %, Solana 1.1 % each way), against buy and hold, both rebalanced monthly with the account's 20 % band. From July 2018 the test holds Bitcoin, Ether, XRP and Cardano; from November 2020 Solana too. Returns are a year, compounded:

| Rule | From 2018 | Worst fall | From 2020 | Worst fall |
|---|---|---|---|---|
| Buy and hold | 35.4 % | −78 % | 61.2 % | −80 % |
| **200-day average, weekly** | 33.8 % | −54 % | 52.8 % | −50 % |
| 20-week average, weekly | 36.7 % | −61 % | 49.8 % | −59 % |
| 4-week momentum, weekly | 29.3 % | −56 % | 54.5 % | −51 % |
| 50-day average, daily | 12.3 % | −78 % | 29.7 % | −71 % |

The 200-day rule earned 1.6 to 8.4 points a year less than buy and hold; the slow rules together ranged from 1.3 points more (20-week, from 2018) to 11 points less (20-week, from 2020). All three cut the worst fall from −78 % or −80 % to between −50 % and −61 %. The 200-day rule trades about four times a year per coin, costing some 7 % of the account a year, against 1.3 % for buy and hold. The fast rules would have won before costs: the 50-day average checked daily made 83 % a year from 2020 with no costs. Firi's fees and spreads took far more than that edge, about 33 % a year. The first version of this table used one evening's spreads, about two-thirds as wide on average (much narrower for XRP and Solana, wider for Cardano), and showed the 200-day rule closer to buy and hold; the spreads the account has paid since are the better guide. The 200-day average is the most widely used trend line, and the steadiest here across both periods, though not the best in every column; it was chosen after this test, so the test does not prove it. The coins are today's survivors and the history is short, so the table is a pointer, not a promise; the two accounts test it going forward.

The account is a replay: only the prices are stored. Firi's best bid and ask are kept every 15 minutes (`crypto_quotes`, thinned to the first complete run of each hour after a week), and the coins' daily closes are in `price_bars`. Trades, fees and value are worked out from them every time, so late prices correct the history. Change `ACCOUNT` and `STARTED_AT` when the rules change, and the account starts again. It starts on 6 October 2026 at 00:00 UTC.

The page has the pump.fun page's look: the hero, a ticker tape with each coin's move over the last 24 hours, and a card per coin with its result after costs, its value, a chart of its price since the account started, its share of the account against the target and its distance to the 200-day average. The pump.fun part's card and the comparison link to the pump.fun page, which no longer has a tab of its own. Like that page, it updates itself while open: it checks `/krypto/version` every 15 seconds and swaps in the parts that changed, so new prices from Firi (every 15 minutes) and the pump.fun account's value (every 5 minutes) show up without a reload.

The page has two downloads:
- `/krypto/export.json`: everything, for analysis. It has both accounts' trades, every check with the trend rule's view of each coin, the holdings, and the value at every price collection.
- `/krypto/export.csv`: both accounts' trades, for Excel with Norwegian settings.

## pump.fun measurement

An experiment on the **pump.fun** page (`/pumpfun`, reached from Krypto, whose pump.fun part follows its main account): can a filter tell pump.fun's pump-and-dump launches apart from the rest, well enough that the tokens it lets through mostly don't collapse? Nothing is traded. It only measures, so the answer exists before any money is involved.

Every 5 minutes the web service's schedule (see [Scheduling](#scheduling)):

1. **Discovers launches:** it reads pump.fun's list of the 50 newest tokens and stores all of them, so creators who launch token after token can be recognised. Every new one is scored (`collect pumpfun --sample N` limits that to a random sample).
2. **Scores each token** about 10 minutes after launch, on warning signs from rug-pull research:
   - the creator has launched other tokens in the last day
   - the creator's wallet is less than a day old, or behaves like a bot
   - the ten largest holders own more than 30 % (needs `SOLANA_RPC_URL`)
   - the price has already fallen below half its peak
   - the whole bonding curve was bought within minutes

   One more sign comes from this measurement itself (from `pf3`, see below):
   - the price has already doubled since launch, which takes about 12 SOL of net buying

   Only tokens with real money in them are measured:
   - they traded in the 5 minutes before scoring, and
   - their market value is at least 10 % above pump.fun's launch value of about 27.96 SOL, which takes roughly 1.5 SOL of net buying.

   On the bonding curve the price only rises as SOL is paid in. A token still at its launch price has had no net buying, its few trades are usually bots buying and selling back, and its price can't fall. It would neither collapse nor earn anything, so counting it would make the filter look better than it is.

   A measured token with no warning signs passes.
3. **Follows the price of each measured token on DexScreener for 24 hours:** every 5 minutes for the first 6 hours, then every 30 minutes. Other scored tokens are not followed.

A token counts as *collapsed* at 1, 6 or 24 hours after scoring if its price then is at most 10 % of its peak since scoring. It counts as *quiet* if nobody traded it since scoring. For each horizon the page shows:
- how often measured launches collapse, and how many went quiet
- the share of collapses the filter caught, and the share of survivors it let through
- how many of the tokens that passed still collapsed
- the returns after pump.fun's 1.25 % fee on each trade
- how well each warning sign separates collapses from survivors

The 1-hour figures come about an hour after collection starts. The decision on real money uses the 24-hour figures.

The page also runs the filter with fake money, in three accounts that buy by the same rule:
- Each starts with 10 SOL. Every token that passes is bought for 0.1 SOL at its price when scored, while the cash lasts.
- Fees are charged on both trades, and a token that disappears from DexScreener counts as lost. Cash from sales goes into new buys.
- **The main account** sells a position as soon as it is worth twice its cost after fees (+100 %), and otherwise after 24 hours.
  - The sale is credited at exactly +100 %, even when the price jumped past the line between two looks, so the account never gets a lucky price.
  - It has run since 4 October 2026. In `pf2`'s day, 20 of the 149 tokens that passed reached +100 % within 24 hours, and held instead they ended at a median of −2 %. On the full log's minute-by-minute prices, this rule would have left that account at 8.25 SOL instead of 7.03.
- **The 24-hour account** holds every position for exactly 24 hours. It's the yardstick the other two are compared with.
- **The trailing account** also waits until a position is worth twice its cost after fees, but then lets it run. It sells once the price has fallen 25 % below its highest since buying, at the price seen, and otherwise after 24 hours.
  - It tests whether letting winners run beats taking +100 %. In `pf3`'s first day, 9 of the 10 positions sold at +100 % were below that line again the next afternoon, but one went on to 65 times its buy price.
  - Prices are seen a minute or more apart, so a token that falls straight through the line is sold lower, as it would be in real trading.
  - It has run since 4 October 2026, and replaced the stup account, which sold at half the buy price. On pump.fun's bonding curve a token's price can't fall below its launch price, so since `pf3` buys only below twice the launch price, nothing it buys can halve before it graduates. In its first 18 hours none of 84 did, against 198 of the 473 tokens it measured but stopped. The halving is still recorded per token, for the log.
- The main account's value is recorded every 5 minutes for the chart. Between collector runs the open positions' prices are fetched every minute, so the accounts and the positions move while the page is open.
- The page shows the three accounts side by side, and marks the main account's sales at +100 %.

Slippage is not included, so real results would be worse.

The page is live: it checks for new data every 15 seconds and updates itself, with no reload. New positions slide in, changed numbers flash, and a ticker tape runs along the top. Each open position has its own card with a chart of its result since it was bought, and each sale has a small chart from purchase to sale.

To look for patterns as the data grows:
- **Mønstre i galskapen** splits the measured tokens into quarters by each feature seen at scoring (market value, trades, buy share, the creator wallet's age and activity, holder concentration). For each quarter it shows how often the tokens collapsed and their median return. The features whose quarters differ most come first, which is where the filter's next rule may be. It covers all tokens with trades and, separately, only those that passed.

  A hype table compares groups by:
  - the social links the creator added at launch (X, Telegram, a website)
  - whether the token had a paid DexScreener profile or boosts when scored

  X and Telegram can't be read without paid access or breaking their terms, and pump.fun no longer serves its comment threads.
- **Last ned loggen** downloads everything measured:
  - `/pumpfun/export-analyse.json`, the small one, made to send on, about 1 MB a day. It has every measured token without pump.fun's launch fields, the counts of all the other tokens, the three fake accounts' trades and the main account's value.
    - It also has the price paths of the current version's tokens that passed, as seconds after scoring and price, for the last 7 days. While a fake account holds a token, its price is fetched every minute and stored when it changed. That's enough to try other exit rules on, for a few hundred kB a day.
  - `/pumpfun/export.csv`: one row per token, for Excel with Norwegian settings.
  - `/pumpfun/export.json`: the same, plus every fake trade, the account value over time and the price paths. About 30 MB a day, because it lists every launch, including the ones never followed.

  Price paths are kept for 7 days (`pf_prices`). The 1-, 6- and 24-hour prices in `pf_tokens` are kept for good. With about 98 % of launches ending as pump-and-dumps, the filter has to catch well over 99 % of them before what passes is mostly honest.

Sources:
- pump.fun's unofficial list API (`frontend-api-v3.pump.fun`), for the newest launches
- DexScreener's documented token API, for prices and trades
- Solana JSON-RPC, for the creator wallet's history and the largest holders. The public node refuses the holders call, so set `SOLANA_RPC_URL` to a private node (for example a free Helius key) to measure concentration.

**Reading the log from GitHub.** The web service can push the small log to a branch every hour, so it can be read straight from the repository:
1. On GitHub, create a fine-grained personal access token (Settings → Developer settings → Fine-grained tokens):
   - Repository access: only this repository.
   - Repository permissions: Contents, Read and write.
2. On the Railway web service, set these variables:
   - `GITHUB_TOKEN` to the token
   - `LOG_REPO` to `andreovstedal/Trading`
   - optionally `LOG_BRANCH` (default `pumpfun-logg`)
3. Within the hour, the branch `pumpfun-logg` appears, holding `pumpfun-analyse.json.gz`. Read it with:

   ```sh
   git fetch origin pumpfun-logg
   git show origin/pumpfun-logg:pumpfun-analyse.json.gz | gunzip > pumpfun-analyse.json
   ```

The branch is replaced each time, so it only holds the latest copy and the repository doesn't grow. Railway deploys the code branch, not this one, so the pushes don't trigger a deploy.

The screen is versioned, and only the current version's results and fake portfolio are shown.
- `pf1` (from 2 October 2026) counted any token with a trade as active. Its first export showed that most tokens it passed were still at their launch price.
- `pf2` added the real-money rule and scores every new launch.
- `pf3` (from late on 3 October 2026) also stops tokens whose price has already doubled since launch. In `pf2`'s first day, 528 measured tokens had reached 6 hours:
  - Tokens at twice the launch price or more had a median of −68 % after 6 hours in the first half of the day and −74 % in the second, with about a third collapsed.
  - The rest had −15 % and −16 %, with 1 % collapsed.
  - The rest still lost money, so only `pf3`'s own results, on tokens it hasn't seen, show whether the rule is worth anything.

Scoring every launch stores about 14,000 tokens a day, roughly 20 MB. Code: `src/nordic_signals/pumpfun.py` (screen and results) and `src/nordic_signals/collectors/pumpfun.py` (collection).

## Collecting data

```sh
nordic-signals collect nordnet                 # tradable universe, Nordnet owner counts, key ratios (NO + SE)
nordic-signals collect newsweb --days 2        # Oslo Børs announcements, full text for key categories
nordic-signals collect fi-insider --days 3     # Swedish insider trades
nordic-signals collect fi-short                # Swedish short positions (named + aggregate)
nordic-signals collect no-short                # Norwegian short positions
nordic-signals collect mfn --slug nibe-industrier --days 30
nordic-signals collect yahoo --symbol EQNR.OL --symbol VOLV-B.ST --range 1y
nordic-signals collect intraday                # today's NewsWeb announcements and FI insider trades
nordic-signals collect daily                   # nordnet, newsweb, fi-insider, fi-short, no-short, SEK/NOK rate
nordic-signals collect backfill                # one-off history load for a new database (1-2 hours)
nordic-signals collect pumpfun                 # pump.fun launches for the pump-and-dump measurement
nordic-signals collect krypto                  # Firi order books and daily closes for the play-money crypto account
nordic-signals nightly                         # the daily set, then evaluate past recommendations
nordic-signals status                          # row counts and the latest run per source
```

The database is `--db` if given, else the `DATABASE_URL` environment variable (PostgreSQL, as on Railway), else a local SQLite file at `data/signals.sqlite` (git-ignored). Use `--start`/`--end` for backfills, for example `collect fi-insider --start 2016-07-01`. MFN and Yahoo need a watchlist: pass `--slug`/`--symbol`, or `--universe SE` to derive one from the stored Nordnet universe. Universe-wide Yahoo runs are slow by design, at about 4 s per symbol.

| Source | Collector | Endpoint | Tables |
|---|---|---|---|
| Euronext Oslo Børs NewsWeb | `newsweb` | `api3.oslo.oslobors.no/v1/newsreader` (the API behind newsweb.oslobors.no) | `newsweb_messages`, `newsweb_bodies`, `newsweb_attachments`, `newsweb_categories` |
| Finansinspektionen insider register | `fi-insider` | `marknadssok.fi.se` CSV export | `se_insider_trades` |
| Finansinspektionen short register | `fi-short` | `www.fi.se/BlankningsRegister/*` (.ods) | `se_short_positions`, `se_short_aggregate` |
| Finanstilsynet short-sale register | `no-short` | `ssr.finanstilsynet.no/api/v2/instruments` | `no_short_totals`, `no_short_positions` |
| MFN press releases | `mfn` | `feed.mfn.se/v1/feed/{entity}` (entity IDs read from `mfn.se/all/a/{slug}`) | `mfn_items`, `mfn_entities` |
| Yahoo Finance | `yahoo` | `query1.finance.yahoo.com/v8/finance/chart/{symbol}` | `price_bars`, `dividends`, `splits` |
| Nordnet stock list | `nordnet` | `www.nordnet.no/api/2/instrument_search/query/stocklist` | `instruments`, `nordnet_observations` |
| Firi order books, and Yahoo daily closes for the coins | `krypto` | `api.firi.com/v2/markets/{market}/depth`, Yahoo's chart API | `crypto_quotes`, `price_bars` |

All endpoints were checked against the live sites on 2026-10-02; each collector's module docstring records the details.

### Scheduling

The web service runs the collection itself, in two background threads (`src/nordic_signals/scheduler.py`), so no cron services are needed. Some registers keep no history: Norway's short register keeps two years, FI's aggregate short file keeps only the latest value, and Nordnet owner counts are a daily snapshot. Collection should therefore run every weekday from the start.

| Job | Equivalent command | When (UTC) |
|---|---|---|
| pump.fun | `nordic-signals collect pumpfun` | every 5 minutes, around the clock |
| pump.fun quotes | none; `PumpFunCollector.quote` | every minute, around the clock: the open fake-money positions' prices, for the live page. Not logged in `runs`. |
| pump.fun log | none; `logpush.push` | every hour, once `GITHUB_TOKEN` and `LOG_REPO` are set: the small log to the `pumpfun-logg` branch |
| krypto | `nordic-signals collect krypto` | every 15 minutes, around the clock: Firi's order books, and each coin's daily close once the day is over (midnight UTC) |
| intraday | `nordic-signals collect intraday` | every 15 minutes, 05:00–18:59 on weekdays (07:00–20:59 Oslo summer time) |
| nightly | `nordic-signals nightly` | from 20:30 on weekdays: after both closes and the evening owner-count update; then scores past recommendations |
| lekepenger | none; `advisor.paper.decide` | right after the nightly set on weekdays: the play-money account's orders for the next opening. Tried again an hour later if that evening's closing prices are missing. |
| lekepenger prices | `nordic-signals collect yahoo --symbol ...` for `advisor.paper.watched_symbols` | every 30 minutes, 07:00–17:59 on weekdays, while Oslo or Stockholm is open and for an hour after: the account's stocks and SEK/NOK, so its orders fill at the opening price during the day. Logged as `lekepenger-kurser`. |
| MFN | `nordic-signals collect mfn --universe SE --days 3 --max-pages 1` | from 21:00 on weekdays |
| prices | `nordic-signals collect yahoo --universe NO --universe SE --range 5d` | from 21:30 on weekdays: about 90 minutes at 4 s per symbol |

How it behaves:
- **Nothing runs twice.** A job is due when the `runs` log shows it hasn't run recently. Whatever already ran, from the schedule, a button on the Data page or a separate cron service, is not repeated.
- **Missed jobs catch up.** A job missed while the service was down runs once it is back, the same evening for the daily jobs.
- **Failures retry.** A daily job that failed is retried after an hour.
- **Web-page jobs come first.** The Nordic jobs wait while a job started from the web page runs. The crypto jobs (pump.fun and krypto) don't wait.
- **Restarts are cleaned up.** Runs cut off by a restart are marked as interrupted.

The scheduler is on by default on Railway and off elsewhere. Set `SCHEDULER=off` or `SCHEDULER=on` to override. The commands still work on their own, for example as Railway cron services; the schedule skips what they have already done. The times are in UTC and hold in both summer (UTC+2) and winter (UTC+1) Nordic time.

## Deploying on Railway

The project needs two things: PostgreSQL and the web service, which also runs the data collection (see [Scheduling](#scheduling)). Railway builds the web service from the `Dockerfile` automatically. The Nordic data is small, under 1 GB a year. The pump.fun measurement adds about 20 MB a day while it runs.

### In the dashboard

1. In the project, choose **+ New → Database → PostgreSQL**.
2. Add the web app: **+ New → GitHub Repo**, this repository.
   - **Variables:** `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (a reference to the database's private URL), `APP_PASSWORD` = a password of your choice, and `SECRET_KEY` = a long random string (for example from `openssl rand -hex 32`).
   - **Settings → Deploy:** set **Healthcheck Path** to `/health`. The start command comes from the `Dockerfile`.
   - **Settings → Networking:** choose **Generate Domain** to get the app's address.
3. Under **Settings → Source**, pick the branch to deploy from.
4. Open the app, sign in, and press **Hent historikk** on the **Data** page once. It loads the history the model needs (a year of prices, insider trades, announcements and short positions) in one to two hours; the app stays usable meanwhile. After that, the schedule keeps the data current.

Optional variables on the web service: `SOLANA_RPC_URL`, a private Solana RPC node (for example with a free Helius key), for the pump.fun measurement's holder concentration; and `SCHEDULER=off` to stop the automatic collection. Cron services from an earlier setup can be deleted, or left: the schedule skips what they have already done.

Without `DATABASE_URL`, a command on Railway stops with an error rather than writing to a throwaway SQLite file. If you deploy with `railway up` instead of GitHub, pull the latest commit first so the `Dockerfile` is included.

### As code

[`.railway/railway.ts`](.railway/railway.ts) describes the same setup (Postgres and the web app) for Railway's infrastructure-as-code tooling (Railway CLI 5.42.1 or newer):

```sh
npm install --prefix .railway    # installs the "railway" SDK the file imports
railway link                     # choose the project and environment
railway config plan              # preview
railway config apply             # create or update the services
```

The file describes the whole project: anything not listed in it is proposed for deletion. Either start from an empty project or read the plan carefully. The name in `project("nordic-signals", ...)` and the repository in `REPO` should match yours. Set `APP_PASSWORD` and `SECRET_KEY` (and optionally `SCHEDULER` and `SOLANA_RPC_URL`) on the web service in the dashboard; the file keeps whatever values are there. Generating the domain and the first history load are still done by hand, as in steps 2 and 4 above.

## How data is stored

- **Raw layer, append-only.** `fetches` logs every request (source, URL, status, time, SHA-256), and `blobs` keeps each distinct response body once, compressed. Parsers can be improved and re-run over old payloads.
- **Parsed tables.** These hold one row per natural key, with `first_seen_at`/`last_seen_at` and the fetch IDs. Backtests filter on `first_seen_at` to see only what was known at the time. Columns that legitimately change, such as a NewsWeb correction link or a short position's size, are refreshed; everything else keeps its first value.
- **`runs`** records each collector run with its counts, warnings and errors.

Production runs on PostgreSQL, with typed columns: timestamps with time zone, dates, numbers, booleans and JSONB lists. Local development and tests can use SQLite with the same schema. Tables are created automatically on first run; there are no migrations yet, so a schema change to an existing table needs Alembic or a manual `ALTER TABLE`.

## Terms of use and privacy

This is for personal, non-commercial use, and the collectors poll slowly and identify themselves.

- **Yahoo:** personal use only.
- **Nordnet:** the stock-list endpoint is unofficial. Nordnet's customer terms may restrict automated collection, so run it at most once a day.
- **MFN:** read only through `feed.mfn.se`. mfn.se's robots.txt disallows its JSON/RSS URLs, and this package never requests them.
- **Finansinspektionen:** data may be reused with attribution.
- **Personal data:** the insider and short registers contain names, so keep the database private.
- **Sharing:** if the app's advice is ever shared with other people, it likely becomes licensable investment advice. See the report's allocation section.
- **pump.fun and DexScreener:**
  - pump.fun's list API is unofficial and rate-limits bursts, so the job reads it once per run.
  - DexScreener's API is documented, with a limit of 300 requests a minute; the job stays well under it.
  - These responses (pump.fun, DexScreener and Solana RPC) are not stored in the raw layer; at this frequency they would add gigabytes a year.
- **Firi:** the public market-data API needs no key. Its order books are read every 15 minutes and kept only as best bid and ask, not in the raw layer.

## Tests

```sh
.venv/bin/pytest                                                   # SQLite
TEST_DATABASE_URL=postgresql://localhost/signals_test .venv/bin/pytest   # SQLite and PostgreSQL
```

The tests run offline against trimmed copies of real responses in `tests/fixtures/`, with personal names anonymised. `TEST_DATABASE_URL` must point at a scratch database, because its tables are dropped between tests.
