# Nordnet (data source and execution venue) and retail sentiment/attention data for Norwegian and Swedish shares (DK/FI secondary)

*Research date: 2026-10-02. Sleeve tags: **[ST]** = short-term trading sleeve (intraday to a few days); **[LT]** = long-term value sleeve (months to years). Endpoint status labels: "verified live 2026-10-02" (with HTTP status) or "unverified" (taken from open-source code or docs, not fetched here). Network context: www.nordnet.se, docs.rs, deepwiki.com, www.nordnet.dk, nordnetab.com, capitalize.no, isk-guiden.se, wikimedia.org, api.crossref.org, api.openalex.org and www.aksjeeierregisteret.no all returned EGRESS_BLOCKED for WebFetch. The session's WebSearch budget ran out partway through. A short live check of www.nordnet.no with curl (allowed by the coordinator) ran once. The permission system then denied reading the saved responses, so I stopped live verification. Only the HTTP status lines already shown are reported below.*

## 1. Nordnet API and website endpoints: 2026 status, eligibility, authentication, data endpoints, read-only use, unofficial JSON endpoints, ToS

### Takeaway
Nordnet's official External API ("nExt API" v2) still exists. It uses Ed25519 key login, and Nordnet's own docs say it is **not onboarding new customers**. There is no test environment, and a key reportedly grants full trading rights (no read-only key). It also does not expose owner counts. In practice, a personal data-gathering app would rely on the **unofficial, unauthenticated JSON endpoints the Nordnet website calls** (`/api/2/instrument_search/...` with header `client-id: NEXT`). These return per-stock `number_of_owners`, prices, key ratios, and a bull/bear-certificate holder list. All of them are undocumented, may change, and are probably covered by customer-terms bans on systematic extraction.

