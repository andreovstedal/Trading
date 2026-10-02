# Nordic signals

A personal web app, in progress, for Nordnet-tradable Norwegian and Swedish shares. It gathers insider trades, company announcements, short positions, prices and other public data. When you enter an account value, it suggests how to split the account between a long-term value sleeve and a short-term trading sleeve. It never places trades. Every input and recommendation is logged, so the formula can be scored against outcomes and improved over time.

## Status

| Part | State |
|---|---|
| Research | Done: [`reports/Nordic stock signal data sources.md`](reports/Nordic%20stock%20signal%20data%20sources.md) covers sources, evidence per sleeve, allocation rules and the logging design. The per-topic notes are in `research_notes/` |
| Collectors | Done for the six core sources (this package, see below) |
| Features, scoring and allocation | Not started |
| Prediction and outcome log | Not started (raw-data layer is in place) |
| Dashboard | Not started |

## Setup

Python 3.11 or newer.

```sh
uv venv && uv pip install -e ".[dev]"
# or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
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
nordic-signals collect daily                   # nordnet, newsweb, fi-insider, fi-short, no-short
nordic-signals status                          # row counts and the latest run per source
```

Data goes to `data/signals.sqlite` (`--db` to change it); `data/` is git-ignored. Use `--start`/`--end` for backfills, for example `collect fi-insider --start 2016-07-01`. MFN and Yahoo need a watchlist: pass `--slug`/`--symbol`, or `--universe SE` to derive one from the stored Nordnet universe. Universe-wide Yahoo runs are slow by design, at about 4 s per symbol.

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

Some registers keep no history: Norway's short register keeps two years, FI's aggregate short file keeps only the latest value, and Nordnet owner counts are a daily snapshot. Run the daily set every weekday from the start. A crontab example, assuming the machine runs on Oslo time:

```cron
# End of day, after both closes and the short registers' 15:30 update
30 19 * * 1-5  cd ~/Trading && .venv/bin/nordic-signals collect daily >> data/collect.log 2>&1
# Fresh announcements and insider trades during the day
*/15 7-18 * * 1-5  cd ~/Trading && .venv/bin/nordic-signals collect newsweb && .venv/bin/nordic-signals collect fi-insider --days 1
```

## How data is stored

- **Raw layer, append-only.** `fetches` logs every request (source, URL, status, time, SHA-256), and `blobs` keeps each distinct response body once, compressed. Parsers can be improved and re-run over old payloads.
- **Parsed tables.** These hold one row per natural key, with `first_seen_at`/`last_seen_at` and the fetch IDs. Backtests filter on `first_seen_at` to see only what was known at the time. Columns that legitimately change, such as a NewsWeb correction link or a short position's size, are refreshed; everything else keeps its first value.
- **`runs`** records each collector run with its counts, warnings and errors.

SQLite is used because a web app and scheduled collectors can share it safely. DuckDB can read it directly for analysis (`ATTACH 'data/signals.sqlite' (TYPE sqlite)`).

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
.venv/bin/pytest
```

The tests run offline against trimmed copies of real responses in `tests/fixtures/`, with personal names anonymised.
