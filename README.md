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
| **Råd** (`/`) | Enter the account value and the split between the long-term sleeve, the short-term sleeve and cash, then press **Hent data og foreslå fordeling**. With **Oppdater data først** ticked it refreshes prices, announcements and insider trades first (about 30 seconds). The result lists whole-share positions, runners-up, short-term signals, an avoid list and the reasons behind each pick, and can be downloaded as CSV (semicolons and decimal commas, for Excel with Norwegian settings). |
| **Signaler** | Fresh events from the last four days: Swedish insider purchases, Norwegian insider notices, new buyback programmes and rising short interest. |
| **Resultater** | The track record: excess return, hit rate and rank IC per model version and horizon, and per short-term signal type. |
| **Data** | When each source last ran, row counts, and buttons for a manual refresh and the one-off history load (**Hent historikk**). |

Each stock links to a page with its score, themes, key figures, announcements, insider trades and open short positions.

How a recommendation is made (model v2, explained in the app under **Slik ble dette beregnet**): every stock gets a percentile rank within its own country on momentum, value, quality and low volatility; small capped adjustments are added for insider trading, buybacks and short interest. Filters remove unprofitable, illiquid and very small companies, penny stocks and duplicate share classes, and the top-ranked stocks get equal weights in whole shares. Since v2 the filters also remove windfalls: a P/E below 4 (usually a one-off gain, changes in the value of holdings, or a short-lived peak) and a rise of more than 300 % in 12 months (an event, not momentum). The low-volatility theme only counts once the price history is loaded (**Hent historikk**). The short-term sleeve follows new buyback programmes and clusters of insider buying, and stays on paper by default, so its track record builds up before any money goes in.

Set `APP_PASSWORD` to require a login, and `SECRET_KEY` so sessions survive restarts. On Railway the app refuses to serve pages until `APP_PASSWORD` is set.

The same advice is available from the command line:

```sh
nordic-signals recommend --account-value 300000 [--long 85 --short 10 --cash 5] [--max-positions 12]
                         [--min-position 20000] [--ask] [--trade-short] [--refresh]
nordic-signals evaluate                        # score past recommendations against later closing prices
```

## pump.fun measurement

A separate experiment, on the **pump.fun** page: can a filter tell pump.fun's pump-and-dump launches apart from the rest, well enough that the tokens it lets through mostly don't collapse? Nothing is traded. It only measures, so the answer exists before any money is involved.

Every 5 minutes the web service's schedule (see [Scheduling](#scheduling)):

1. **Discovers launches:** it reads pump.fun's list of the 50 newest tokens and stores all of them, so creators who launch token after token can be recognised. Every new one is scored (`collect pumpfun --sample N` limits that to a random sample).
2. **Scores each token** about 10 minutes after launch, on warning signs from rug-pull research:
   - the creator has launched other tokens in the last day
   - the creator's wallet is less than a day old, or behaves like a bot
   - the ten largest holders own more than 30 % (needs `SOLANA_RPC_URL`)
   - the price has already fallen below half its peak
   - the whole bonding curve was bought within minutes

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

The page also runs the filter with fake money:
- The account starts with 10 SOL.
- Every token that passes is bought for 0.1 SOL at its price when scored, while the cash lasts, and sold after 24 hours.
- Fees are charged on both trades, and a token that disappears from DexScreener counts as lost.
- Its value is recorded every 5 minutes. Between collector runs the open positions' prices are fetched every minute, so the account value and the positions move while the page is open.
- A second fake account, the *stup* account, makes the same buys. It sells a position as soon as a price at or below half the buy price is seen, at the price seen, and uses the cash for new buys.
  - Prices are seen a minute or more apart, so a token that falls straight through the halfway line is sold lower, as it would be in real trading.
  - The page shows both accounts side by side, and marks the positions the stup account sold.

Slippage is not included, so real results would be worse.

The page is live: it checks for new data every 15 seconds and updates itself, with no reload. New positions slide in, changed numbers flash, and a ticker tape runs along the top. Each open position has its own card with a chart of its result since it was bought, and each sale has a small chart of its 24 hours.