### Cited Findings
**Official nExt API v2 (status, auth, hosts)**
- The External API is version 2.0. Login uses Ed25519: generate a key with `ssh-keygen -t ed25519 -a 150`, upload the public key on Nordnet web (My pages → Settings → My profile → "API key" under Security), and receive an API key (UUID). Then `POST /api/2/login/start` returns a challenge, the caller signs the challenge bytes with the Ed25519 key, and `POST /api/2/login/verify` returns a `session_key` — [Nordnet API documentation](https://www.nordnet.se/externalapi/docs/api); [Getting Started with the Nordnet API](https://www.nordnet.se/externalapi/docs/getting_started) (content via search snippets; nordnet.se blocked here)
- "A Nordnet API key grants full access to your account, including placing orders, and Nordnet does not offer a read-only key" — [nordnet_api Rust crate docs (third-party)](https://docs.rs/nordnet-api/latest/nordnet_api/); [lib.rs nordnet-api](https://lib.rs/crates/nordnet-api) (secondary; via search summary)
- "Nordnet API is currently not onboarding new customers." This is stated on the official Getting Started page (date not shown in the snippet) — [Getting Started with the Nordnet API](https://www.nordnet.se/externalapi/docs/getting_started); [Nordnet blog: Nordnet API](https://www.nordnet.se/blogg/nordnet-api-koppla-dina-egenutvecklade-handelsapplikationer-till-nordnet)
- The API host depends on the customer's country: `public.nordnet.dk`, `public.nordnet.fi`, `public.nordnet.no` or `public.nordnet.se` — [Getting Started with the Nordnet API](https://www.nordnet.se/externalapi/docs/getting_started) (via search snippet). This conflicts with Nordnet Denmark's FAQ, which (per the search summary) says Nordnet does not offer API solutions — [Nordnet DK FAQ: Kan man benytte API-løsninger hos Nordnet?](https://www.nordnet.dk/faq/handel/kob-salg/kan-man-benytte-api-losninger-hos-nordnet)
- Nordnet's official example repo: "There is no longer any test environment available. Contact Nordnet Trading Support to get started." A sample `login/verify` response contains `"expires_in": 1800`, a `session_key`, a public feed at `pub.next.nordnet.se:443` and a private feed at `priv.next.nordnet.se:443`. Feed login is `{'cmd': 'login', 'args': {'session_key': ...}}` and a subscription looks like `{'cmd': 'subscribe', 'args': {'t': 'price', 'm': 11, 'i': '101'}}` — [nordnet/next-api-v2-examples python3/README.md (official GitHub)](https://github.com/nordnet/next-api-v2-examples/blob/master/python3/README.md); [repo root](https://github.com/nordnet/next-api-v2-examples) ("The code in this repo is intended as examples only")
- A third-party project's Sept-2026 test notes say the official API "is not sufficient". `/api/2/instruments/{id}` gives instrument master data but **not owner counts**, and `/statistics`, `/ownership` and `/shareholder_statistics` all returned `NOT_FOUND`. Access is by application via Nordnet Trading Support, with no test environment — [ryddmo/stockpicker addendum (2026-09-08)](https://github.com/ryddmo/stockpicker) (`_bmad-output/planning-artifacts/briefs/brief-stockpicker-2026-09-08/addendum.md`)
- Other open-source clients and integrations: [zjael/nordnet-api (Nordnet.dk unofficial API)](https://github.com/zjael/nordnet-api), [helmstedt/nordnet-utilities](https://github.com/helmstedt/nordnet-utilities), [jippi/hass-nordnet](https://github.com/jippi/hass-nordnet), [mcfrojd/hass-nordnet](https://github.com/mcfrojd/hass-nordnet), [ThomasTJdev/nim_nordnet_api (scraping API for nordnet.dk)](https://github.com/ThomasTJdev/nim_nordnet_api)

**Unofficial website JSON endpoints (no login)** — all **unverified** unless stated
- Stock list / screener (**[ST][LT]**): `GET https://www.nordnet.{se|no|dk|fi}/api/2/instrument_search/query/stocklist`. Parameters seen in code: `free_text_search=<text>&limit=10`; `apply_filters=exchange_country=<CC>` (URL-encoded `%3D`); `sort_attribute=dividend_yield|diff_pct|number_of_owners|turnover`; `sort_order=desc`; `limit`, `offset`. The header is `client-id: NEXT`; one project first loads `https://www.nordnet.dk/markedet` and passes back whatever cookies are returned ("the 'NEXT' cookie no longer exists") — [FlemmingJahn/NordnetAktieScreener](https://github.com/FlemmingJahn/NordnetAktieScreener); [ryddmo/stockpicker NordnetAdapter.php](https://github.com/ryddmo/stockpicker); [luimu64/nordnet-sdk](https://github.com/luimu64/nordnet-sdk)
  - Field names read by that code: `total_hits`, `results[].instrument_info.{name,symbol,isin,instrument_pawn_percentage}`, `results[].nnx_info.nnx_instrument_id`, `results[].statistical_info.number_of_owners` (integer), `results[].statistical_info.statistics_timestamp` (epoch ms), `results[].price_info.last.price`, `results[].company_info.market_cap`, `results[].exchange_info.exchange_country`, `results[].key_ratios_info.{pe,dividend_yield}`. Range filters take the form `diff_pct=[0.001 TO *]` — [ryddmo/stockpicker NordnetAdapter.php](https://github.com/ryddmo/stockpicker); [FlemmingJahn/NordnetAktieScreener](https://github.com/FlemmingJahn/NordnetAktieScreener); [luimu64/nordnet-sdk client.py](https://github.com/luimu64/nordnet-sdk)
  - Live check 2026-10-02: `https://www.nordnet.no/api/2/instrument_search/query/stocklist?apply_filters=exchange_country%3DNO&sort_attribute=number_of_owners&sort_order=desc&limit=5&offset=0` with `client-id: NEXT` and no cookies returned **HTTP 400** (68-byte JSON error body; the body was not inspected). The host is reachable but this parameter combination was rejected. Field names were **not** verified live.
- Bull/bear certificate holders by underlying (**[ST]**): `GET https://www.nordnet.no/api/2/instrument_search/query/bullbearlist?apply_filters=underlying_name%3D{name}%7Cnordnet_markets%3Dtrue&limit=200`. Fields: `statistical_info.number_of_owners`, `certificate_info.static_leverage`, `etp_info.direction` ("Long"/"Short"). One project computes weight = holders^0.7 × gearing, long ratio = Σlong / Σall, and signal = 2·ratio − 1 ∈ [−1, 1] — [jon-tj/StocksPlatform BullBearDeltaService.cs](https://github.com/jon-tj/StocksPlatform)
  - Live check 2026-10-02: the same URL with `underlying_name=Equinor` and `limit=50` returned **HTTP 200** (`application/json`, 38-byte body; contents not inspected). The endpoint responds, but the fields were not verified live.
- Other paths, per [luimu64/nordnet-sdk](https://github.com/luimu64/nordnet-sdk) (headers `client-id: NEXT`, `ntag: NO_NTAG_RECEIVED_YET`; "No account. No API key. No login."; "market data may be delayed"):
  - `/api/2/instrument_search/query/instrument?apply_filters=instrument_id={id}`
  - `/api/2/instrument_search/query/fundlist`
  - `/api/2/main_search?query=&limit=&search_space=`
  - `/api/2/tradables/trades/{market_id}%3A{identifier}?count=100` (trade tape, **[ST]**)
  - On a separate market-data host `https://api.prod.nntech.io` (header `x-locale`, e.g. `fi-FI`), the SDK lists:
    - `/market-data/v3/price-time-series/period/{DAY_1|WEEK_1|MONTH_1|MONTH_3|MONTH_6|YTD|YEAR_1|ALL}/identifier/{id}` (price history, **[ST][LT]**)
    - `/news/v1/news/preview/instrument/{nnx_id}?limit=20&offset=0` (news, **[ST]**)
    - `/market-data/v1/market-hours/{order_book_id}`
    - `/instrument-screening/v3/stocks/web/{slug}` (stock profile)
    - `/instrument-screening/v1/indicator/web/list/{list_id}`
  - All of these are unverified, and `api.prod.nntech.io` was not tested. The user would need to allow that host.
- Shareville/Nordnet Social (**[ST]**): older code calls `https://www.shareville.no/api/v1/portfolios/{id}/performance` — [fintech-enigma/fintech-enigma-api Shareville.js](https://github.com/fintech-enigma/fintech-enigma-api). Status after the April-2026 rebrand is **unverified**.

**ToS / robots**
- A third-party project's Sept-2026 notes claim that "Avanzas kundvillkor förbjuder formellt systematisk/automatiserad extraktion och all redistribution" and that the same applies to Nordnet. They also say robots.txt permits general crawling for both, rate limits for both are unknown, and the practical risk for personal, low-volume, non-redistributed use is low — [ryddmo/stockpicker addendum](https://github.com/ryddmo/stockpicker) (secondary; Nordnet's own wording not seen)
- Live check 2026-10-02: `https://www.nordnet.no/robots.txt` returned **HTTP 200** (3,206 bytes). Under `User-agent: *` it disallows account and order pages (`/overview`, `/transactions`, `/settings`, `/search`, `/currencies`, `*/order/*`, …) and filtered list pages such as `*/etp/sertifikat/bull-bear/liste?*`, `*/etp/sertifikat/liste?*` and `*/derivat/opsjoner/liste?*`. Only the first ~60 lines were viewed, so whether `/api/` is disallowed was **not** confirmed.

### Inferences
- For a personal app, the realistic Nordnet data path is the unofficial `instrument_search` endpoints, polled at most once daily for owner counts plus occasional quotes. The official API is closed to newcomers. Even for existing users it would be over-privileged, since a key can trade.
- Owner-count history does not exist in any Nordnet endpoint found. The app must snapshot `number_of_owners` plus `statistics_timestamp` daily to build its own history.
- The HTTP 400 on the `number_of_owners` sort suggests that either that sort attribute or a missing session/`ntag` is not accepted. Code that worked used `free_text_search` or `sort_attribute=dividend_yield|diff_pct`. The collector should copy the request pattern the site uses, re-check it periodically and validate the schema, as ryddmo does.
- Because terms likely prohibit systematic extraction, keep request volume minimal, do not redistribute data, and cache.

### Gaps
- Nordnet's exact ToS wording on automated access or scraping, and whether robots.txt disallows `/api/`: not obtained (nordnet.se/.dk blocked; live read on nordnet.no denied by the permission system).
- Whether `number_of_owners` on nordnet.no counts only Norwegian customers or all Nordnet customers: unknown.
- Official API endpoint list (instrument search, order book `depth` feed, news feed types), rate limits, and whether market data via the API is real-time: not verified (docs blocked). Only the `price` feed subscription is shown in the official examples.
- Nordnet analyst-consensus widget endpoint: not found.
- Hosts the user would need to allow for further verification: `www.nordnet.se`, `api.prod.nntech.io`, `public.nordnet.no` / `public.nordnet.se`, `pub.next.nordnet.se`, `www.shareville.no`, `www.avanza.se`. Further curl reads of `www.nordnet.no` also need a user-granted Bash permission rule.

## 2. Tradable universe for Nordnet NO/SE customers and how to obtain it programmatically

### Takeaway
A Nordnet Norway customer can trade Oslo Børs, Euronext Growth Oslo, NOTC/unlisted shares, all Swedish venues (Nasdaq Stockholm, First North, Spotlight, NGM, Nordic MTF), Copenhagen and Helsinki (incl. First North), plus about 14 other countries. However, **Euronext Growth shares cannot be held in a Norwegian ASK**. The universe can be enumerated by paging the website's `stocklist` endpoint filtered by `exchange_country`.

### Cited Findings
- Nordnet Norway lists these trading venues:
  - Norway: Oslo Børs, Oslo Axess, NOTC, Euronext Growth, unlisted Norwegian shares.
  - Sweden: Nasdaq Stockholm, Nordic Growth Market, Nordic MTF, Spotlight Stock Market, First North Stockholm.
  - Denmark: Nasdaq Copenhagen with First North Denmark and Spotlight.
  - Finland: Nasdaq Helsinki with First North Helsinki.
  - Elsewhere: Germany, UK, USA, Canada, France, Belgium, Netherlands, Portugal, Ireland, Italy, Switzerland, Austria, Poland and Spain.
  - Sources: [Nordnet NO FAQ: Handelsplassene våre](https://www.nordnet.no/faq/handel/handelsplassene-vare/handelsplassene-vare) (via search summary); [Nordnet NO: Handle unoterte aksjer (NOTC)](https://www.nordnet.no/blogg/handle-unoterte-aksjer-notc/)
- Euronext Growth shares can be traded on a regular aksje- og fondskonto or "Investeringskonto Zero", but not in an Aksjesparekonto (ASK), because Euronext Growth is not an EU/EEA-regulated market — [Nordnet NO: Hvorfor kan jeg ikke ha Euronext Growth-aksjer på min aksjesparekonto?](https://www.nordnet.no/blogg/hvorfor-kan-jeg-ikke-ha-euronext-growth-aksjer-pa-min-aksjesparekonto); [Nordnet NO FAQ: Euronext Growth](https://www.nordnet.no/faq/handel/handelsplassene-vare/euronext-growth)
- Recent venue additions (titles and dates from Nordnet press releases): five new European exchanges, Madrid, electronic trading on the London Stock Exchange, and pre-market trading in US shares — [Nordnet åpner dørene til fem nye europeiske børser](https://nordnetab.com/press_release/nordnet-apner-dorene-til-fem-nye-europeiske-borser/); [Nordnet åpner for aksjehandel på Madrid-børsen (PDF)](https://mb.cision.com/Main/116/4229467/3648166.pdf); [LSE electronic trading](https://nordnetab.com/press_release/nordnet-lanserer-elektronisk-handel-pa-london-stock-exchange/); [Nordnet lanserer førhandel i amerikanske aksjer](https://news.cision.com/no/nordnet/r/nordnet-lanserer-forhandel-i-amerikanske-aksjer,c4136691)
- Programmatic enumeration: page `GET /api/2/instrument_search/query/stocklist?apply_filters=exchange_country%3D{NO|SE|DK|FI}&limit=100&offset={n}` and read `total_hits` plus `results[]` (country filter and paging as used on nordnet.dk) — [FlemmingJahn/NordnetAktieScreener](https://github.com/FlemmingJahn/NordnetAktieScreener). The listing includes `instrument_info.isin` and `exchange_info.exchange_country`. Dual listings are handled by preferring the "SE" listing in one project — [ryddmo/stockpicker NordnetAdapter.php](https://github.com/ryddmo/stockpicker). **Unverified live** (see the HTTP 400 note in §1).
- Avanza equivalent (for a Swedish cross-check): `POST https://www.avanza.se/_api/market-stock-filter/stocks` for the universe, and `POST /_api/search/filtered-search` with body `{"query":..., "searchFilter":{"types":["STOCK"]}}` — [ryddmo/stockpicker addendum and AvanzaAdapter.php](https://github.com/ryddmo/stockpicker) (**unverified**)

### Inferences
- The app should tag each instrument with: venue/list, country, currency, `isASKEligible` (false for Euronext Growth; likely false for other MTFs such as First North, Spotlight and NGM, which is unverified) and `isFXTrade` relative to the account currency. The allocation step can then restrict an ASK account to eligible shares.
- The Nordnet FAQ still names "Oslo Axess" (an older list name), so the venue taxonomy should come from the live list data, not from FAQ text.

### Gaps
- Exact list of venues for **Nordnet Sweden** customers, and whether Swedish ISK can hold MTF shares (First North/Spotlight/NGM): not verified (nordnet.se blocked; search budget exhausted).
- Filter keys for list or segment (for example Oslo Børs vs Euronext Growth vs Euronext Expand) in the `stocklist` endpoint: not found in code read.
- Current status of Euronext Expand Oslo: not verified.

## 3. Trading costs and account constraints (courtage, minimum fees, FX, ASK/ISK/KF, fractional shares) and implications for position size and rebalancing

### Takeaway
Nordnet NO's cheapest class for small trades is Mini at **0.15%, minimum NOK 29** for Nordic shares, so trades below about NOK 19,300 pay more than 0.15%. Nordnet SE's Mini is **0.25%, minimum SEK 1**, so it has no meaningful minimum. Automatic FX conversion at Nordnet NO adds **0.25%** each way, or 0.075% with a currency account. No evidence was found that Nordnet offers fractional shares. Small accounts should therefore hold few, larger positions and rebalance rarely.

### Cited Findings
- **Nordnet Norway (2026):**
  - Mini: minimum NOK 29 (0.15%) for Nordic trades and minimum NOK 49 (0.2%) outside the Nordics. It is best for trades under NOK 52,667.
  - Normal: minimum NOK 79 (stated as 0.10% in the same summary).
  - New customers get a two-month "Welcome" period with courtage "fra bare 1 kr".
  - Classes change automatically with the number of courtage-paying trades and are reclassified monthly.
  - Sources: [Capitalize: Nordnet anmeldelse 2026](https://capitalize.no/blogg/nordnet-anmeldelse/); [Nordinnsikt: Nordnet anmeldelse (2026)](https://nordinnsikt.no/meglere/nordnet/); [Nordnet NO FAQ: Normal, Bonus og VIP kurtasje](https://www.nordnet.no/faq/priser/kurtasje/normal-bonus-og-vip-kurtasje); [Nordnet NO FAQ: Hvordan endrer jeg til kurtasjeklasse MINI?](https://www.nordnet.no/faq/priser/kurtasje/hvordan-endrer-jeg-til-kurtajeklasse-mini); official price list at [nordnet.no/kundeservice/prisliste](https://www.nordnet.no/kundeservice/prisliste) (not read). All via search summary. The Normal percentage is uncertain.
- **Nordnet Sweden (2026):**
  - Mini: 0.25%, minimum SEK 1 (trades under SEK 15,600).
  - Liten: 0.15%, minimum "49 kr" (SEK 15,600–46,000).
  - Mellan: 0.069%, minimum SEK 69 (SEK 46,000–143,478).
  - The class can be changed in the app at any time.
  - "Kom igång": no courtage on Stockholmsbörsen until SEK 50,000 total capital, maximum 500 trades per year.
  - Sources: [Kvalitetsaktier: Courtage-jämförelse 2026](https://kvalitetsaktier.se/courtage-jamforelse); [ISK-guiden: Nordnet ISK 2026](https://isk-guiden.se/maklare/nordnet/); [Financer: Nordnet omdöme 2026](https://financer.se/recension/nordnet/); [Nordnet SE FAQ: Kom-igång erbjudande](https://www.nordnet.se/faq/courtage-avgifter/kom-igang-erbjudandet/nordnets-kom-igang-erbjudande); [Nordnet SE FAQ: Hur beräknas courtaget](https://www.nordnet.se/faq/courtage-avgifter/courtage/hur-beraknas-courtaget-vid-en-affar) (via search summary)
  - **Internal inconsistency:** a Mini/Liten breakpoint of SEK 15,600 implies a Liten minimum of SEK 39 (0.25% × 15,600 = 39), not 49. The 143,478 upper bound implies a SEK 99 flat-fee class (0.069% × 143,478 ≈ 99). Both are my arithmetic, so the official price list needs confirming.
- **FX (Nordnet NO):** automatic exchange uses a rate 0.25% away from the provider's rate (e.g. NOK 25 on NOK 10,000). With a valutakonto (currency account), manual exchange carries a 0.075% markup (NOK 7.50 per NOK 10,000) — [Nordnet NO FAQ: Hvordan fungerer valutaveksling på Nordnet?](https://www.nordnet.no/faq/priser/valuta-og-veksling/automatisk-veksling/hvordan-fungerer-valutaveksling-pa-nordnet); [Nordnet NO: Valutakonto](https://www.nordnet.no/tjenester/valutakonto); [Nordnet NO FAQ: automatisk veksling](https://www.nordnet.no/faq/priser/valuta-og-veksling/automatisk-veksling/hvordan-fungerer-automatisk-veksling) (via search summary)
- **ASK constraint:** Euronext Growth shares are not allowed in a Norwegian ASK — [Nordnet NO blog](https://www.nordnet.no/blogg/hvorfor-kan-jeg-ikke-ha-euronext-growth-aksjer-pa-min-aksjesparekonto)
- **Fractional shares:** a search for Nordnet fractional-share trading ("brøkdelshandel") returned only unrelated launches (US pre-market, new exchanges, NOTC, zero-courtage Nordnet Markets products). No evidence of fractional share trading was found — [search results incl. Nordnet Markets press release](https://nordnetab.com/press_release/handel-i-borsnoterte-produkter-uten-kurtasje-med-nordnet-markets/)

### Inferences
- **Cost function for the allocator** (one-way, my arithmetic from the figures above):
  - NO Mini: `max(29, 0.0015·X)` NOK. The minimum binds below X ≈ NOK 19,333. A NOK 5,000 trade costs 0.58% one-way (about 1.16% round trip); NOK 10,000 costs 0.29% one-way.
  - SE Mini: `0.0025·X` (minimum SEK 1), so 0.5% round trip at any small size.
  - Cross-currency trades (e.g. a NOK account buying Stockholm shares): add 0.25% per conversion (about 0.5% round trip), or 0.075% via valutakonto.
  - Bid-ask spread comes on top; it is not quantified here.
- **Minimum sensible position:** on NO Mini, positions of about NOK 19,300 or more keep courtage at the 0.15% floor. A cap of 0.3% one-way cost implies at least about NOK 9,700. A NOK 50k account therefore supports roughly 3–5 positions without heavy fee drag.
- **Short-term sleeve:** signals must clear about 0.3% (NO Mini at ≥ NOK 19.3k) or 0.5% (SE Mini) round-trip cost plus spread. Avoid cross-currency short-term trades.
- **Long-term sleeve:** rebalance with tolerance bands rather than on a calendar, and avoid small top-ups.
- Because no fractional shares were found, allocations must round to whole shares. For high-priced stocks in small accounts this creates material tracking error, so the allocator should optimise integer share counts.

### Gaps
- Official Nordnet NO price list (Normal/Bonus/VIP percentages and thresholds) and Nordnet SE price list (Liten minimum 39 vs 49; flat-price class): not confirmed from primary pages (nordnet.se blocked; nordnet.no reads denied).
- Nordnet SE FX fee: not found.
- Swedish ISK 2026 rules (tax-free amount, standard-income rate) and KF availability at Nordnet: not verified (isk-guiden.se blocked; search budget exhausted).
- Danish ASK and Finnish osakesäästötili 2026 limits: not researched.

## 4. Retail ownership and flow data: Nordnet owners and lists, Avanza owner counts and history, Shareville/Nordnet Social, monthly statistics, Euroclear/VPS statistics

### Takeaway
The richest free retail-flow signals are daily broker-level **owner counts**:
- **Nordnet:** `statistical_info.number_of_owners` (snapshot only).
- **Avanza:** `keyIndicators.numberOfOwners` plus a dedicated **owner-count history** endpoint, `/_api/market-guide/number-of-owners/{id}`.

These are complemented by:
- Nordnet NO's **monthly "Aksjestatistikk"** most-bought and most-sold press releases (September 2026 issue published 2026-09-30).
- Quarterly Euroclear Sweden and AksjeNorge/VPS shareholder statistics (aggregate, slow).

Shareville was **renamed Nordnet Social in April 2026**.

### Cited Findings
**Nordnet (NO/SE)**
- Per-stock `statistical_info.number_of_owners` carries `statistics_timestamp`. It "observeras röra sig dagligen" (observed to move daily), but the exact cadence and time are undocumented — [ryddmo/stockpicker addendum](https://github.com/ryddmo/stockpicker) (**[ST][LT]**; endpoint unverified live, see §1)
- Bull/bear certificate holders per underlying via `bullbearlist` give a holder-weighted long/short ratio — [jon-tj/StocksPlatform](https://github.com/jon-tj/StocksPlatform) (**[ST]**)
- Monthly Nordnet NO statistics. The September 2026 release ("Aksjestatistikk september: Nordnet-kundene økte aksjeeksponeringen betydelig i en turbulent måned – sikret oljegevinster og søkte ly i forsvar og utbytte") names, per Finansavisen (2026-09-30):
  - Kongsberg Gruppen as the most net-bought stock.
  - Vend Marketplaces and Telenor second and third.
  - Thor Medical, SED Energy Holdings, Tomra, B2 Impact, Orkla, Norsk Hydro and Frontline also in the top 10.
  - Customers took profits in oil stocks.
  - Sources: [Cision: Nordnet Aksjestatistikk september](https://news.cision.com/no/nordnet/r/aksjestatistikk-september--nordnet-kundene-okte-aksjeeksponeringen-betydelig-i-en-turbulent-maned---,c4402480); [Finansavisen 2026-09-30](https://www.finansavisen.no/finans/2026/09/30/8384188/nordnet-kundene-makte-ut-oljeaksjer-lastet-opp-defensivt); [Finansavisen 2026-08-31 (August list)](https://www.finansavisen.no/finans/2026/08/31/8376867/lempet-ut-aksjer-i-august-dette-er-nordnet-kundenes-favorittaksjer); earlier-year example (year not shown in the search snippet) [Cision: "Nordnet-kunder trosset september-frykten"](https://news.cision.com/no/nordnet/r/aksjestatistikk-september--nordnet-kunder-trosset-september-frykten-og-lastet-opp-med-aksjer,c4242869) (**[ST][LT]**, monthly)
- Nordnet NO year-end lists and on-site "inspiration lists" (e.g. "Mest kjøpte blant 31-50 åringer") — [Årets mest kjøpte og solgte aksjer](https://www.nordnet.no/blogg/arets-mest-kjopte-og-solgte-aksjer); [Inspirasjonsliste](https://www.nordnet.no/aksjer/inspirasjon/lister/1dcyiumgu8mgggqfbmyfqr). Sweden: [Börskollen: 20 aktier som köps mest hos Nordnet](https://www.borskollen.se/nyheter/27/lista-har-ar-20-aktier-som-kops-mest-hos-nordnet-och-de-10-som-ratas-1790503203)

**Avanza (SE)**
- `GET https://www.avanza.se/_api/market-guide/stock/{orderBookId}` returns `keyIndicators.numberOfOwners`, `keyIndicators.marketCapital.value`, `quote.last`, `historicalClosingPrices.oneDay` and `isin` — [ryddmo/stockpicker AvanzaAdapter.php](https://github.com/ryddmo/stockpicker) (**[ST][LT]**, unverified)
- `numberOfOwners` "uppdateras dagligen, ungefär 18:00–19:00 CET" (updated daily at roughly 18:00–19:00 CET) and is not updated on weekends ("söndag och måndag visar lördagens värde": Sunday and Monday show Saturday's value) — [ryddmo/stockpicker addendum](https://github.com/ryddmo/stockpicker)
- **Owner history:** `GET /_api/market-guide/number-of-owners/{orderbookId}` "returns history of Avanza customer ownership" with no authentication required — [AnteWall/avanza-ts market-client.ts](https://github.com/AnteWall/avanza-ts); also in [AnteWall/avanza-mcp endpoints.py](https://github.com/AnteWall/avanza-mcp). A tracker app calls it with `User-Agent: Mozilla/5.0`, "Required to avoid 403 error from Avanza", and caches for 2 hours — [psykopotatis/agardata-avanza](https://github.com/psykopotatis/agardata-avanza) (**unverified**; response schema not documented in that code)
- Other Avanza endpoints (no auth unless noted), per [AnteWall/avanza-ts](https://github.com/AnteWall/avanza-ts) and [avanza-mcp](https://github.com/AnteWall/avanza-mcp); all **unverified**:
  - `/_api/market-guide/stock/{id}/broker-trade-summaries` (broker flow, **[ST]**)
  - `/_api/market-guide/short-selling/{id}`
  - `/_api/market-insider-transactions/transactions/{id}`
  - `/_api/market-guide/stock/{id}/orderdepth` and `/trades`
  - `/_api/market-guide/news/{id}`
  - `/_api/price-chart/stock/{id}?timePeriod=…|from=…&to=…&resolution=…`
  - `/_api/market-guide/stock/{id}/analysis`
  - `/_api/trading-critical/rest/marketdata/{id}` (requires a session)
- Avanza ToS: customer terms reportedly prohibit systematic or automated extraction and redistribution — [ryddmo/stockpicker addendum](https://github.com/ryddmo/stockpicker) (secondary)

**Shareville → Nordnet Social**
- "Shareville blir Nordnet Social", with over half a million users per Nordnet's X post dated 2026-04-27 (date decoded from the post ID) — [Nordnet blog](https://www.nordnet.se/blogg/shareville-blir-nordnet-social/); [NordnetSE on X](https://x.com/NordnetSE/status/2048673016188457188)
- In Finland, Shareville.fi was closed and moved to nordnet.fi/foorumi (X post 2024-06-20) — [nordnetFI on X](https://x.com/nordnetFI/status/1803699490362163467) (via search summary)
- Trade recommendations are not allowed on Shareville under MAR, per Nordnet Norge on 2022-12-19 — [NordnetNO on X](https://x.com/NordnetNO/status/1604770362046418947). The HTML portfolio-embed feature was removed in 2024 — [Hernhag: Shareville oanvändbart](https://hernhag.se/shareville-oanvandbart/)
- Nordnet originally acquired Shareville — [Nordnet press release](https://nordnetab.com/press_release/nordnet-koper-sociala-investeringsnatverket-shareville/)

**Register-level statistics (aggregate; [LT])**
- **Euroclear Sweden:**
  - Publishes quarterly "Aktieägarstatistik" press releases (e.g. Q1, Q2) with changes in shareholder numbers and the most popular companies, plus the annual "Aktieägandet i Sverige" report.
  - About 2.8 million unique shareholders at end-2025; the database covers about 1,659 companies.
  - Sources: [Euroclear: Aktieägandet i Sverige 2025](https://www.euroclear.com/sweden/sv/nyheter-och-insikter/pressmeddelanden/Rekord-i-aktieagande-millennials-tar-over-och-mannen-drar-ifran.html); [Aktieägarstatistik Q2](https://www.euroclear.com/sweden/sv/nyheter-och-insikter/pressmeddelanden/Aktieagarstatistik-Q2-Utlandskt-agande-okar-svenskt-minskar-och-Saab-fortsatt-raket.html); [Aktieägarstatistik Q1](https://www.euroclear.com/sweden/sv/nyheter-och-insikter/pressmeddelanden/Aktieagarstatistik-Q1-Krympande-portfoljer-och-kvinnor-fortsatt-vinnare-pa-borsen.html); [2020 report PDF](https://www.euroclear.com/dam/ESw/Brochures/Documents_in_Swedish/Euroclear_aktie%C3%A4garrapport_2020.pdf)
- **Norway:**
  - AksjeNorge compiles quarterly statistics from Euronext Securities Oslo (formerly VPS) data on private individuals holding listed shares in their own name.
  - Over 621,000 Norwegians owned Oslo Børs shares at end-2025, with about 22,000 new shareholders in 2025.
  - Sources: [AksjeNorge: Slik investerer nordmenn på Oslo Børs](https://aksjenorge.no/aktuelt/2026/01/18/stat2025/); [Grafpakke Q4 2025 (PDF)](https://aksjenorge.no/wp-content/uploads/2026/01/Grafpakke-Q4-2025-Del-1.pdf)
  - Shareholder lookups: [Skatteetaten Aksjonærregisteret](https://www.skatteetaten.no/en/deling/aksjonarregisteret/) (annual), [AksjeNorge: Sjekk hvem som eier aksjen](https://aksjenorge.no/aktuelt/2024/08/19/aksjereg1/), and [Offentlig Aksjeeierportal, "Daglig oppdatert aksjonærregister"](https://www.aksjeeierregisteret.no/) (title only; blocked). Euronext Securities Oslo data pricing: [ES-OSL prisliste januar 2026 (PDF)](https://www.euronext.com/sites/default/files/2025-12/ES-OSL_Prisliste-januar-2026.pdf) (not read).

### Inferences
- **Best signal construction:** compute daily Δowners and Δowners/owners per stock from both Nordnet (NO and SE retail) and Avanza (mostly SE retail). Normalise by market cap or free float. Use the Avanza history endpoint to backfill for backtests (Nordnet must be snapshotted from now on).
- **Short-term sleeve:** jumps in owner counts or the bull/bear ratio. **Long-term sleeve:** owner-base trend and crowding.
- Because Avanza owner counts update at about 18–19 CET and not on weekends, use them as next-day signals with a timestamp, so that nothing that wasn't yet published leaks into a backtest.
- Nordnet monthly most-bought/sold lists cover only the top ~10 names and arrive after month-end. They are better as labels or validation than as signals.

### Gaps
- Avanza `number-of-owners` response schema, history depth and granularity: not documented in the code read (likely a time series; verify).
- Existence and content of "Nordnet Sparbarometer" and Avanza monthly most-bought press releases: not verified.
- Historical datasets of Nordnet or Avanza owner counts beyond that endpoint (e.g. archived snapshots on GitHub): none found besides tracker code.
- Whether Euroclear Sweden publishes per-company shareholder counts as downloadable data (vs press-release tables): not confirmed.
- What aksjeeierregisteret.no provides, and whether it allows bulk or automated access: unknown (blocked).

## 5. Forums and social media / attention sources: access, ToS and cost in 2026

### Takeaway
For Norway, the main retail forum is **Finansavisen's HO-forum** (per-ticker pages; scrapable HTML, ToS unverified). For Sweden it is **Avanza's Placera forum** (relaunched December 2022, BankID registration) and **Nordnet Social**.

Official social APIs became more restrictive or costly:
- **Reddit** requires manual approval since 11 November 2025 (free non-commercial tier at 100 QPM).
- **X** is pay-per-use (about USD 0.005 per post read, per secondary sources).
- **Google Trends** has only an application-gated alpha API, and pytrends is archived.

Wikipedia pageviews remain a free attention proxy (endpoint unverified here).

### Cited Findings
- **Finansavisen / HO-forum (NO) [ST]:** base `https://www.finansavisen.no/forum/`. Per-ticker pages follow `https://www.finansavisen.no/forum/ticker/{Ticker name}` and threads `https://www.finansavisen.no/forum/thread/{id}/view` — [GitHub sample with ticker URL](https://github.com/OriginalityAI/ai-citation-study); [Finansavisen forum thread](https://www.finansavisen.no/forum/thread/18717/view). An open-source scraper paginates the index, collects thread titles, tickers, post text, user and timestamp, and filters to Norwegian. It shows no login, rate-limit or ToS handling — [11Mali/datacleaningfolder webscraping_main.py](https://github.com/11Mali/datacleaningfolder) (**unverified** live)
- **Placera forum (Avanza, SE) [ST]:** taken down without warning in December 2021 (about 100,000 registered users). Avanza's support account said on 2022-01-21 that Placera had temporarily closed it. It relaunched on 20 December 2022 with BankID registration and optional pseudonyms. It now lives under URLs like `https://www.avanza.se/placera/forum/forum/{company}.html` — [Placera: Placeras nya forum igång (2022-12-20)](https://www.placera.se/telegram/placeras-nya-forum-igang-2022-12-20); [Affärsvärlden](https://www.affarsvarlden.se/artikel/avanza-forum-nara-comeback); [Avanza on X](https://x.com/avanzabank/status/1484453437291044868); [Daniel investerar blog (2021-12)](https://danielinvesterar.blogspot.com/2021/12/avanza-raderade-alla-sina-aktieforum.html); [example forum page](https://www.avanza.se/placera/forum/forum/volue.html)
- **Nordnet Social (ex-Shareville) [ST]:** see §4 — [Nordnet blog](https://www.nordnet.se/blogg/shareville-blir-nordnet-social/)
- **Reddit API [ST]:**
  - Since 11 November 2025 the "Responsible Builder Policy" requires every developer, including personal projects, to request and receive explicit approval. Self-service OAuth registration closed, and approval reportedly takes 2–4 weeks.
  - The free tier is non-commercial at 100 queries per minute per OAuth client ID.
  - Commercial access has no published rate card; third-party reports cite about USD 12,000/month for about 50M calls (≈ USD 0.24 per 1,000).
  - Sources (all secondary): [redditapis.com: Responsible Builder Policy](https://www.redditapis.com/reddit-responsible-builder-policy); [Medium: Reddit is winding down its public API (2026)](https://medium.com/@idoavnir/reddit-is-winding-down-its-public-api-here-is-what-it-costs-you-in-2026-1dc42ff47e36); [CreatorCrawl: Is the Reddit API free in 2026?](https://creatorcrawl.com/blog/reddit-api-pricing-2026/); [Prowlo: Reddit Data API terms 2026](https://prowlo.com/blog/reddit-data-api); [xpoz.ai](https://www.xpoz.ai/blog/guides/reddit-api-pricing-tiers-and-alternatives/)
- **X API [ST]:**
  - The official API is billed pay-per-use for new developers, and the Free, Basic and Pro tiers were retired "as of September 2026".
  - Post reads cost about USD 0.005 each, with a 3 million reads/month cap before Enterprise. User reads cost USD 0.010; owned reads USD 0.001.
  - Sources (all secondary): [Outstand: X API pricing 2026](https://www.outstand.so/blog/x-api-pricing); [Postproxy: X API pricing 2026](https://postproxy.dev/blog/x-api-pricing-2026/); [twitterapi.io cost breakdown 2026](https://twitterapi.io/blog/x-api-cost-breakdown-2026); [SocialCrawl](https://www.socialcrawl.dev/blog/x-twitter-api-2026)
- **Google Trends [ST][LT]:**
  - Google announced an official Trends API (alpha) on 24 July 2025. As of September 2026 it was still application-gated with no published pricing — [dev.to: pytrends is dead (2026)](https://dev.to/esteban_ortega/pytrends-is-dead-heres-how-to-get-google-trends-data-in-2026-1a18); [ScrapeBadger: Does Google Trends have an API? (2026)](https://scrapebadger.com/blog/does-google-trends-have-an-api-what-to-use-in-2026). The official pages are listed as [developers.google.com/search/apis/trends](https://developers.google.com/search/apis/trends) and the [July 2025 launch post](https://developers.google.com/search/blog/2025/07/trends-api), per [HimanshuJ16/Algo-Trading-Skills references](https://github.com/HimanshuJ16/Algo-Trading-Skills); neither page was fetched.
  - pytrends' GitHub repo is **archived** (last push 2024-08-10, per the GitHub API) — [GeneralMills/pytrends](https://github.com/GeneralMills/pytrends). Secondary sources say it was archived in April 2025 and several of its methods now return 404 — [apiserpent: pytrends dead](https://apiserpent.com/blog/pytrends-dead-google-trends-data-2026)
- **Wikipedia pageviews [ST][LT]:** the commonly used per-article REST endpoint pattern is `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/{access}/{agent}/{article}/{granularity}/{start}/{end}`. A test call for `no.wikipedia/.../Equinor/daily/20260901/20260930` was **blocked** (wikimedia.org EGRESS_BLOCKED), so this pattern is **unverified** here.
- **StockTwits, YouTube, Flashback, Nordic FinTwit:** no 2026-verified information gathered (see Gaps).
- **Finland/Denmark (secondary):** Finnish Shareville moved to `nordnet.fi/foorumi` in 2024 — [nordnetFI on X](https://x.com/nordnetFI/status/1803699490362163467). Danish Nordnet website endpoints work the same way (`www.nordnet.dk/api/2/...`) — [FlemmingJahn/NordnetAktieScreener](https://github.com/FlemmingJahn/NordnetAktieScreener)

### Inferences
- **Most practical stack for this app:**
  - Daily owner counts from Nordnet and Avanza.
  - Nordnet bull/bear holder ratio.
  - HO-forum and Placera post counts per ticker (attention, not sentiment, as a first step).
  - Wikipedia daily pageviews per company article.
  - Optionally the Google Trends API if alpha access is granted.
- Reddit (approval needed; Nordic subreddits are small) and X (paid per read) are low value per krone for Nordic small caps.
- Forum data should be stored as derived counts and scores only, with no redistribution of raw posts, to limit ToS and GDPR exposure. Raw text contains personal data.

### Gaps
- ToS of Finansavisen forum and Placera forum on automated collection, and whether HO-forum reading requires a subscription login: not verified.
- Flashback "Aktier" subforum access/ToS, Investtech, Aksjelive and "Aksjeforum": not researched (search budget exhausted).
- Size and activity of r/aksjer, r/ISKbets, r/Aktiemarknaden and r/Avanza: not verified.
- StockTwits coverage of Oslo/Stockholm tickers and API status in 2026: not verified.
- YouTube Data API quota and cost: not verified.
- Wikipedia pageviews history depth, rate limits and User-Agent policy: not verified (wikimedia.org blocked).
- Primary pages for Reddit's policy and X's pricing: not read. Figures above come from secondary blogs.
- Finnish Inderes forum (Discourse) and Danish forums (Euroinvestor, Proinvestor): not researched.

## 6. Evidence: do retail attention, flows or owner changes predict returns? Contrarian or momentum, and at which horizon?

### Takeaway
The literature points to a **horizon split**:
- **Attention shocks and herding** produce short-lived positive price pressure, roughly days to two weeks, followed by **reversal**. Intense herding predicts **negative** returns over about 20 days.
- **Ordinary retail net buying**, which is typically contrarian, predicts **positive** returns over one week to one month (liquidity provision).

The only Nordic primary evidence verified here is Finnish (Grinblatt & Keloharju): households are contrarian and underperform momentum-trading foreigners. No study using Nordnet or Avanza owner counts was found.

### Cited Findings
- **Finland, Grinblatt & Keloharju (2000):** using Finland's shareholder register, foreign investors tend to be momentum investors (buy past winners, sell past losers), while domestic investors, especially households, tend to be contrarians. Foreign investors' portfolios seem to outperform households' portfolios even after controlling for behavioural differences — [JFE 55(1), 2000](https://doi.org/10.1016/S0304-405X(99)00044-6) (title and issue confirmed in [an issue listing](https://github.com/danielyang1009/light-speed-engine)) **[LT]**
- **Finland, Grinblatt & Keloharju (2001):** daily trades of virtually all Finnish investors show that past returns and historical price patterns (e.g. a stock at a monthly high or low), reluctance to realise losses, and tax-loss selling drive buy and sell decisions — ["What Makes Investors Trade?", JF 56(2)](https://doi.org/10.1111/0022-1082.00338) **[ST][LT]**
- **Attention-driven buying, Barber & Odean (2008):** individual investors are net buyers of attention-grabbing stocks: stocks in the news, with high abnormal volume, or with extreme one-day returns — [RFS 21(2)](https://doi.org/10.1093/rfs/hhm079) **[ST]**
- **Google search attention, Da, Engelberg & Gao (2011):** Google Search Volume Index likely measures retail attention. An increase in SVI predicts higher prices over the next 2 weeks and an eventual reversal within the year — [JF 66(5), 1461–1499](https://doi.org/10.1111/j.1540-6261.2011.01679.x) **[ST]** (drift) / **[LT]** (reversal)
- **Retail herding, Barber, Huang, Odean & Schwarz (2022):** Robinhood users engage in more attention-induced trading, and intense buying by them forecasts negative returns. Average 20-day abnormal returns are −4.7% for the top stocks purchased each day (abstract) — [JF 77(6), first page 3141](https://doi.org/10.1111/jofi.13183); [SSRN 3715077](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3715077) **[ST]**
- **Retail as liquidity providers, Kaniel, Saar & Titman (2008):** NYSE individuals buy after prior-month declines and sell after increases. Positive excess returns follow intense individual buying in the next month, and negative ones follow selling, consistent with individuals providing liquidity — [JF 63(1), first page 273](https://doi.org/10.1111/j.1540-6261.2008.01316.x) **[ST]** (about 1 month)
- **Retail order imbalance, Boehmer, Jones, Zhang & Zhang (2021):** stocks with net retail buying outperform those with net selling over the following week — [JF 76, 2249](https://doi.org/10.1111/jofi.13033). The identification method was later challenged: Barber, Huang, Jorion, Odean & Schwarz (2024, JF 79:2403) and Ardia, Aymard & Cenesizoglu (2025) report "Different Conclusions" for a recent period — [references listed in clemaymd/RevisitBJZZ](https://github.com/clemaymd/RevisitBJZZ); [SSRN 4703056](https://ssrn.com/abstract=4703056) **[ST]**
- **Media tone, Tetlock (2007):** high media pessimism predicts downward pressure on market prices followed by reversion (index level) — [JF 62(3)](https://doi.org/10.1111/j.1540-6261.2007.01232.x)
- **Search volume and the market, Preis, Moat & Stanley (2013):** Google Trends search volumes for financial terms were used to construct trading strategies on the DJIA (index level) — [Scientific Reports 3:1684](https://doi.org/10.1038/srep01684)

### Inferences
- **Short-term sleeve:**
  - Treat *onset* attention, such as a jump in Avanza or Nordnet owners, a forum post spike, or a Wikipedia/Google spike, as a weak continuation signal only over 1–10 trading days.
  - Treat *extreme* herding, such as top-decile owner jumps or a Nordnet "most bought" headline, as a fade or avoid signal over about 20 days.
  - Retail buying *after price declines* (contrarian) has historically preceded positive next-week to next-month returns. Condition the owner-change signal on the prior return.
- **Long-term value sleeve:** retail popularity is not a value signal. Finnish households (contrarian) underperformed momentum-trading foreigners. Use retail crowding (owners relative to market cap; 3–12-month owner growth) mainly as a risk or crowding penalty, and test whether it predicts within-year reversal as in Da et al.
- All of these are US or Finnish results, so the app's prediction log should include explicit A/B tags for "attention-momentum" vs "attention-contrarian" at 1, 5, 20 and 60 trading-day horizons. Calibrate the sign per sleeve on Nordic data before giving it weight.

### Gaps
- No peer-reviewed or working-paper study using **Nordnet or Avanza owner counts, Nordnet Social, HO-forum or Placera** to predict Nordic returns was located. The search budget was exhausted, and Crossref/OpenAlex were blocked.
- Norwegian register studies (e.g. Døskeland & Hvide, JF 2011; Betermier, Calvet, Knüpfer & Kvaerner on Norwegian investor portfolios) and Swedish household studies (Calvet, Campbell & Sodini) were not verified this session.
- Message-board and social-media evidence was not re-verified this session: Antweiler & Frank (2004, JF) on message boards, Chen, De, Hu & Hwang (2014, RFS) on Seeking Alpha, Moat et al. (2013) on Wikipedia views, Kumar & Lee (2006, JF) on retail sentiment comovement, and Siikanen et al. (2018, FRL) on Facebook and Finnish households.
