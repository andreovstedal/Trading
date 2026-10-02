# Intraday / Real-Time Data and Short-Horizon Signals for Nordnet-Tradable Norwegian and Swedish Shares (secondarily Danish/Finnish), as of October 2026

Research-process notes (read first):
- Retrieval constraints: the session's shared WebSearch budget (200 calls) ran out partway through. After that, most primary domains returned EGRESS_BLOCKED to WebFetch. Blocked: nasdaq.com, interactivebrokers.com, twelvedata.com, connect.euronext.com, investtech.com, diva-portal.org, core.ac.uk, centaur.reading.ac.uk, wp.lancs.ac.uk, ba-odegaard.no and docs.rs. Two hosts failed DNS: openaccess.nhh.no and api.test.nordnet.se. Many facts below therefore come from search-engine snippets and summaries of primary pages; they are marked "(search snippet)" where the full page could not be read. GitHub and raw.githubusercontent.com were readable, and exact endpoints come from open-source code there.
- Live endpoint checks: the coordinator relayed that six hosts had been allowed for curl (query1.finance.yahoo.com, www.nordnet.no, newsweb.oslobors.no, mfn.se, www.fi.se, www.finanstilsynet.no). The session's permission system (auto-mode classifier) denied the curl call, so no endpoint in these notes is "verified live 2026-10-02". Every endpoint is labelled either "unverified (seen in open-source code)" or "third-party-reported working on 2026-08-28".

## Q1. Intraday data access in 2026: what can a retail developer legally and affordably get for Oslo and Stockholm (incl. Euronext Growth Oslo and First North)?

### Takeaway
No cheap, licensed, retail-grade API delivers real-time Oslo plus Stockholm data with depth.
- **Nordnet:** shows free real-time Level 1 (and in many cases Level 2) on its own platform, but has no API for private customers. Its old nExt API client was archived in August 2024.
- **Licensed real-time feeds:** these come from broker APIs with paid per-exchange subscriptions (IBKR, Saxo; Saxo requires a separate opt-in for API market data) or from vendors (Millistream, Infront; Twelve Data only partly).
- **Low-cost options:** they are 15-minute-delayed or end-of-day: EODHD and Twelve Data lower tiers, Yahoo via yfinance (1-minute bars only about 8 days back, intraday at most 60 days), and the exchanges' own website JSON (Nasdaq `api.nasdaq.com/api/nordic/...`, Euronext `live.euronext.com/en/ajax/...`). The website endpoints are unofficial, carry ToS risk and change without notice.

### Cited Findings

