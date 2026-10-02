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

Some registers keep no history: Norway's short register keeps two years, FI's aggregate short file keeps only the latest value, and Nordnet owner counts are a daily snapshot. Run the jobs every weekday from the start.

| Job | Command | When (UTC, weekdays) |
|---|---|---|
| `collect-intraday` | `nordic-signals collect intraday` | `*/15 5-18 * * 1-5`: every 15 min, 07:00–20:45 Oslo summer time |
| `collect-daily` | `nordic-signals nightly` | `30 20 * * 1-5`: after both closes and the evening owner-count update; then scores past recommendations |
| `collect-mfn` | `nordic-signals collect mfn --universe SE --days 3 --max-pages 1` | `0 21 * * 1-5`: needs the universe from `collect-daily` |
| `collect-prices` | `nordic-signals collect yahoo --universe NO --universe SE --range 5d` | `30 21 * * 1-5`: about 90 minutes at 4 s per symbol |

The times are in UTC because Railway's cron is UTC-only; they hold in both summer (UTC+2) and winter (UTC+1) Nordic time.

## Deploying on Railway

The `Dockerfile` builds one image for the web app and every job, and Railway uses it automatically; by default it starts the web app. Each job is a Railway cron service with its own start command: it starts on schedule, runs one command and exits. Everything shares one PostgreSQL database. Data volume is small, roughly 1 GB a year.

### In the dashboard

1. In the project, choose **+ New → Database → PostgreSQL**.
2. Add the web app: **+ New → GitHub Repo**, this repository.
   - **Variables:** `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (a reference to the database's private URL), `APP_PASSWORD` = a password of your choice, and `SECRET_KEY` = a long random string (for example from `openssl rand -hex 32`).
   - **Settings → Deploy:** set **Healthcheck Path** to `/health`. The start command comes from the `Dockerfile`.
   - **Settings → Networking:** choose **Generate Domain** to get the app's address.
3. Create one more service from the same repository per job in the table above. For each one:
   - **Variables:** add `DATABASE_URL` as above.
   - **Settings → Deploy:** set the **Custom Start Command** and **Cron Schedule** from the table, and set **Restart Policy** to **Never**.
4. For every service, pick the branch to deploy from under **Settings → Source**.
5. Open the app, sign in, and press **Hent historikk** on the **Data** page once. It loads the history the model needs (a year of prices, insider trades, announcements and short positions) in one to two hours; the app stays usable meanwhile. After that, the cron jobs keep the data current.

Without `DATABASE_URL`, a job on Railway stops with an error rather than writing to a throwaway SQLite file. If you deploy with `railway up` instead of GitHub, pull the latest commit first so the `Dockerfile` is included.

### As code

[`.railway/railway.ts`](.railway/railway.ts) describes the same setup (Postgres, the web app and the four cron services) for Railway's infrastructure-as-code tooling (Railway CLI 5.42.1 or newer):

```sh
npm install --prefix .railway    # installs the "railway" SDK the file imports
railway link                     # choose the project and environment
railway config plan              # preview
railway config apply             # create or update the services
```

The file describes the whole project: anything not listed in it is proposed for deletion. Either start from an empty project or read the plan carefully. The name in `project("nordic-signals", ...)` and the repository in `REPO` should match yours. Set `APP_PASSWORD` and `SECRET_KEY` on the web service in the dashboard; the file keeps whatever values are there. Generating the domain and the first history load are still done by hand, as in steps 2 and 5 above.

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

## Tests

```sh
.venv/bin/pytest                                                   # SQLite
TEST_DATABASE_URL=postgresql://localhost/signals_test .venv/bin/pytest   # SQLite and PostgreSQL
```

The tests run offline against trimmed copies of real responses in `tests/fixtures/`, with personal names anonymised. `TEST_DATABASE_URL` must point at a scratch database, because its tables are dropped between tests.