To look for patterns as the data grows:
- **Mønstre i galskapen** splits the measured tokens into quarters by each feature seen at scoring (market value, trades, buy share, the creator wallet's age and activity, holder concentration). For each quarter it shows how often the tokens collapsed and their median return. The features whose quarters differ most come first, which is where the filter's next rule may be. It covers all tokens with trades and, separately, only those that passed.

  A hype table compares groups by:
  - the social links the creator added at launch (X, Telegram, a website)
  - whether the token had a paid DexScreener profile or boosts when scored

  X and Telegram can't be read without paid access or breaking their terms, and pump.fun no longer serves its comment threads.
- **Last ned loggen** downloads everything measured:
  - `/pumpfun/export.csv`: one row per token, for Excel with Norwegian settings.
  - `/pumpfun/export.json`: the same, plus every fake trade, the account value over time and the price paths.

  Price paths are kept for 7 days (`pf_prices`). The 1-, 6- and 24-hour prices in `pf_tokens` are kept for good. With about 98 % of launches ending as pump-and-dumps, the filter has to catch well over 99 % of them before what passes is mostly honest.

Sources:
- pump.fun's unofficial list API (`frontend-api-v3.pump.fun`), for the newest launches
- DexScreener's documented token API, for prices and trades
- Solana JSON-RPC, for the creator wallet's history and the largest holders. The public node refuses the holders call, so set `SOLANA_RPC_URL` to a private node (for example a free Helius key) to measure concentration.

The screen is versioned, and only the current version's results and fake portfolio are shown.
- `pf1` (from 2 October 2026) counted any token with a trade as active. Its first export showed that most tokens it passed were still at their launch price.
- `pf2` added the real-money rule and scores every new launch.

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

All endpoints were checked against the live sites on 2026-10-02; each collector's module docstring records the details.

### Scheduling

The web service runs the collection itself, in two background threads (`src/nordic_signals/scheduler.py`), so no cron services are needed. Some registers keep no history: Norway's short register keeps two years, FI's aggregate short file keeps only the latest value, and Nordnet owner counts are a daily snapshot. Collection should therefore run every weekday from the start.

| Job | Equivalent command | When (UTC) |
|---|---|---|
| pump.fun | `nordic-signals collect pumpfun` | every 5 minutes, around the clock |
| pump.fun quotes | none; `PumpFunCollector.quote` | every minute, around the clock: the open fake-money positions' prices, for the live page. Not logged in `runs`. |
| intraday | `nordic-signals collect intraday` | every 15 minutes, 05:00–18:59 on weekdays (07:00–20:59 Oslo summer time) |
| nightly | `nordic-signals nightly` | from 20:30 on weekdays: after both closes and the evening owner-count update; then scores past recommendations |
| MFN | `nordic-signals collect mfn --universe SE --days 3 --max-pages 1` | from 21:00 on weekdays |
| prices | `nordic-signals collect yahoo --universe NO --universe SE --range 5d` | from 21:30 on weekdays: about 90 minutes at 4 s per symbol |

How it behaves:
- **Nothing runs twice.** A job is due when the `runs` log shows it hasn't run recently. Whatever already ran, from the schedule, a button on the Data page or a separate cron service, is not repeated.
- **Missed jobs catch up.** A job missed while the service was down runs once it is back, the same evening for the daily jobs.
- **Failures retry.** A daily job that failed is retried after an hour.
- **Web-page jobs come first.** The Nordic jobs wait while a job started from the web page runs. pump.fun doesn't wait.
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

## Tests

```sh
.venv/bin/pytest                                                   # SQLite
TEST_DATABASE_URL=postgresql://localhost/signals_test .venv/bin/pytest   # SQLite and PostgreSQL
```

The tests run offline against trimmed copies of real responses in `tests/fixtures/`, with personal names anonymised. `TEST_DATABASE_URL` must point at a scratch database, because its tables are dropped between tests.