#### Nordnet (Nordnet Bank AB) — platform and API
- Nordnet Norway's price list (search snippet) says streaming real-time Level 1 quotes for Norwegian stocks, ETFs and warrants are free. Level 2 (order depth) is "free for certain customer types and 715–870 NOK for others"; the snippet does not say whether that is per month or per year. — [Nordnet.no prisliste](https://www.nordnet.no/kundeservice/prisliste)
- Nordnet Denmark's real-time page says customers get free streaming real-time quotes from the Nordic exchanges, including full order depth (search snippet; the summary may merge Nordnet country sites). — [Nordnet.dk Aktiekurser i realtid](https://www.nordnet.dk/tjenester/kurser); [Nordnet.dk FAQ](https://www.nordnet.dk/faq/kursinformation-og-alarmer/aktiekurser/hvilken-kursinformation-far-jeg-pa-nordnet-dk)
- Nordnet's own FAQ "Erbjuder Nordnet API?" says Nordnet currently does **not** offer an API for private persons who want to retrieve data or automate trading. — [Nordnet.se FAQ](https://www.nordnet.se/faq/handel-vardepapper/handelsapplikationer/erbjuder-nordnet-api)
- The official `nordnet/nordnet-next-api` JavaScript client was **archived on 14 August 2024** and marked deprecated with no further development planned. — [GitHub nordnet/nordnet-next-api](https://github.com/nordnet/nordnet-next-api)
- The legacy "Nordnet External API v2" had two feeds, both newline-delimited JSON over TLS:
  - a public feed at `pub.next.nordnet.se:443` (prices and trades);
  - a private feed at `priv.next.nordnet.se:443` (orders and positions).
  - Clients had to log in before subscribing, or the connection was closed. — [DeepWiki summary of nordnet/next-api-v2-examples](https://deepwiki.com/nordnet/next-api-v2-examples/6-nordnet-api-reference); [Nordnet External API feed docs](https://api.test.nordnet.se/next/2/api-docs/docs/feeds); [docs.rs nordnet_feed](https://docs.rs/nordnet-feed/latest/nordnet_feed/)
- The `nordnet/next-api-v2-examples` repo shows no archival notice and points to `www.nordnet.se/externalapi/docs`. — [GitHub nordnet/next-api-v2-examples](https://github.com/nordnet/next-api-v2-examples)
- In this session (2026-10-02), `api.test.nordnet.se` did not resolve (getaddrinfo ENOTFOUND). This is a first-hand observation only; it may be an artefact of this environment.
- The API's overview page states that "the API service is not available for 3rd party or distribution of the software" and refers questions to tradingsupport@nordnet.se (search snippet). — [Nordnet External API overview](https://api.test.nordnet.se/); [Nordnet API användarvillkor (PDF)](https://files.nordnet.se/pdf/sv-SE/nExt-api_anvandarvillkor.pdf)
- A Home Assistant integration's README says: "Sadly Nordnet do not have a API token system or similar for private customers (unless you pay them BIG $$$!)". It therefore logs in with username and password. — [GitHub jippi/hass-nordnet](https://github.com/jippi/hass-nordnet)
- **Unofficial web endpoints** (unverified; seen in open-source code; ToS risk; login today normally needs BankID):
  - Login flow, in order:
    1. `GET https://www.nordnet.{dk|se|no|fi}/mux/login/start.html?cmpi=start-loggain&state=signin` sets `TUX-COOKIE`.
    2. `POST https://www.nordnet.{cc}/api/2/login/anonymous` sets `NOW`.
    3. `POST https://www.nordnet.{cc}/api/2/authentication/basic/login` (form fields `username`, `password`) returns an `xsrf`/`XSRF-TOKEN`.
  - Hosts and sessions: `classic.nordnet.*` is marked deprecated, and sessions last about 24 hours. — [AngelFreak/wealth_tracker auth.go](https://raw.githubusercontent.com/AngelFreak/wealth_tracker/main/internal/broker/nordnet/auth.go)
  - Stock list: `https://www.nordnet.no/api/2/instrument_search/query/stocklist?sort_attribute={X}&sort_order=desc&limit=100&offset={n}&free_text_search=&apply_filters=exchange_country%3DNO%7Cexchange_list%3Dno%3Aose`
  - Daily history: `https://www.nordnet.no/api/2/instruments/historical/prices/{instrument_id}?fields=open%2Chigh%2Clow%2Clast%2Cvolume&from={date}`
  - Headers: `client-id: NEXT`, `ntag` (updated on every response), `x-nn-href`.
  - Fields parsed: `instrument_id`, `isin`, `market_id`, `price_info.ask.price`, `price_info.bid.price`, `open/high/low/last/volume/time`. — [theBadMusician/TradingBot NordnetScraper.py](https://raw.githubusercontent.com/theBadMusician/TradingBot/master/Scrapers/NordnetScraper.py)

#### Nasdaq Nordic (Stockholm, Helsinki, Copenhagen, First North) — licensing and public endpoints
- Nasdaq European Markets Exchange Data Price List v4.5. The URL is labelled January 2026; the search summary called it "updated September 2025", and an April 2026 edition also exists. Non-professional display fees, per subscriber per month:

  | Product | Fee |
  |---|---|
  | Nordic Equity TotalView | €11.17 |
  | Nordic Equity Level 2 | €5.64 |
  | Nordic Equity Level 1 | €1.13 |
  | Nordic & Baltic Equity Last Sale | €0.67 |
  | Non-professional distribution | €1,165/month |
  | Hosted L1 & L2 licence (non-pro) | €835 per hosted firm |
  | Managed Data Solution (non-pro) | €578/month distributor fee + €22.30 per recipient |

  Source: search snippet. — [Nasdaq price list v4.5](https://www.nasdaq.com/docs/Nasdaq_European_Exchange_Market_Data_Price_List_January_2026); [April 2026 edition](https://www.nasdaq.com/docs/Nasdaq_European_Exchange_Market_Data_Price_List_April_2026)
- **Public website JSON API** (unofficial; unverified by me):
  - Screener, main market: `https://api.nasdaq.com/api/nordic/screener/shares?category=MAIN_MARKET&tableonly=true&page=1&size=1000&segment=LARGE_CAP&segment=MID_CAP&segment=SPAC&segment=SMALL_CAP&lang=en`
  - Screener, First North: `...?category=FIRST_NORTH&tableonly=true&page=1&size=1000&lang=en`
  - Daily chart: `https://api.nasdaq.com/api/nordic/instruments/{id}/chart?assetClass=SHARES&fromDate=1986-01-01&toDate={today}&lang=en`
  - Requests use a browser User-Agent; chart requests add `X-Requested-With: XMLHttpRequest`. — [hampusadamsson/nasdaq-stock-retriever client.go](https://raw.githubusercontent.com/hampusadamsson/nasdaq-stock-retriever/master/client.go)
  - Index constituents: `https://api.nasdaq.com/api/nordic/instruments/FI0008900212/index-children?&lang=en`. — [diman199888/quantitative-finance script.py](https://github.com/diman199888/quantitative-finance/blob/7d296ab8f11789fabc7412d00e282b75c3b71f41/script/script.py)
- **Third-party test dated 2026-08-28** (Swedish open-source project):
  - The screener works GET-only; POST returns 403 from an Akamai WAF.
  - Market codes are `STO`, `HEL`, `CPH`, `ICE`. Row counts: STO Main 411, STO First North 332, HEL 147, CPH 118, ICE 27.
  - Fields include symbol, ISIN, lastSalePrice, volume, turnover and sector.
  - The old `nasdaqomxnordic.com/shares/listed-companies/*` pages redirect to `nasdaq.com/european-market-activity/shares`, and the `?download=1` CSV endpoints are dead.
  - The same repo contradicts itself on Oslo: one file says `OSL` is not available because Oslo Børs is separate; another lists "OSL 400". — [hankkontakt/marketscan datatest-publik-norden.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/datatest-publik-norden.md); [RAPPORT_DATASYSTEM_2026-08-28.md](https://raw.githubusercontent.com/hankkontakt/marketscan/master/RAPPORT_DATASYSTEM_2026-08-28.md)

#### Euronext (Oslo Børs / Euronext Expand Oslo / Euronext Growth Oslo) — licensing and public endpoints
- Euronext says real-time data can be used internally but is usually fee-liable. For some real-time products "a lower fee is available if you are a retail client". An Information Product Fee Schedule effective 1 January 2026 exists, and Oslo Børs contracts and price lists sit on Connect2. — [Euronext Market Data Fees and Policies](https://www.euronext.com/en/data/market-data/market-data-pricing-policies); [Oslo Børs Contracts & Price List](https://connect2.euronext.com/en/data/oslo-bors-contracts-price-list)
- A search snippet of the January 2026 fee schedule quoted "€1,792.835 per month" as a non-professional Level 1 figure for the Continental Cash consolidated pack. This is almost certainly a distributor-level fee, not a per-user fee. The Oslo per-user retail fee could not be read (blocked). — [Product Fee Schedule Jan 2026 (compare doc)](https://connect.euronext.com/sites/default/files/documentation/data/Compare%20Document%20-%20Product%20Fee%20Schedule%20(effective%20January%202026).pdf)
- MIC codes: Oslo Børs `XOSL`, Euronext Growth Oslo `MERK`, Euronext Expand Oslo `XOAS`. All three use the Yahoo suffix `.OL`. — [IvanAnikin/InvestingBuddy directories.py](https://github.com/IvanAnikin/InvestingBuddy/blob/d29f1e133554d61c2ef4879b6538e013a9ac6439/apps/api/app/services/discovery/directories.py)
- **Unofficial live.euronext.com AJAX endpoints** (unverified; live.euronext.com is blocked in this environment):
  - `GET https://live.euronext.com/en/ajax/getIntradayPriceFilteredData/{ISIN}-XOSL?nbitems=1` returns intraday trade rows with `rows[].price` and `rows[].time`. — [jorgtron/tekinvestorstock update_stocks.rb](https://raw.githubusercontent.com/jorgtron/tekinvestorstock/master/app/jobs/scheduled/update_stocks.rb)
  - `POST https://live.euronext.com/en/ajax/AwlHistoricalPrice/getFullDownloadAjax/{ISIN}-XOSL` with form body `format=csv&decimal_separator=.&date_form=d/m/Y&startdate=...&enddate=...` returns a daily CSV. — [enzanto/stockfinder market_screener.py](https://github.com/enzanto/stockfinder/blob/7c8972e643b46fd994fc31e28354b10d601a9ea8/screener/market_screener.py)
  - `.../ajax/getFactsheetInfoBlock/STOCK/{isin}-{mic}/fs_tradinginfo_block` and `.../ajax/getIndexCompositionFull/NO0007035327-XOSL`. — [InvestingBuddy](https://github.com/IvanAnikin/InvestingBuddy/blob/d29f1e133554d61c2ef4879b6538e013a9ac6439/apps/api/app/services/discovery/directories.py); [LNTR/list_extraction_upwork](https://github.com/LNTR/list_extraction_upwork/blob/577b68ef7f20d02bdedfb6f9331b9a581514c2c2/Week1/py/90.0127.py)
- **Oslo Børs NewsWeb** (third-party test, 2026-08-28):
  - Every path returns a 3,715-byte React single-page shell.
  - The JS bundle reveals `/obsvc/` and `/v1/newsreader/{env,message,announcement,issuers,search}`.
  - The production API host `obns-api.euronext.cloud` did not resolve on the tester's machine, so it is not scriptable over plain HTTP. — [hankkontakt datatest-publik-norden.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/datatest-publik-norden.md)

#### Millistream (Millistream Market Data AB, Stockholm)
- Millistream offers a streaming "Market Data Feed" API with real-time and historical prices, corporate actions, fundamentals and news. It also offers a RESTful API and widgets. API prices are not public; the FAQ says any minimum spend depends on delivery mechanism and content. — [Millistream API/Widgets/Trader](https://millistream.com/index.php/api-widgets-trader/); [Millistream home](https://millistream.com/)
- A "Trader" plan for private investors costs 549 SEK/month and includes real-time equities for Sweden, Denmark and Finland. Norway is not mentioned (search snippet; aggregator-sourced). — [SaaSBrowser Millistream](https://saasbrowser.com/en/saas/542379/millistream); [Millistream](https://millistream.com/)
- Protocol details:
  - The feed uses the MDF protocol through the native C library `libmdf` (Linux, macOS, Windows).
  - Sandbox: `sandbox.millistream.com:9100` with user and password `sandbox`.
  - Messages: `MDF_M_LOGON` (`MDF_F_USERNAME`, `MDF_F_PASSWORD`), then `MDF_M_LOGONGREETING`, then `MDF_M_REQUEST` with request classes `MDF_RC_BASICDATA` and `MDF_RC_QUOTE`.
  - Request type `MDF_RT_FULL` means image plus streaming. — [mgnsm/Millistream.NET](https://github.com/mgnsm/Millistream.NET)
- Stamdata and Millistream formed a data-distribution partnership (Nordic bonds). — [Nordic Trustee](https://nordictrustee.com/stamdata-millistream-forms-a-new-strategic-data-distribution-partnership/)

#### Twelve Data
- Individual plans are Basic (free), Grow, Pro and Ultra. Search snippets give conflicting prices: "$79 / $229 / $999" versus "Grow from $29/month" and "Pro from $99/month". Annual billing is 17% off. Ultra includes "70+ markets, real-time EU market data". "Cboe Europe real-time data for all major European stocks is now live" (search snippets). — [Twelve Data pricing](https://twelvedata.com/pricing); [Twelve Data March 2026 updates](https://twelvedata.com/news/march-2026-updates)
- Delay for Oslo is contradictory. The XOSL exchange page shows delay "–" and hours "M-F 09:00–16:20". Pricing documentation lists Norway as "15 minute delay" (search snippet). — [Twelve Data XOSL](https://twelvedata.com/exchanges/xosl)
- REST API (unverified for Nordic symbols):
  - Base URL `https://api.twelvedata.com/`.
  - `time_series` parameters: `symbol`, `interval` (1min, 5min, 15min, 30min, 45min, 1h, 2h, 4h, 8h, 1day, 1week, 1month), `exchange`, `mic_code`, `outputsize`, `start_date`/`end_date`.
  - "WebSockets are only available for Twelve Data users on the Pro plan and above." — [twelvedata-python README](https://github.com/twelvedata/twelvedata-python)

#### EODHD (EOD Historical Data)
- Intraday API: OHLCV bars at 1-minute to 1-hour intervals. For non-US exchanges, 5-minute and 1-hour bars go back to October 2020. Intraday data is delayed and "finalized about 2–3 hours after the market close". — [EODHD Intraday API](https://eodhd.com/financial-apis/intraday-historical-data-api)
- WebSockets (<50 ms) cover only US stocks, forex and crypto. Other exchanges get delayed "live" data (15–20 minutes). Intraday is sold in the "All World Extended" and "All-In-One" packages (2026 price not retrieved). — [EODHD home](https://eodhd.com/); [Live (Delayed) API](https://eodhd.com/financial-apis/live-ohlcv-stocks-api); [EODHD pricing](https://eodhd.com/pricing); [EODHD exchange OL](https://eodhd.com/exchange/OL)
- A third-party test (2026-08-28) reports: free tier 20 calls/day; "no First North in exchange list"; returns 401 without a key. The First North claim is unverified. — [hankkontakt RAPPORT_DATASYSTEM_2026-08-28.md](https://raw.githubusercontent.com/hankkontakt/marketscan/master/RAPPORT_DATASYSTEM_2026-08-28.md)

#### Interactive Brokers (TWS / IB Gateway API)
- An IBKR pricing snippet lists a "Market Data Package for Oslo Bors (L1, L2)" at Non-Pro "N/A" and Pro EUR 39.50/month. This is ambiguous: "N/A" may mean no separate non-pro package. Subscriptions are not pro-rated, so subscribing mid-month costs the full month. — [IBKR Market Data Pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)
- An open-source IBKR implementation document says:
  - "There is **no free real-time exchange data** at IBKR". Per-exchange real-time subscriptions cost "roughly USD 4–20/exchange/month, waivable with commissions for some".
  - Delayed data is available with `reqMarketDataType(3)`.
  - A Stockholm contract is written `Stock('VOLV-B', 'SFB', 'SEK')`. — [eddydarell/ClariFi IBKR_IMPLEMENTATION.md](https://raw.githubusercontent.com/eddydarell/ClariFi/270f4b6e51fb6c5d21500fd4a8a45f86424f64de/docs/IBKR_IMPLEMENTATION.md)

#### Saxo Bank OpenAPI (Danish broker; serves NO/SE/DK/FI clients)
- Access and subscriptions:
  - FX prices are always real-time; other asset types need a market-data subscription.
  - Real-time data works only in the LIVE environment.
  - Market data is disabled by default for non-FX instruments in third-party (OpenAPI) apps. You must request access and accept terms.
  - Nasdaq OMX Nordic Equities subscriptions are offered to Professional and Private clients, "starting at 47.00 EUR for Level 1 Professional". — [Saxo: How do I enable market data](https://openapi.help.saxo/hc/en-us/articles/4418427366289-How-do-I-enable-market-data); [Why are quotes still delayed](https://openapi.help.saxo/hc/en-us/articles/4416934340625-Why-are-quotes-still-delayed-after-I-subscribe-to-market-data); [Saxo market data subscriptions](https://www.home.saxo/products/market-data-subscriptions)
- Endpoints and auth (from developer notes and code; unverified):
  - SIM base `https://gateway.saxobank.com/sim/openapi/`; LIVE base `https://gateway.saxobank.com/openapi/`.
  - OAuth via `https://{sim|live}.logonvalidation.net/authorize|token` (PKCE).
  - **`/chart/v1/charts` was deprecated in February 2025** and now returns an HTML 404. Use `/chart/v3/charts` with parameters `AssetType`, `Uic`, `Count`, and `Horizon` (minutes per bar).
  - SIM tokens often expire after a few hours, and SIM credentials lapse after about 20 days of inactivity. — [torbenboeck/snapd-invest saxo-openapi-notes.md](https://raw.githubusercontent.com/torbenboeck/snapd-invest/23f32dba95715cdeea6171125c2edee4576dd21a/docs/integrations/saxo-openapi-notes.md); [neurallayer/roboquant saxo.py](https://github.com/neurallayer/roboquant.py/blob/b40d70bee9eb01348c80d3a9fdf04b2959f65051/roboquant/brokers/saxo.py); [tikeda123/saxo_db saxo_client.py](https://github.com/tikeda123/saxo_db/blob/6e93db521c27a50d38af80702aaf3ca5cd77896f/market_db/saxo_client.py)
- Rate limits are counted per "service group", meaning the first path segment (`chart`, `port`, ...). — [simonellefsen/saxo-daytrader-rust saxo_rate_limit.rs](https://github.com/simonellefsen/saxo-daytrader-rust/blob/91aa053a59e3535114fc82b45af5fedd530a3d91/src/saxo_rate_limit.rs)

#### TradingView
- Oslo Børs real-time stock and index data can be bought by paid-plan holders; delayed data is free to all users. — [TradingView blog: OSE, OMX data](https://www.tradingview.com/blog/en/data-tradingview-ose-omx-well-known-nasdaq-indices-7623/); [How to purchase additional market data](https://www.tradingview.com/support/solutions/43000471705-how-to-purchase-additional-market-data/)
- A secondary source says TradingView real-time exchange add-ons cost about $2–$10 per exchange per month. The Oslo and Nasdaq Nordic prices were not retrieved. — [FinancialTechWiz (secondary)](https://www.financialtechwiz.com/post/tradingview-real-time-data/)

#### Yahoo Finance (via yfinance; unofficial)
- The yfinance docstring lists valid intervals `1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo` and says "Intraday data cannot extend last 60 days". It also notes that "30m data is fetched from Yahoo as 15m then resampled, to work around a Yahoo API bug". — [yfinance multi.py](https://github.com/ranaroussi/yfinance/blob/5cae563642b59f49adf6a04a5ad6744f8b0e084d/yfinance/multi.py)
- Default lookback windows when `period="max"`:

  | Interval | Lookback |
  |---|---|
  | `1m` | 8 days (`end - 691200`) |
  | `2m`, `5m`, `15m`, `30m`, `90m` | 60 days |
  | `1h`, `60m` | 730 days |

  The repair code rejects 1h data older than 729 days and 30m/15m data older than 59 days. — [yfinance history.py](https://raw.githubusercontent.com/ranaroussi/yfinance/main/yfinance/scrapers/history.py)
  - Caveat: the 8-day figure is yfinance's default window for `period="max"` at 1m. It is commonly said that Yahoo serves 1m bars up to about 30 days back if requested in windows of 8 days or less; this was not verified here.
- A third-party test (2026-08-28) found yfinance 1.4.1 working for 10 Nordic tickers. `earningsDate` is always null; use `earningsTimestamp` instead. — [hankkontakt RAPPORT](https://raw.githubusercontent.com/hankkontakt/marketscan/master/RAPPORT_DATASYSTEM_2026-08-28.md)
- `query1.finance.yahoo.com/v8/finance/chart/{EQNR.OL|VOLV-B.ST}` was **not** verified live: the curl call was denied by this session's permission system.

#### Other Nordic retail sources (changes noted)
- **Börsdata:** its API needs a "Pro+" subscription at €59/month since 2025-02-01. Per the tester, the ToS forbids "external systems displaying API data", and `rest.borsdata.se` returns 403 (Cloudflare) without a key. — [hankkontakt RAPPORT](https://raw.githubusercontent.com/hankkontakt/marketscan/master/RAPPORT_DATASYSTEM_2026-08-28.md)
- **Avanza (unofficial):** `avanza.se/api/market-guide/stock/{id}` and `/price-chart` work without a key, but the format changed to `timePeriod=one_week|one_month|…` with `resolution=day`. ToS risk applies. — [same](https://raw.githubusercontent.com/hankkontakt/marketscan/master/RAPPORT_DATASYSTEM_2026-08-28.md)

### Inferences
- For the app (periodic gathering plus suggestions on button click, not automated execution), 15-minute-delayed intraday data plus daily OHLCV is enough for signals with horizons of 1 day to 2 weeks. True intraday signals, such as "first half-hour predicts last half-hour", need real-time data in the final hour: about 15:50 CET for Oslo and 16:55 CET for Stockholm. The user would then execute manually on Nordnet, where real-time L1 is free.
- The cheapest legal real-time path for automated collection is a broker API with a personal non-professional subscription (IBKR or Saxo). The underlying Nasdaq non-pro L1 fee is only €1.13 per user per month, but you must take it through a licensed distributor. Euronext Oslo retail fees could not be confirmed.
- Twelve Data's "real-time EU" comes from Cboe Europe. For Oslo and Stockholm names it would reflect Cboe's MTF trades and quotes, not the primary-market (XOSL/XSTO) book or auctions. This is unverified, and it matters for auction-based signals.
- Scraping Nordnet, Euronext or Nasdaq website JSON works technically (per open-source code). However:
  - it is unofficial and can break without notice; Nasdaq Nordic and Avanza both changed formats in 2025–2026;
  - Nordnet login now needs BankID-type authentication, and the `classic.nordnet` host is deprecated;
  - storage and redistribution rights are unclear.
- For a private, single-user app, low-frequency polling is the least risky use, but it is not licensed.
- Euronext Growth Oslo (`MERK`) and First North names appear to be covered by the website endpoints (Nasdaq First North in the screener) and by Yahoo `.OL`/`.ST` tickers. EODHD's First North coverage is disputed.
- Hosts the user may need to allowlist to test further: `api.nasdaq.com`, `live.euronext.com` (currently blocked), `obns-api.euronext.cloud` (NewsWeb API), `eodhd.com`, `api.twelvedata.com`, `gateway.saxobank.com`, `connect.euronext.com`/`connect2.euronext.com` (fee schedules) and `www.nasdaq.com` (price lists).

### Gaps
- Exact Euronext Oslo per-user non-professional real-time fees (L1 and L2) for 2026: the fee schedules are on connect.euronext.com, which is blocked.
- Exact IBKR non-pro prices for "Nordic Equity" and "Oslo Børs" bundles, the IBKR exchange code for Oslo (believed to be `OSE`, unverified), and IBKR historical-bar pacing limits.
- Saxo private-client prices for Nordic and Oslo L1/L2.
- Infront retail and API pricing, and the Millistream API price: nothing retrieved.
- Twelve Data: exact 2026 plan prices and whether XOSL/XSTO are real-time or 15-minute-delayed on each plan (sources conflict).
- Yahoo's ToS for automated collection and storage was not retrieved. Whether Yahoo's Oslo and Stockholm quotes are delayed, and by how much, was not verified live (curl denied).
- No intraday-trades endpoint on `api.nasdaq.com/api/nordic` was found in open-source code. Nasdaq's public-site delay (assumed 15 minutes) is unverified.
- Whether Nordnet's legacy External API still serves any (e.g., professional) customers in 2026, and when private access formally closed: only the FAQ statement and the 2024 repo archive date were found.

## Q2. Which short-horizon signals (intraday to ~2 weeks) have credible evidence in Nordic markets, net of costs?

### Takeaway
Nordic-specific peer-reviewed evidence for intraday and short-horizon signals is thin. Most evidence is US or international; Nordic evidence comes mainly from master's theses and vendor research.
- **Intraday momentum:** internationally robust, but a Stockholm thesis found it did not beat a naive mean out of sample.
- **Short-term reversal:** exists in Nordic monthly data before costs.
- **Oslo earnings announcements:** move prices on the announcement day and the day after, with little drift.
- **Technical-analysis rules:** Nordic studies find gains erased by transaction costs.
- **Investtech:** reports roughly 0.8 percentage points of one-month excess return for trend signals, before costs.

None of these is clearly profitable after Nordnet retail costs at short holding periods.

### Cited Findings

#### Intraday momentum
- Gao, Han, Li and Zhou (Journal of Financial Economics, 2018) find that the market's first half-hour return, including the overnight move, predicts the last half-hour return (US evidence). — [ScienceDirect: Market intraday momentum](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351); [author PDF](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf)
- Li, Sakkas and Urquhart (Journal of Financial Markets, 2022) study intraday time-series momentum in 16 developed markets using high-frequency data.
  - The effect "is economically sizable and statistically significant both in- and out-of-sample in most countries".
  - It is stronger when liquidity is low, volatility is high and information arrives discretely.
  - A search snippet adds that predictability is significant in 12 of 16 markets, and that the US first half-hour return predicts other markets' last half-hour returns. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S138641812100001X); [accepted version](https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf); [SSRN](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3762700_code2938409.pdf?abstractid=3460965&mirid=1)
- A Swedish master's thesis (DiVA) tests whether the first half-hour (including overnight) predicts the last half-hour for OMXS30 and five constituents: ABB, Investor B, Nordea, SBB B and Sinch.
  - It finds "some degree of predictability" in-sample.
  - But out-of-sample R² is **negative** for ABB, Investor, Nordea and OMXS30, meaning the model does worse than the historical mean (search snippet). — [DiVA: Intraday Momentum and Return Predictability](https://www.diva-portal.org/smash/get/diva2:1878991/FULLTEXT01.pdf)
- A European-market study (Klagenfurt) reports that intraday time-series momentum exists in European stock markets (search snippet). — [Universität Klagenfurt netlibrary](https://netlibrary.aau.at/obvuklhs/download/pdf/7301728)

#### Overnight vs intraday returns
- Lou, Polk and Skouras ("A Tug of War"): stocks with high overnight returns over the past month keep having high overnight returns, and relatively low intraday returns, the next month. Momentum profits accrue overnight, while other anomalies accrue intraday. — [LSE PDF](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)
- Premiums for profitability, investment, beta, idiosyncratic volatility, equity issuance, discretionary accruals and turnover occur intraday. Beta is positively priced overnight and negatively priced intraday. — [JFE 2021: The cross-section of intraday and overnight returns](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21000854)
- An international overnight-return anomaly study exists, but its Nordic results were not retrieved. — [ResearchGate](https://www.researchgate.net/publication/228456751_The_International_Evidence_of_the_Overnight_Return_Anomaly)

#### Short-term reversal
- General (mostly US) evidence: last week's winners return about −0.35% to −0.55% the next week, and last week's losers about +0.86% to +1.24%. Results depend on volume, turnover and volatility. — [Quantpedia](https://quantpedia.com/strategies/short-term-reversal-in-stocks); [Alpha Architect](https://alphaarchitect.com/how-volatility-and-turnover-affect-return-reversals/); [JBF 2021: Short-term reversals, short-term momentum, and news-driven trading](https://www.sciencedirect.com/science/article/abs/pii/S0378426621000261)
- **Nordic:** an Aalto master's thesis (Davis-Kerppola, 2023) uses monthly returns for all Nordic listed companies from 1995 to 2022. It finds a short-term contrarian strategy earns positive abnormal returns, plus size and January effects in mid-length formation periods. Cost treatment was not captured. — [Aaltodoc: Betting against the Nordic market](https://aaltodoc.aalto.fi/items/bf3e55af-8821-4dd7-a168-72e458958557)

#### Earnings announcements / announcement drift
- **Oslo:** a CBS thesis studies OSEBX constituents' quarterly reports from 2013 to 2016. It finds significant abnormal returns on the announcement day and the following day, but "no large signs of a delayed stock price response", i.e. no meaningful post-earnings drift. — [CBS student project](https://research.cbs.dk/da/studentProjects/ef598439-563b-45f1-9c6d-3853655cdbc9/)

#### Technical analysis
- A University of Vaasa thesis on Nordic technical rules finds strong sensitivity to costs: simulated higher transaction costs produce negative returns for short sales in Helsinki, Oslo and Stockholm. A "two-week time span" appeared profitable when the 200-day moving average is declining (search snippet). — [Vaasa thesis (CORE)](https://core.ac.uk/download/pdf/197964347.pdf)
- An NHH thesis, "Backtesting trading strategies on the Oslo Stock Exchange", finds that strategies replacing more than two stocks per month incurred high transaction costs (search snippet). — [NHH Open Access](https://openaccess.nhh.no/nhh-xmlui/bitstream/handle/11250/2989509/masterthesis.pdf?sequence=1)
- **Investtech (vendor):**
  - The study covers Norwegian, Swedish, Danish and Finnish stocks from 1996 to 2018.
  - A buy signal is the first day a stock enters a rising trend, or any day in a rising trend more than 22 days after the previous signal.
  - Stocks in short-term rising trends gained 1.8% on average over one month, 0.8 percentage points more than the benchmark (Investtech annualises this to 10.1 points).
  - In Norway, stocks after buy signals returned 2.7% after one month and 20.0% after 12 months, against 1.0% and 12.3% for the exchange average.
  - Investtech says its statistics show high significance. — [Investtech: Excess return from stocks in rising trends](https://www.investtech.com/us/market.php?CountryID=993&fn=wpArticle&p=staticPage&tbReport=tbib_rising_2019art); [Investtech research summary](https://www.investtech.com/main/market.php?CountryID=1000&p=staticPage&fn=tbib&tbReport=tbib_summary)
- Investtech also publishes "strong excess return following buy signals from rectangle formations" for Nordic stocks; the numbers were not retrieved. — [Investtech rectangle report](https://www.investtech.com/main/market.php?CountryID=993&p=staticPage&fn=wpArticle&tbReport=r2019_RecBuyNordicArt)

### Inferences
- **Investtech claims should be treated as gross, in-sample, vendor-selected results.** The pages retrieved give no transaction costs. Signals overlap (a new signal is allowed after 22 days), so observations are not independent. Benchmarks are equal-weighted market averages, and there is no out-of-sample or multiple-testing correction. A 0.8-point one-month excess is roughly equal to one Nordnet Mini round trip plus a small-cap spread (see Q3).
- **Intraday momentum** is the best-documented intraday effect internationally, but it is a market-level, index-timing signal measured in basis points. The Stockholm thesis's negative out-of-sample R² suggests it is weak or absent in OMXS30 large caps. It should be logged and evaluated, not traded, unless the app's own logged predictions show an edge after costs.
- **Short-term reversal** in Nordic data is plausible but most likely concentrated in small, illiquid names where spreads (often 100+ bps) and the Nordnet minimum fee consume it.
- **Event signals** (earnings and announcements) in Oslo appear to resolve in about two days. A pre-open release (07:00–08:00 CET) mainly creates a gap that the 09:00 opening auction absorbs, so retail trade after the open is late. Only a "post-announcement continuation for 1–2 days" signal has even weak support (CBS thesis).
- **A realistic sleeve design:** fewer trades, 2–10 trading-day holds, liquid large and mid caps, and limit or auction orders. Every prediction should be logged with gross and net-of-cost outcomes so the formula is judged after costs.

### Gaps
- No retrieved Nordic study (searches ran out) on:
  - ex-dividend-day price behaviour on Oslo Børs;
  - OBX/OSEBX/OMXS30 index-rebalance effects;
  - closing-auction price reversals;
  - opening-gap fading or continuation;
  - abnormal-volume spikes;
  - intraday reaction to pre-open (07:00–08:00) announcements.

  All of these remain open.
- Whether Sweden or Norway are among Li, Sakkas and Urquhart's 16 markets, and their country-level results: the full text was blocked.
- Investtech's Sweden-specific numbers, its out-of-sample updates after 2018, and any independent NHH/BI/SSE replication of Investtech signals: none found.
- The Aalto and Vaasa theses' net-of-cost figures and exact magnitudes: the full texts were blocked.
- BI/NHH theses on Oslo intraday patterns: none retrieved.

## Q3. Costs and feasibility: Nordnet commissions, spreads, tick sizes, retail day-trader outcomes, and break-even edge

### Takeaway
For small accounts, Nordnet's minimum fees dominate costs: 1 SEK on Swedish Mini (0.25%) and 29 NOK on Norwegian Mini (0.15%).
- **Round-trip commission** is about 0.3–0.8% for 10,000–30,000 positions.
- **Spread crossing** adds roughly 0.1–0.2% for large caps and over 1% for small caps.
- **Evidence from large datasets (Taiwan, Brazil):** fewer than 1% of day traders are predictably profitable, and 97% of persistent day traders lose money.

A short-term sleeve therefore needs a gross edge of roughly 0.5–0.7% per round trip in large caps, and around 2% in small caps, just to break even.

### Cited Findings

#### Nordnet commission (courtage), 2026
- **Sweden** (nordnet.se price list, search snippet):

  | Class | Rate (Nordic markets) | Minimum | Best for orders of |
  |---|---|---|---|
  | Mini | 0.25% | 1 SEK | up to 15,600 SEK |
  | Liten | 0.15% | 39 SEK | 15,600–46,000 SEK |
  | Mellan | 0.069% | 69 SEK | 46,000–143,478 SEK |
  | Fast | 99 SEK flat | — | over 143,478 SEK |

  New customers trade Nordic exchanges free until 30 June 2027, then move to Mini. — [Nordnet.se prislista](https://www.nordnet.se/kundservice/prislista); [ISK-guiden: Nordnet 2026](https://isk-guiden.se/maklare/nordnet/); [Nordnet FAQ: Vilka courtageklasser finns](https://www.nordnet.se/faq/courtage-avgifter/courtage/vilken-courtageklass-passar-mig-bast)
- **Norway** (aggregator, search snippet):
  - Mini: 0.15%, minimum 29 NOK for Nordic trades, best below 52,667 NOK per trade.
  - Normal: 0.049%, minimum 79 NOK.
  - Activity-based classes are also reported: "Bonus" (minimum 69 NOK, 0.04%, more than 15 trades/month) and "VIP" (minimum 39 NOK, 0.035%, more than 30 trades/month).
  - The same summary also says "Mini from 39 NOK", which conflicts with 29 NOK. An older Nordnet press release announced a minimum cut to 39 NOK. — [Nordinnsikt: Nordnet anmeldelse 2026](https://nordinnsikt.no/meglere/nordnet/); [Nordnet FAQ: kurtasjeklasse MINI](https://www.nordnet.no/faq/priser/kurtasje/hvordan-endrer-jeg-til-kurtajeklasse-mini); [Egenkapitalen: kurtasje](https://egenkapitalen.no/kurtasje/); [Nordnet press release "Prisbombe"](https://nordnetab.com/press_release/prisbombe-minstekurtasjen-senkes-til-39-kroner/)
  - The 52,667 NOK break-even matches 79 NOK ÷ 0.15%, which supports the 0.15% Mini / 79 NOK Normal pairing.

#### Spreads and tick sizes
- Cross-country evidence: average bid-ask spreads are 148 bps for small stocks, 41 bps for medium and 17 bps for large, and the size–spread relation holds in all sample countries. — [BIS Working Paper 1229](https://www.bis.org/publ/work1229.pdf)
- A generic source says large caps often trade at 15 bps or less, while small caps can exceed 500 bps. — [Stockopedia](https://www.stockopedia.com/ratios/bid-ask-spread-5063/)
- Oslo-specific spread statistics by size: B.A. Ødegaard (BI) maintains lecture notes on spread measures, dated 16 September 2026, that cover the Oslo Stock Exchange. The content could not be read (blocked). — [Ødegaard: Trading costs – spread measures](https://ba-odegaard.no/teach/notes/liquidity_estimators/spread/spread_lectures.pdf)
- **MiFID II tick sizes** (RTS 11, Delegated Regulation (EU) 2017/588): the minimum tick depends on price and on the instrument's average daily number of transactions (ADNT) on its most liquid EU market. There are six liquidity bands (ADNT <10; 10–80; 80–600; 600–2,000; 2,000–9,000; ≥9,000) crossed with price ranges, recalibrated annually. — [European Commission RTS 11](https://ec.europa.eu/finance/securities/docs/isd/mifid/rts/160714-rts-11_en.pdf); [ESMA final report on RTS 11 amendments](https://www.esma.europa.eu/sites/default/files/library/esma70-156-834_final_report_on_the_proposed_amendments_to_rts_11.pdf); [AMF: Impact of the new tick size regime](https://www.amf-france.org/sites/institutionnel/files/contenu_simple/lettre_ou_cahier/risques_tendances/MiFID%20II%20Impact%20of%20the%20New%20Tick%20Size%20Regime.pdf)

#### Retail day-trader outcomes
- Barber, Lee, Liu and Odean use complete Taiwan Stock Exchange data from 1992 to 2006. They estimate that fewer than 1% of individuals who day trade over a year are predictably profitable. — [The Cross-Section of Speculator Skill (PDF)](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf); [Do Day Traders Rationally Learn About Their Ability?](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf)
- A secondary summary says Taiwan day traders lost an average of 23.9 bps per day net of fees across 3.7 billion transactions. This is unverified against the paper. — [Tradicted summary](https://www.tradicted.com/research/barber-learning-2020/)
- Chague, De-Losso and Giovannetti studied everyone who began day trading Brazilian equity mini-index futures in 2013–2015.
  - Of those who persisted 300 or more days, 97% lost money.
  - Only 1.1% earned more than the minimum wage, and only 0.5% more than a bank teller's starting salary.
  - The best trader earned about US$310/day with a standard deviation of US$2,560.
  - They found no evidence of learning. — [SSRN: Day Trading for a Living?](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)
- **Nordic:** Sweden's FI has published analysis of trading behaviour, e.g. FI-analys 42 on women's and men's behaviour on the stock market; its findings were not retrieved. An affiliate site claims "according to Finansinspektionen, fewer than 15% of Swedish private active short-term traders maintain continuous profit over three years", but gives no primary citation, so treat it as unreliable. — [FI-analys 42 (PDF)](https://www.fi.se/contentassets/21a10d76e3f149aa95f62ecfeead9b60/fi-analys-42-kvinnors-och-mans-beteende-pa-borsen.pdf); [MarketMate (unreliable)](https://www.marketmate.se/utbildning/statistik/daytrading/)

### Inferences
- **Break-even arithmetic.** Commission uses the classes above; for a market-order round trip, assume you pay about one full quoted spread (half on entry, half on exit), using BIS averages of 17, 41 and 148 bps.

  | Account | Position | Class | Commission per side | Round-trip commission | + large-cap spread | + small-cap spread |
  |---|---|---|---|---|---|---|
  | Sweden | 10,000 SEK | Mini | 25 SEK | 0.50% | ≈0.67% | ≈2.0% |
  | Sweden | 10,000 SEK | Liten | 39 SEK (minimum) | 0.78% | — | — |
  | Sweden | 30,000 SEK | Liten | 45 SEK | 0.30% | ≈0.47% | — |
  | Sweden | 100,000 SEK | Mellan | 69 SEK | 0.138% | ≈0.31% | — |
  | Norway | 10,000 NOK | Mini | 29 NOK (minimum) | 0.58% | ≈0.75% | ≈2.1% |
  | Norway | 20,000 NOK | Mini | 30 NOK | 0.30% | ≈0.47% | — |
  | Norway | 100,000 NOK | Normal | 79 NOK (minimum) | 0.158% | ≈0.33% | — |

  So a 50,000–100,000 account split into 3–5 positions faces about 0.5–0.8% round-trip cost in liquid names and about 2% in small caps or growth markets (Euronext Growth Oslo, First North).
- **Cost drag compounds.** Two round trips per week at about 0.6% each is about 1.2% per week, or about 60% per year of traded capital before any edge. This is the core reason the day-trading sleeve needs low turnover.
- **Tick constraint.** For low-priced or illiquid stocks the tick can force a wide minimum spread: if a stock trades at 2.00 with a 0.01 tick, one tick is 50 bps. The app should compute tick/price per instrument and exclude names where one tick exceeds the signal's expected edge.
- **Limit orders, or joining the opening and closing auctions, can avoid paying the spread**, at the cost of non-fills and adverse selection. The app should model both cases.
- **Large-scale evidence implies the prior for a retail short-term sleeve is negative net alpha.** The logging and evaluation loop should treat "no trade" as the benchmark.

### Gaps
- Nordnet Norway's exact 2026 class table: there are conflicting 29 versus 39 NOK minimums, and whether Bonus and VIP classes still exist. Primary page blocked.
- Whether Nordnet has an "active trader" pricing class in Sweden in 2026: only the four standard classes were found.
- Oslo- and Stockholm-specific spreads by market-cap segment for 2025–2026, and Nordic market-impact estimates for retail order sizes.
- Nordic regulator studies (Finanstilsynet, FI) quantifying retail day-trader losses in equities. Most cited regulator figures concern CFDs.

## Q4. Market-structure facts the app needs: hours and auctions, volatility interruptions, short selling, settlement, PDT-type rules, tax wrappers

### Takeaway
- **Stockholm (INET Nordic):** pre-open 08:00, opening auction uncross 09:00, continuous trading 09:00–17:25, closing call 17:25–17:30.
- **Oslo (Euronext Optiq):** continuous trading until 16:20, then a closing auction uncrossing about 16:25. Sources disagree on the exact opening and closing auction times.
- **Settlement:** EU moves from T+2 to T+1 on 11 October 2027.
- **Short selling:** Nordnet lets approved retail customers short Nordic shares in ordinary accounts (not ISK or ASK). Intraday shorts cost only commission.
- **PDT-type rules:** none found for the EU/EEA.
- **Tax wrappers:**
  - Sweden's ISK taxes capital, not trades: 2026 tax-free level 300,000 SEK, effective 1.065% on the excess.
  - Norway's ASK defers tax at 37.84% on gains, but today excludes Euronext Growth shares. Inclusion is proposed from 1 January 2027.

### Cited Findings

#### Trading hours and auctions
- **Nasdaq Stockholm (INET Nordic) equities:** pre-open 08:00; opening uncross 09:00; continuous trading 09:00–17:25; pre-close 17:25; closing uncross 17:30; post-trade 17:30; closed 18:00–08:00. — [Nasdaq Nordic Market Model 2025:04](https://www.nasdaq.com/docs/2025/09/29/Nasdaq_Nordic_Market_Model_2025_04.pdf); [Nasdaq European Markets Trading Hours](https://www.nasdaqomxnordic.com/tradinghours); [TradingHours.com STOX](https://www.tradinghours.com/markets/nasdaq-stockholm)
- **Oslo Børs (Euronext Optiq)**, where sources conflict:
  - One summary: regular session 09:00–16:20; closing auction call 16:20–16:24:45; closing uncross at 16:24:50; and "no Trading-at-Last phase". — [Guide to New Trading System, Oslo Børs (Euronext Connect2)](https://connect2.euronext.com/sites/default/files/it-documentation/Guide%20to%20New%20Trading%20System%20-%20issue%203%200.pdf); [Euronext trading hours](https://www.euronext.com/en/trading/trading-hours-holidays)
  - The same guide is also summarised as: opening auction 09:00–09:05, continuous trading 09:05–16:20, closing auction 16:20–16:25, and "first order entry prior to the opening auction starts at 07:15 CET". This may describe the migration-era schedule.
  - A broker page instead gives: opening auction 08:15–09:00, continuous trading 09:00–16:25, closing auction 16:25–16:30. — [DEGIRO exchange opening times](https://www.degiro.com/uk/products-and-markets/exchange-opening-times)
  - Twelve Data lists XOSL trading hours as 09:00–16:20. — [Twelve Data XOSL](https://twelvedata.com/exchanges/xosl)
- Oslo Børs cash equities and ETFs went live on Euronext Optiq; the go-live date was not captured. — [The TRADE](https://www.thetradenews.com/oslo-bors-cash-equities-and-etf-markets-go-live-on-euronext-optiq-platform/); [The TRADE: migration set to complete by year-end](https://www.thetradenews.com/oslo-bors-migration-euronext-optiq-platform-set-complete-end-year/)

#### Volatility interruptions
- **Nasdaq Nordic Volatility Guards:**
  - A "dynamic" guard triggers when an aggressive order deviates too far from the last sale price.
  - A "static" guard triggers on deviation from a reference price, normally the day's opening price.
  - When triggered, continuous trading halts and an auction follows, then the book returns to continuous trading.
  - A snippet gives the auction length as "60 to 180 seconds"; thresholds are instrument-specific and set in the Market Model. — [Nasdaq IR: updated volatility guards](https://ir.nasdaq.com/news-releases/news-release-details/nasdaq-omx-nordic-introduces-updated-volatility-guards-protect); [Nasdaq Nordic Market Model 2024](https://www.nasdaq.com/docs/2023/12/06/Nasdaq-Nordic-Market-Model-2024_01_final.pdf)

#### Settlement
- The EU T+1 move was set by Regulation (EU) 2025/2075, which amends CSDR. It applies from **11 October 2027**.
  - Timeline: ESMA recommended T+1 on 18 November 2024; the Commission proposed it on 12 February 2025; political agreement came in June 2025; the Council published the text on 17 September 2025.
  - Securities-financing and margin-lending transactions are exempt. — [Regulation Tomorrow](https://www.regulationtomorrow.com/de/clearing-settlement-de/council-of-eu-publishes-text-of-draft-regulation-amending-csdr-to-t1-settlement-cycle/); [European Commission T+1](https://finance.ec.europa.eu/news/t1-settlement-2025-02-14_en); [AFM on ESMA report](https://www.afm.nl/en/sector/actueel/2024/december/esma-stelt-overgang-voor); [EU T+1 FAQ](https://eu-t1.eu/qa/)

#### Short selling at Nordnet
- **Sweden:**
  - Private customers can apply digitally. Shorting requires an ordinary "aktie- och fonddepå"; it does not work in ISK or KF.
  - You sign a "Ramavtal för värdepapperslån" and a "Kredit- & Förfogandeavtal" with BankID.
  - A short bought back the same day costs only commission, with no stock loan.
  - An overnight short opens a loan: for a Swedish stock, a 200 SEK admin fee plus at least 3% annual interest.
  - Only Swedish, Finnish, Norwegian and Danish shares can be shorted, and not all of them. — [Nordnet.se: Vilka avtal krävs för blankning?](https://www.nordnet.se/faq/handel-vardepapper/blankning/vilka-avtal-kravs-for-blankning); [Vilka aktier går att blanka?](https://www.nordnet.se/faq/handel-vardepapper/blankning/vilka-aktier-gar-att-blanka); [Kan jag blanka i en KF?](https://www.nordnet.se/faq/handel-vardepapper/blankning/kan-jag-blanka-i-en-kf-kapitalforsakring)
- **Norway:**
  - Shorting is available only on an "Aksje- og fondskonto" (not ASK), with available margin.
  - It needs an approved "Rammeavtale for verdipapirlån" and passed knowledge tests for both margin and shorting.
  - Collateral is 15–100% equity; commission is the same as for a sale.
  - Positions not bought back the same day pay interest plus an admin fee.
  - Both Norwegian and foreign stocks can be shorted. — [Nordnet.no Shorthandel](https://www.nordnet.no/tjenester/shorthandel); [Søk om shorthandel](https://www.nordnet.no/faq/handel/shorthandel/sok-om-shorthandel); [Hvilke aksjer kan jeg shorte?](https://www.nordnet.no/faq/handel/shorthandel/hvilke-aksjer-kan-jeg-shorte)
- **Denmark:** Nordnet DK also has a shorting FAQ; details were not retrieved. — [Nordnet.dk shorthandel FAQ](https://www.nordnet.dk/faq/kredit-og-shorthandel/shorthandel/kan-jeg-foretage-en-shorthandel-hos-nordnet)
- **FI short-position register (Sweden):** reachable on 2026-08-28 with 338 rows. Fields: issuer_name, LEI, latest_position_date, total_short_pct. — [hankkontakt datatest](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/datatest-publik-norden.md)

#### Tax wrappers
- **Sweden, ISK 2026:**
  - The first 300,000 SEK is tax-free; this level is shared across ISK, KF and PEPP.
  - The standardised income rate (schablonintäkt) is 3.55%: the government borrowing rate of 2.55% (as of 30 November 2025) plus 1 percentage point.
  - That income is taxed at 30%, so the effective tax is 1.065% of capital above 300,000 SEK. — [Skatteverket: ISK](https://www.skatteverket.se/privat/skatter/vardepapper/investeringssparkontoisk.4.5fc8c94513259a4ba1d800037851.html); [ISK-guiden: schablonskatt 2026](https://isk-guiden.se/guider/schablonskatt-2026/); [Handelsbanken](https://www.handelsbanken.se/sv/privat/spara/investeringssparkonto/sa-beraknas-skatt-pa-isk)
- **Norway, ASK:**
  - You can trade shares and equity funds (at least 80% equities) without tax along the way, provided the securities are domiciled in the EEA and listed.
  - Withdrawals up to the amount deposited are tax-free. Gains above that are taxed when withdrawn, at 37.84% in 2026 after the risk-free return allowance (skjermingsfradrag).
  - Euronext Growth shares **cannot** be held in ASK today because Euronext Growth is an MTF. — [AksjeNorge: Aksjesparekonto](https://aksjenorge.no/aksjesparekonto/); [Capitalize: ASK 2026](https://capitalize.no/investering/aksjesparekonto-ask); [Wiese Advokatfirma](https://www.wieseadv.no/aktuelt-1/blog-post-title-two-e7chr-dmdc3)
  - **Proposed change:** the Finance Ministry consulted on extending ASK to shares and equity certificates traded on MTFs such as Euronext Growth, effective **1 January 2027**. The consultation deadline was 3 August. AksjeNorge wrote on 24 June 2026 that "Aksjesparekontoen er i endring", and Stortinget committee report Innst. 182 S (2025–2026) concerns ASK. — [Regjeringen høring](https://www.regjeringen.no/no/aktuelt/horing-utvidet-aksjesparekonto-vil-gi-flere-investeringsmuligheter/id3167178/); [AksjeNorge 2026-06-24](https://aksjenorge.no/aktuelt/2026/06/24/ask-endring/); [Investornytt](https://www.investornytt.no/nyheter/vil-utvide-ordningen-med-aksjesparekonto/536517); [Stortinget Innst. 182 S](https://www.stortinget.no/no/Saker-og-publikasjoner/Publikasjoner/Innstillinger/Stortinget/2025-2026/inns-202526-182s/?all=true)

### Inferences
- **Auctions shape the app's clock.** Settlement stays T+2 until 11 October 2027. Retail brokers generally let customers reuse unsettled sale proceeds, so settlement is unlikely to block same-day round trips. This is unverified for Nordnet and should be confirmed before the app assumes it.
- **Signals should use auction prices.** The opening auction (09:00 in both markets) and closing auction (about 16:25 Oslo, 17:30 Stockholm) prices are the natural "fillable" prices for a manual user. Pre-open releases (07:00–08:00 CET) are priced in the opening auction.
- **Volatility guards and halts mean stop-loss logic** should expect gaps and auction resumptions rather than continuous fills.
- **No PDT-type rule was found** for EU/EEA cash equities. Nordnet's constraints are margin and short-selling approvals plus knowledge tests (needs confirmation; see Gaps).
- **Wrappers matter:**
  - Inside ISK and ASK, frequent trading triggers no per-trade tax, so short-term trading there is tax-neutral. But shorting is impossible in ISK and ASK, and Euronext Growth Oslo is ineligible for ASK until at least 2027.
  - Outside wrappers in Norway, each realised gain is taxed at 37.84% (losses deductible), which further raises the net hurdle for winners.
- **Danish and Finnish shares** run on the same INET Nordic platform (Nasdaq screener codes CPH and HEL) with similar rules. Their national wrappers (Danish aktiesparekonto, Finnish osakesäästötili) would need separate checks.

### Gaps
- An authoritative 2026 Oslo Optiq schedule (opening auction start and uncross time, closing auction end, whether Trading-at-Last exists for Oslo): sources conflict and Euronext pages are blocked.
- Euronext Optiq dynamic and static collar percentages and trading-halt procedures for Oslo. Exact Nasdaq Nordic volatility-guard thresholds and auction lengths.
- Copenhagen and Helsinki trading hours: not retrieved.
- Whether Norway (EEA/EFTA) has incorporated the CSDR T+1 amendment on the same date as the EU.
- EU Short Selling Regulation notification and disclosure thresholds (believed 0.1% to the regulator and 0.5% public; not verified here). Formal confirmation that no EU/EEA "pattern day trader" rule exists: no source retrieved.
- The final legislative status of ASK inclusion of Euronext Growth: proposal and committee stage found, enactment not confirmed. Danish and Finnish wrapper rules were not researched (search budget exhausted).

## Q5. Tooling: indicator libraries, intraday-capable backtesters, and realistic fill simulation

### Takeaway
- **TA-Lib's Python wrapper** now ships binary wheels (0.6.5+; current 0.8.x).
- **The original pandas-ta repo is gone** (HTTP 404 on 2026-10-02). The maintained continuation is the `pandas-ta-classic` fork (2025–2026).
- **NautilusTrader** (LGPL-3.0, Rust core) is the strongest open-source event-driven option. It supports L1–L3 order books, quote and trade ticks, bars, queue position, partial fills, latency, and `AT_THE_OPEN`/`AT_THE_CLOSE` orders, which suit Nordic auction-aware fill modelling.

### Cited Findings
- **TA-Lib Python wrapper:**
  - "Starting with version 0.6.5, we now build binary wheels … which include the underlying TA-Lib C library".
  - The current line is 0.8.x, supporting TA-Lib C 0.8.x and NumPy 2; use ta-lib ≥0.5 for numpy ≥2.
  - It has 150+ indicators and 60+ candlestick patterns. — [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python)
- **pandas-ta:**
  - `github.com/twopirllc/pandas-ta` returned HTTP 404 when fetched on 2026-10-02 (first-hand observation).
  - `xgboosted/pandas-ta-classic` describes itself as "250+ Indicators and Candlestick Patterns". It was created 2025-06-17, last updated 2026-10-01, has 447 stars and is not archived. — [GitHub pandas-ta-classic](https://github.com/xgboosted/pandas-ta-classic)
  - A Rust/Polars reimplementation, polars-ta-classic, was created in April 2026. — [GitHub polars-ta-classic](https://github.com/DaveForan/polars-ta-classic)
- **NautilusTrader:**
  - A "production-grade, Rust-native engine" with a deterministic event-driven design, sharing strategy code between backtest and live.
  - Data: quote and trade ticks, L1/L2/L3 order-book deltas, bars, and nanosecond timestamps.
  - Fill simulation: queue-position tracking, partial fills, slippage, and latency modelling.
  - Order types and instructions: IOC, FOK, GTC, GTD, DAY, `AT_THE_OPEN` and `AT_THE_CLOSE`, plus post-only, reduce-only and iceberg.
  - Adapters for Interactive Brokers and Databento. LGPL-3.0, with a roughly bi-weekly release schedule. — [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader)
- **Saxo-based Nordic day-trading projects on GitHub:**
  - One Rust project trades Danish, Swedish and Norwegian stocks through Saxo.
  - It polls quotes every minute while markets are open and computes MA, MACD, RSI, Bollinger, Stochastic, ATR and support/resistance on Saxo chart bars.
  - It enforces that "an LLM … response is an advisory report, not a broker instruction". — [simonellefsen/saxo-daytrader-rust](https://github.com/simonellefsen/saxo-daytrader-rust)

### Inferences
- **For this app** (suggestions, not execution), a light stack is enough:
  - TA-Lib or pandas-ta-classic for indicators on daily, 5-minute or 15-minute bars;
  - a vectorised backtest for 1–10-day signals;
  - a prediction log that records the decision-time price, the next auction price, and costs.

  NautilusTrader is warranted only if intraday entries and exits are modelled from tick or book data.
- **Realistic fill rules to encode:**
  1. Entries after an announcement fill at the next opening-auction price, not the previous close.
  2. Market orders in continuous trading pay half the spread per side, using quoted spread snapshots or a size-bucket spread such as BIS's 17, 41 and 148 bps where no quotes exist.
  3. Limit orders fill only if price trades through the limit, which approximates queue position. Partial fills are capped at a participation rate (e.g. 5–10% of interval volume) for small caps.
  4. Apply Nordnet minimum fees per order and tick-size rounding (RTS 11).
  5. Halts and volatility guards produce auction prices, not stop-level fills.
- **Data granularity is the binding constraint.** Free Yahoo 1-minute history covers about 8 days by default (possibly about 30 days with windowed requests; unverified), and other intraday intervals at most 60 days, so the app should **archive** intraday bars itself from day one if it wants to test intraday signals later. Note the storage-rights caveat in Q1.

### Gaps
- No sources were retrieved this session for backtrader (maintenance status), vectorbt or vectorbt PRO, backtesting.py, LEAN/QuantConnect Nordic data coverage, zipline-reloaded or hftbacktest. Their current status and suitability are unverified.
- No Nordic-specific open-source auction-fill models or historical Nordic order-book datasets (e.g., Nasdaq Nordic ITCH history or Euronext historical depth pricing) were found.
