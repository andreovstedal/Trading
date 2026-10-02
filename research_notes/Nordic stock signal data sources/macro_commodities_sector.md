# Macro, rates/FX, commodity and sector alternative data driving Norwegian and Swedish equities (Danish/Finnish secondary): free-access methods, October 2026

How to read these notes:
- **Sleeve tags.** **[ST]** = short-term trading sleeve (intraday to a few days). **[LT]** = long-term value sleeve (months to years).
- **How endpoints were checked.** Almost every primary-source domain was blocked by the egress proxy during this session: riksbank.se, ssb.no, scb.se, eia.gov, nordpoolgroup.com, transparency.entsoe.eu, hydro.com, investors.boliden.com, sec.gov, cdn.equinor.com, opec.org, live.euronext.com, fishpool.eu, cran.r-project.org and arxiv.org. The shared WebSearch budget also ran out partway through. Endpoints were therefore checked in two ways:
  - **"verified-in-code"**: the URL appears in working open-source clients on GitHub, many of them committed in 2025–2026.
  - **"doc-excerpt"**: the URL appears in search-result excerpts of official documentation.
- **What "verified" does not mean.** No endpoint was live-tested. Anything not seen in either form is labelled **unverified**.

---

## 1. Rates, FX and macro APIs: Norges Bank, Riksbank, ECB, FRED, SSB, SCB, Statistics Denmark, Statistics Finland, PMIs and confidence indicators

### Takeaway
Every core rates, FX and macro series for Norway and Sweden is available free and keyless (or with a free key) through official REST APIs.

**Norway (Norges Bank SDMX API)**
- Policy rate: `IR/B.KPRA.SD.R`
- NOWA: `SHORT_RATES/B.NOWA.ON.R`
- FX: `EXR/B.{CCY}.NOK.SP`
- Government yields: `GOVT_GENERIC_RATES/B.{tenor}.GBON`

**Sweden (Riksbank SWEA/SWESTR API)**
- Policy rate: `SECBREPOEFF`
- FX: `SEK{CCY}PMI`
- Anonymous limit: 5 requests/min. With a free key: 200 requests/min.

**Statistics offices and surveys**
- SSB and SCB moved to **PxWebApi v2** (GET queries) in autumn/October 2025.
- Konjunkturinstitutet offers a free PxWeb API, including for commercial use.

**Norway has no PMI any more.** The DNB/NIMA manufacturing PMI was **discontinued after its 1 Dec 2025 release**. Sweden's Silf/Swedbank PMI continues, but only as press releases with no API found.

### Cited Findings

#### A. Rates and FX endpoint catalog

| Series (owner) | Exact endpoint / parameters | Auth and limits | Key fields / IDs | Frequency, history, latency | Cost / licence | Sleeve | Verification / source |
|---|---|---|---|---|---|---|---|
| **Norges Bank policy rate** | `https://data.norges-bank.no/api/data/IR/B.KPRA.SD.R?format=csv&startPeriod=YYYY-MM-DD`. Also `format=sdmx-json`; `lastNObservations=1` returns the latest value. | No authentication | Flow `IR`, key `B.KPRA.SD.R` (business-daily, policy rate). CSV rows are `;`-separated with `TIME_PERIOD;OBS_VALUE`. | Business-daily series; changes at 8 decisions a year | Free | LT; ST on decision days | Verified-in-code: [Sindre31/shares-analytics `scripts/fetch_market.py`](https://github.com/Sindre31/shares-analytics), [mortennordbye/headroom `server/norgesBank.js`](https://github.com/mortennordbye/headroom), [Sindre31/STB `scripts/update-data.mjs`](https://github.com/Sindre31/STB). No-auth claim: [Norges Bank open data](https://www.norges-bank.no/en/topics/statistics/open-data/), [pipeworx mcp-norges-bank](https://github.com/pipeworx-io/mcp-norges-bank). |
| **NOWA (Norwegian overnight rate)** | `https://data.norges-bank.no/api/data/SHORT_RATES/B.NOWA.ON.R?format=csv&startPeriod=...&endPeriod=...&locale=en` | No authentication | Use key `.R` (rate). The wildcard key `B.NOWA..` also returns volume/COUNT rows, which one client warns "is a plausible-looking integer and not a rate at all". | Daily | Free | LT (bank NII, discount rates) | Verified-in-code: [yieldcurvemonkey/ARBS `official_sources.py`](https://github.com/yieldcurvemonkey/ARBS), [tfm000/florin `stats/risk_free.py`](https://github.com/tfm000/florin), [frefrik/norway-finance-statistics `get_rates.py`](https://github.com/frefrik/norway-finance-statistics) |
| **NOK exchange rates** | `https://data.norges-bank.no/api/data/EXR/B.USD.NOK.SP?format=csv&startPeriod=...&endPeriod=...&locale=en`. Official example uses `format=excel-both&startPeriod=2023-05-15&endPeriod=2024-05-15&locale=no`. | No authentication | Key pattern `B.{ISO4217}.NOK.SP`; covers 40+ currencies against NOK | Business-daily | Free | ST and LT (FX translation for exporters) | Doc-excerpt: [Norges Bank open data](https://www.norges-bank.no/en/topics/statistics/open-data/), [Norges Bank data-portal guide](https://www.norges-bank.no/en/topics/statistics/open-data/guide-data-warehouse/), [pipeworx mcp-norges-bank](https://github.com/pipeworx-io/mcp-norges-bank) |
| **Norwegian government yields and T-bills** | `https://data.norges-bank.no/api/data/GOVT_GENERIC_RATES/B.3Y+5Y+10Y.GBON?format=csv&startPeriod=2019-01-01&endPeriod=...&locale=en`. T-bills: `B.3M+6M+12M.TBIL`. Combined: `B.7Y+6M+5Y+3Y+3M+12M+10Y.GBON+TBIL.` | No authentication | Flow `GOVT_GENERIC_RATES`; tenors joined with `+`. Flow `GOVT_KEYFIGURES` also exists. | Daily; one client downloaded 2019→2026-06-09 on 2026-06-11 | Free | LT (real estate, banks, valuation discount rate) | Verified-in-code: [tSLoseth/nok-monetary-policy-event-study `data/raw/manifest.json`](https://github.com/tSLoseth/nok-monetary-policy-event-study), [JonasHasl/finpage](https://github.com/JonasHasl/finpage). Flow list: [pipeworx](https://github.com/pipeworx-io/mcp-norges-bank). |
| **Riksbank SWEA (policy rate, STIBOR, FX)** | Range: `https://api.riksbank.se/swea/v1/Observations/{seriesId}/{from}[/{to}]`, e.g. `/Observations/SECBREPOEFF/1994-06-01`. Latest: `/Observations/Latest/seknokpmi`. Catalogue: `https://api.riksbank.se/swea/v1/Series` | Anonymous: **5 requests/min, 1,000/day**. With free key: **200 requests/min, 30,000/week**. Another client comment says "200/min, 10k/week", so the weekly cap is uncertain. Key goes in header `Ocp-Apim-Subscription-Key` or query `?subscription-key=`. | `SECBREPOEFF` policy rate; `SECBDEPOEFF` deposit rate; `SECBLENDEFF` lending rate; `SEKEURPMI`, `SEKUSDPMI`, `SEKNOKPMI`, `SEKGBPPMI`, `SEKJPYPMI`, `SEKDKKPMI`, `SEKCHFPMI` (FX fixings); STIBOR in group 3. Roughly 60 rate series and 50 FX series. | Daily | Free | LT, ST (SEK moves, decision days) | Doc-excerpt: [Riksbank series for the API](https://www.riksbank.se/en-gb/statistics/interest-rates-and-exchange-rates/retrieving-interest-rates-and-exchange-rates-via-api/series-for-the-api/), [Riksbank API FAQ](https://www.riksbank.se/en-gb/statistics/interest-rates-and-exchange-rates/retrieving-interest-rates-and-exchange-rates-via-api/faq--the-api-for-interest-rates-and-exchange-rates/). Limits and header: [robinandreeklund-collab/Berit `riksbank-mcp/src/resources.ts`](https://github.com/robinandreeklund-collab/Berit), [oneseekv1 docs](https://github.com/robinandreeklund-collab/oneseekv1), [MaxxoRelaxxo/markets-data-hub](https://github.com/MaxxoRelaxxo/markets-data-hub). Conflicting weekly cap: [UmaiTech/aura-llm-gateway](https://github.com/UmaiTech/aura-llm-gateway). |
| **SWESTR (Swedish overnight rate)** | Base `https://api.riksbank.se/swestr/v1/`. The exact `latest/SWESTR` path is **unverified**. | As SWEA | Latest SWESTR, a period of past publications, and transaction-dataset metadata | Daily | Free | LT | Doc-excerpt: [Riksbank "Collecting SWESTR via API"](https://www.riksbank.se/en-gb/statistics/swestr/collecting-swestr-via-api/). Base URL: [Berit](https://github.com/robinandreeklund-collab/Berit). |
| **Riksbank forecasts API** | Base `https://api.riksbank.se/forecasts/v1/`; paths **unverified** | As SWEA | Riksbank's own macro and policy-rate forecasts | At each Monetary Policy Report | Free | LT | Verified-in-code (base only): [Berit](https://github.com/robinandreeklund-collab/Berit) |
| **ECB Data Portal (EUR/NOK, EUR/SEK, euro rates)** | `https://data-api.ecb.europa.eu/service/data/EXR/M.USD.EUR.SP00.A?format=csvdata` (documented example). By the same pattern, `EXR/D.NOK.EUR.SP00.A` and `EXR/D.SEK.EUR.SP00.A` (daily) are pattern-derived. | No key; no published rate limit | `EXR` dataflow; `format=csvdata`, SDMX-JSON or XML; `startPeriod`, `endPeriod` | Daily reference rates | Free | ST and LT (FX), DK/FI rates | Doc-excerpt: [ECB API overview](https://data.ecb.europa.eu/help/api/overview), [ECB data examples](https://data.ecb.europa.eu/help/api/data-examples), [EconIndx guide](https://econindx.com/guides/getting-started-ecb/) |
| **FRED (St. Louis Fed)** | `https://api.stlouisfed.org/fred/series/observations?series_id={ID}&api_key={KEY}&file_type=json` | Free API key | E.g. `DCOILBRENTEU` (Brent daily). IMF monthly commodity series are listed in §2. | Varies | Free, but **third-party series carry their own copyright and licensing**: check each series' source note before republishing | LT; ST for some daily series | [FRED API docs](https://fred.stlouisfed.org/docs/api/fred/), [FRED API terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html), [EconGraph PR #252](https://github.com/EconGraph/econ-graph/pull/252), [ALFRED DCOILBRENTEU](https://alfred.stlouisfed.org/series?seid=DCOILBRENTEU) |

#### B. Statistics offices and survey bodies

| Source | Exact endpoint / parameters | Auth and limits | Notes (fields, cadence, licence) | Sleeve | Verification / source |
|---|---|---|---|---|---|
| **SSB, Statistics Norway: PxWebApi v2** | `https://data.ssb.no/api/pxwebapi/v2/tables/{tableId}/data?lang=en&valuecodes[{var}]=...&outputformat=csv&outputformatparams=separatorsemicolon,usecodesandtexts`. Salmon example: `.../tables/03024/data?lang=en&valuecodes[ContentsCode]=*&valuecodes[Varegrupper2]=*&valuecodes[Tid]=top(3)&outputformat=csv...`. JSON: `&outputFormat=json-stat2` | No key. Keep GET URLs under about 2,100 characters: past that the API returns 404, not 400. A repeated value code returns 500. Request-rate limit **unverified**. | Launched autumn 2025, built jointly with SCB. v1 stays available during a transition period. The "ready-made datasets" API was **removed 31 Dec 2025**. Licence **unverified** (ssb.no blocked). | LT; ST for the weekly salmon price | Doc-excerpt: [SSB API page](https://www.ssb.no/en/api/pxwebapi), [SSB ready-made datasets phase-out](https://www.ssb.no/en/api/ready-made-datasets--phasing-out). Verified-in-code: [PxTools user guide](https://github.com/PxTools/pxtools.github.io), [janbrus/pxwebapi-skills](https://github.com/janbrus/pxwebapi-skills), [janbrus v2 notes](https://github.com/janbrus/ssb-api-v2-examples/blob/main/new_in_v2.md). |
| **SCB, Statistics Sweden: PxWebApi v2** | `https://statistikdatabasen.scb.se/api/v2/tables/{TAB}/data?lang=en&valueCodes[...]` (GET). Metadata: `.../tables/{TAB}/metadata?lang=sv` | **Max 150,000 data cells per call; 30 calls per 10 s** | Launched in the Statistical Database in **October 2025**. Old v1 (`https://api.scb.se/OV0104/v1/doris/{lang}/ssd/`) allows 10 calls per 10 s and 100,000 values. Open data, free. Releases go out weekdays at 08:00. | LT | Doc-excerpt: [SCB PxWebApi v2](https://www.scb.se/en/services/open-data-api/pxwebapi/pxwebapi-2.0), [SCB open data](https://www.scb.se/en/services/open-data-api/). Verified-in-code: [rOpenGov/pxweb](https://github.com/rOpenGov/pxweb); [xemarap/pxstatspy NEWS](https://github.com/xemarap/pxstatspy) says "Updated base URL to the official SCB production endpoint". v1 URL: [elkassabgi/econdatalibrary](https://github.com/elkassabgi/econdatalibrary). |
| **Konjunkturinstitutet (NIER): Economic Tendency Survey / Barometerindikatorn** | `https://statistik.konj.se/PXWeb/api/v1/{en,sv}/...`. Forecast database: `https://prognos.konj.se/PXWeb/api/v1/sv/...` | 10 calls per 10 s; listed cell limits "1 k / 100 k" | Open data, downloadable without limit and free, **including for commercial use**, via website or API. Updated at the **end of each month** when Konjunkturbarometern is published. | LT; ST around release | [Konj "Så fungerar databaserna"](https://www.konj.se/statistik-och-data/sa-fungerar-databaserna/), [Konj statistics](https://www.konj.se/statistik-och-data/). Endpoint and limits: [janbrus installations list](https://github.com/janbrus/pxwebapi-skills), [nbbrd/sdmx-dl api.json](https://github.com/nbbrd/sdmx-dl), [christianlindell/fetchpxw](https://github.com/christianlindell/fetchpxw). |
| **Swedish Forest Agency (Skogsstyrelsen) PxWeb** (timber and roundwood statistics for SCA, Holmen) | `https://pxweb.skogsstyrelsen.se/api/[version]/[lang]` | 10 calls per 10 s | Specific timber-price tables **unverified** | LT | [janbrus installations list](https://github.com/janbrus/pxwebapi-skills) |
| **Statistics Denmark (secondary)** | `https://api.statbank.dk/v1/data` (JSON REST, POST). Metadata: `https://api.statbank.dk/v1/tableinfo?id={tid}&format=JSON&lang=en` | No auth | Not PxWeb; `lang=en` matters | LT | Verified-in-code: [LeRaffl-Gallery interfaces doc](https://github.com/LeRaffl/LeRaffl-Gallery), [econdatalibrary](https://github.com/elkassabgi/econdatalibrary) |
| **Statistics Finland (secondary)** | `https://pxdata.stat.fi/PxWeb/api/v1/en/StatFin/{path}.px`: GET for metadata, POST for the query | No auth | A PxWebApi v2 rollout at Statistics Finland is **unverified** | LT | Verified-in-code: [LeRaffl-Gallery](https://github.com/LeRaffl/LeRaffl-Gallery), [econdatalibrary](https://github.com/elkassabgi/econdatalibrary) |

#### C. PMIs and confidence indicators
- **Sweden, Silf/Swedbank manufacturing PMI**
  - September 2026: **58.1**, up from a revised 56.3 in August. This was a three-month high and the 15th straight month above the 54.3 long-term average.
  - New orders 59.5 (August 55.1); production 60.0; input costs 77.6, the highest since June. — [Sweden Herald](https://swedenherald.com/article/swedish-manufacturing-momentum-picks-up-as-pmi-rises-to-581-in-september)
  - Services and composite PMIs also exist (calendar listings). — [MQL5 calendar: manufacturing](https://www.mql5.com/en/economic-calendar/sweden/silf-swedbank-manufacturing-pmi), [services](https://www.mql5.com/en/economic-calendar/sweden/silf-swedbank-services-pmi)
  - No official machine-readable API was found (see Gaps).
- **Norway, DNB/NIMA manufacturing PMI: discontinued**
  - Trading Economics states the PMI "was officially discontinued by the source, with the last release published on December 1, 2025". That release showed November 2025 at 53.0, up from 48.2.
  - Index weights were: new orders 30%, output 25%, employment 20%, supplier delivery times 15%, stocks of purchases 10%; survey of 300 companies.
  - — [Trading Economics news](https://tradingeconomics.com/norway/manufacturing-pmi/news/506310), [Trading Economics forecast page](https://tradingeconomics.com/norway/manufacturing-pmi/forecast)
- **Sweden, Konjunkturinstitutet Barometerindikatorn (monthly)**
  - 2026 releases include 29 Jan ("small changes"), 25 Mar ("normally strong mood") and 26 Jun ("manufacturing lifts the barometer indicator"). — [Konj Jan 2026](https://www.konj.se/publikationer/konjunkturbarometern/2026-01-29-sma-forandringar-i-konjunkturbarometern), [Konj Mar 2026](https://www.konj.se/publikationer/konjunkturbarometern/2026-03-25-fortsatt-normaltstarkt-stamningslage/), [Konj Jun 2026](https://www.konj.se/publikationer/konjunkturbarometern/2026-06-26-tillverkningsindustrin-lyfter-barometerindikatorn/)
  - The methodology handbook was updated 24 Jun 2026. — [Konj metodbok](https://www.konj.se/media/o2jni00n/metodbok.pdf)

#### D. Service changes and discontinuations (rates, macro)

| Date | Change | Source |
|---|---|---|
| Autumn 2025 | SSB launched **PxWebApi v2**. v1 is kept "until we have a good solution for handling the transition". | [SSB](https://www.ssb.no/en/api/pxwebapi) |
| Oct 2025 | SCB launched **PxWebApi v2** in the Statistical Database (150,000 cells; 30 calls per 10 s) | [SCB](https://www.scb.se/en/services/open-data-api/pxwebapi/pxwebapi-2.0) |
| 1 Dec 2025 | Last **DNB/NIMA Norway manufacturing PMI**; series discontinued | [Trading Economics](https://tradingeconomics.com/norway/manufacturing-pmi/news/506310) |
| 31 Dec 2025 | SSB "ready-made datasets" API removed | [SSB](https://www.ssb.no/en/api/ready-made-datasets--phasing-out) |
| 6 May 2026 | Norges Bank **raised** the policy rate from 4.00% to **4.25%** (held at 4.00% on 21 Jan and 25 Mar; held at 4.25% on 17 Jun and 12 Aug) | [NB Jan](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/january-2026/), [NB Mar](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/march-2026/), [NB May](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/may-2026/), [NB Jun](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/june-2026/), [NB Aug](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/august-2026/) |

### Inferences
- **Minimal free rates/FX stack for the app.**
  - Norges Bank: `IR`, `SHORT_RATES`, `EXR`, `GOVT_GENERIC_RATES`.
  - Riksbank SWEA: register for the free key, because the anonymous limit is only 5 requests/min.
  - ECB EXR: for EUR crosses and DK/FI.
  - FRED: for US yields and the dollar.
  - All are daily, keyless or free-key, and cover both sleeves.
- **What the series are for.**
  - Rates feed bank net-interest-income models and real-estate valuation [LT].
  - FX feeds exporter translation effects [ST/LT]. NOK and SEK moves change NOK/SEK-reported earnings of USD/EUR earners such as Equinor, Mowi, Boliden and Evolution.
- **Statistics bulk pulls.** Build the SSB and SCB clients against **v2 now**. Both offices invested in v2 in 2025, and SSB has already retired one legacy product. v1 is likely to be retired eventually, but no date was found.
- **Replacing the Norwegian PMI.** It has to be substituted with Norwegian alternatives:
  - Norges Bank's Regional Network survey (flow `REGNET` appears only in one AI-generated notes file: [terragis-terminal notes](https://github.com/JsonTheRuler/terragis-terminal); the flow and keys are **unverified**).
  - SSB business tendency surveys.
  - The Swedish, euro-area and US PMIs as proxies.
- **Swedish PMI collection.** It is press-release-only, so the app must scrape it or enter it by hand.

### Gaps
- **SSB:** API rate limit and licence (CC BY 4.0 is likely but **unverified**, because ssb.no was blocked).
- **Riksbank:** weekly cap with a key is uncertain (30,000 vs 10,000); there is a source conflict above.
- **Riksbank series IDs:** government-bond yields and the exact SWESTR path are **unverified**.
- **Legacy Riksbank SOAP service:** whether "SweaWS" (`swea.riksbank.se/sweaWS`) has been retired is **unverified**; only its documentation pages were seen ([SweaWS quick start](https://swea.riksbank.se/sweaWS/docs/api/quick.htm)).
- **Norges Bank licence:** terms of use for API data were not retrieved.
- **ECB keys for €STR and euro yield curves:** not verified; only the EXR pattern was confirmed.
- **Norway PMI replacement:** no information found on whether any successor launched in 2026.
- **Swedbank/Silf PMI:** no official API or CSV feed found; release time of day unverified.
- **Statistics Finland:** PxWebApi v2 rollout status unverified.
- **Danmarks Nationalbank:** rate/FX table IDs in Statbank not verified.

---

## 2. Commodity and sector-driver data: oil/gas, salmon, Nordic power, freight, metals, pulp, gold/silver, EU carbon

### Takeaway
Free, programmatic access is good for most drivers:
- **Oil and gas:** EIA API v2 (free key), FRED, Yahoo futures tickers `BZ=F` and `TTF=F`.
- **Salmon:** SSB table 03024 (weekly, every Wednesday 08:00).
- **Nordic power by bidding zone:** ENTSO-E (free token, 400 requests/min, 15-minute resolution since 1 Oct 2025), plus community JSON mirrors for NO1–NO5 and SE1–SE4.
- **Container freight:** Drewry WCI and SCFI (free, weekly web pages).
- **Metals:** LME official prices free only next-day delayed after registration. Free proxies are COMEX/CME Yahoo tickers, IMF monthly series on FRED and SHFE via akshare.
- **Gold:** LBMA JSON feeds (IBA licence caveats).
- **EUA carbon:** EEX primary auction results; Ember (CC BY 4.0).

Paid or opaque:
- **Baltic Exchange** freight indices.
- **Nord Pool's official API**: EUR 2,700 per region per year for day-ahead prices only, per a third-party profile.
- **Fastmarkets FOEX** pulp indices.
- Access to the **Sitagri SISALMONI** salmon index (cost unknown).

### Cited Findings

#### A. Oil and gas [ST and LT]

| Series | Endpoint / access | Auth / limits | Frequency / history / latency | Cost / licence | Verification / source |
|---|---|---|---|---|---|
| **Brent spot (EIA `RBRTE`), WTI (`RWTC`)** | `https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key={KEY}&frequency=daily&data[0]=value&facets[series][]=RBRTE&start=YYYY-MM-DD&end=YYYY-MM-DD&sort[0][column]=period&sort[0][direction]=asc&offset=0&length=5000` | Free EIA API key. `length=5000` per request is used in client code; the official cap is **unverified**. | Daily from **1987-05-20**. On 2 Oct 2026 the FRED/ALFRED mirror ran to **2026-09-29**, i.e. several days behind, so this is not usable for overnight signals. | Free (US government) | Verified-in-code: [scottstanfield/oil `bin/update.sh`](https://github.com/scottstanfield/oil), [UP2CLOUD/global-chokepoints `app/lib/eia.ts`](https://github.com/UP2CLOUD/global-chokepoints), [kiingkunal/HEIMDALL](https://github.com/kiingkunal/HEIMDALL). History: [ALFRED DCOILBRENTEU](https://alfred.stlouisfed.org/series?seid=DCOILBRENTEU), [datahub oil-prices](https://datahub.io/core/oil-prices). |
| **Henry Hub (EIA `RNGWHHD`)** | `https://api.eia.gov/v2/natural-gas/pri/sum/data/` (same parameter style) | Free key | Daily | Free | Verified-in-code: [UP2CLOUD/global-chokepoints](https://github.com/UP2CLOUD/global-chokepoints) |
| **FRED Brent `DCOILBRENTEU`** | FRED API (see §1) | Free key | Daily (EIA source) | Free | [ALFRED](https://alfred.stlouisfed.org/series?seid=DCOILBRENTEU) |
| **Front-month futures on Yahoo**: Brent `BZ=F`, WTI `CL=F`, Henry Hub `NG=F` | Unofficial Yahoo chart endpoints or the yfinance library (`query1.finance.yahoo.com` is blocked in this research environment) | None (unofficial) | Intraday and daily. The only free source that captures **overnight moves before the Oslo open**. | Free; no official licence | Ticker usage: [MeetJain23/CONFLUX `metadata/templates.py`](https://github.com/MeetJain23/CONFLUX) |
| **Dutch TTF gas** `TTF=F` (contract months such as `TTFV26.NYM`); `TTG=F` (TTF financial) | Yahoo quote and history pages; Investing.com historical pages (manual) | None | Daily and intraday | Free (personal use) | [Yahoo TTF=F futures chain](https://finance.yahoo.com/quote/TTF=F/futures/), [Yahoo TTG=F history](https://finance.yahoo.com/quote/TTG=F/history/), [Investing.com TTF historical](https://www.investing.com/commodities/dutch-ttf-gas-c1-futures-historical-data) |
| **IMF monthly commodity prices on FRED** | `POILBREUSDM` (Brent), `PNGASEUUSDM` (European gas), `PALUMUSDM`, `PCOPPUSDM`, `PNICKUSDM`, `PZINCUSDM`, `PIORECRUSDM` (iron ore), `PTINUSDM`, `PLEADUSDM`, **`PSALMUSDM` (salmon)** | Free FRED key | Monthly | Free (IMF source) | Verified-in-code: [alikatgh/benchmarkwatcher `scripts/commodities.json`](https://github.com/alikatgh/benchmarkwatcher), [londrwus/techeu_agentichack](https://github.com/londrwus/techeu_agentichack) |

- **NBP (UK gas) free source:** not found (see Gaps).

#### B. Salmon [ST weekly event, LT earnings]
- **SSB table 03024: what it contains**
  - Weekly export price (NOK/kg) and export volume (tonnes) for farmed fresh/chilled and frozen salmon, compiled from Norwegian customs declarations covering all salmon exports.
  - The price covers all weight classes and qualities. It is the price at the border, including freight and terminal costs.
  - It is widely treated as the official reference price.
  - Released **every Wednesday at 08:00**, covering the previous week. Some aggregators note Wednesday or Thursday publication.
  - — [SSB salmon statistics](https://www.ssb.no/en/utenriksokonomi/statistikker/laks), [SSB (Norwegian)](https://www.ssb.no/utenriksokonomi/utenrikshandel/statistikk/eksport-av-laks), [Oppdrett.info](https://oppdrett.info/laksepris?lang=en)
- **SSB 03024: latest value seen.** Week 34 2026: fresh/chilled **NOK 73.52/kg**, frozen NOK 75.03/kg. — [Oppdrett.info](https://oppdrett.info/laksepris?lang=en)
- **SSB 03024: exact v2 GET URL.** `https://data.ssb.no/api/pxwebapi/v2/tables/03024/data?lang=en&valuecodes[ContentsCode]=*&valuecodes[Varegrupper2]=*&valuecodes[Tid]=top(3)&outputformat=csv&outputformatparams=separatorsemicolon,usecodesandtexts`. JSON-stat2 variant: `...?lang=en&outputFormat=json-stat2`. — [PxTools PxWebApi user guide](https://github.com/PxTools/pxtools.github.io), [janbrus/pxwebapi-skills `laks_eng.ipynb`](https://github.com/janbrus/pxwebapi-skills)
- **SSB 03024: other community collectors.** Projects already pull the weekly SSB 03024 price programmatically. — [magnusihle/SalmonFlipper issue #6](https://github.com/magnusihle/SalmonFlipper/issues/6)
- **Sitagri Salmon Index (SISALMONI): definition**
  - The weekly exporters' selling price for fresh Superior Atlantic Salmon (head-on gutted).
  - It reflects a weekly spot price of **11 benchmarks** for salmon transported from Norway to Europe.
  - It is calculated from physical transactions reported by a panel of Norwegian exporters.
  - — [Sitagri](https://www.sitagri.com/sitagri-salmon-index/), [Fish Pool SISALMONI page](https://fishpool.eu/sisalmoni/)
- **Euronext Salmon Futures: contract terms**
  - Cash-settled; quoted in **EUR per tonne**; minimum tick EUR 10/t.
  - Monthly settlement is the arithmetic average of the weekly Sitagri index for the expiring month.
  - The **SISALMONI 3–6 kg** index has been used for 100% of settlement **since 22 July 2024**.
  - Listed on Euronext Paris and cleared by Euronext Clearing. Sitagri Index Services is a BMR-compliant price reporting agency.
  - — [Euronext technical specifications (Oct 2025)](https://live.euronext.com/sites/default/files/documentation/contract-specifications/20251006%20-%20Euronext%20Technical%20specifications%20of%20the%20Salmon%20Futures%20contract.pdf), [Euronext salmon derivatives](https://live.euronext.com/en/products/commodities/salmon-derivatives), [Euronext contract specs](https://live.euronext.com/en/resources/contracts-specifications/commodity-futures-salmon)
- **History of the salmon index**
  - Fish Pool merged with Oslo Børs on the Euronext platform and shifted to EUR trading. — [Salmon Business](https://www.salmonbusiness.com/fish-pool-shifts-to-euro-trading-as-it-merges-with-oslo-bors-on-euronext-platform/)
  - FinanceAgri became operator of the spot price index previously called the "Nasdaq Salmon Index". — [Fish Pool notice](https://fishpool.eu/financeagri-is-the-new-operator-of-the-spot-price-index-today-called-nasdaq-salmon-index/)
- **IMF monthly salmon price** `PSALMUSDM` on FRED — [benchmarkwatcher](https://github.com/alikatgh/benchmarkwatcher)

#### C. Nordic power by bidding zone [ST for power-intensive names and Hydro; LT for renewables and utilities]

| Source | Endpoint | Auth / limits | Resolution / latency | Cost / licence | Verification / source |
|---|---|---|---|---|---|
| **ENTSO-E Transparency Platform** (official, all zones) | `GET https://web-api.tp.entsoe.eu/api?securityToken={TOKEN}&documentType=A44&in_Domain={EIC}&out_Domain={EIC}&periodStart=YYYYMMDDHHMM&periodEnd=YYYYMMDDHHMM`. Returns IEC 62325 XML; a day-ahead query returns 24 h starting at local midnight. | Free token: register, then email transparency@entsoe.eu with subject "Restful API access"; arrives within days. **400 requests/min**. | **PT60M before 2025-10-01, PT15M after.** Parse the resolution per `Period`; do not assume it. | Free; reuse terms **unverified** | Token: [QAnders setup guide](https://github.com/QAnders/IVT-HP-PriceControl/blob/main/Entsoe-API-Setup.md), [Progrunners](https://progrunners.com/entso-e-api/). Resolution: [whipeeer-creator/entsoe-quickstart](https://github.com/whipeeer-creator/entsoe-quickstart). Limit: [maurorisso/ECTL README](https://github.com/maurorisso/ECTL), [clemensv/real-time-sources](https://github.com/clemensv/real-time-sources). |
| **ENTSO-E EIC zone codes** | NO1 `10YNO-1--------2`; NO2 `10YNO-2--------T`; NO3 `10YNO-3--------J`; NO4 `10YNO-4--------9`; NO5 `10Y1001A1001A48H`; SE1 `10Y1001A1001A44P`; SE2 `10Y1001A1001A45N`; SE3 `10Y1001A1001A46L`; SE4 `10Y1001A1001A47J`; DK1 `10YDK-1--------W`; DK2 `10YDK-2--------M`; FI `10YFI-1--------U`. Document types: A44 price, A65 total load, A75 generation per type, A11 aggregated energy data. Process type A01 = day-ahead. | — | — | — | [EnergieID/entsoe-py `mappings.py`](https://github.com/EnergieID/entsoe-py) |
| **Nord Pool official Market Data API** | OAuth 2.0 | **Paid** "Power Data Services" subscription. Day-ahead-only prices for Nordics & Baltics: **EUR 2,700 per region per year + EUR 200 per extra API user**. | Day-ahead in 15-minute resolution once SDAC 15-min went live; Nord Pool's March 2025 notice estimated 11 June 2025, but the actual go-live was 1 Oct 2025 (see ENTSO-E row) | Paid | Pricing (third-party profile): [api-evangelist/nordpool](https://github.com/api-evangelist/nordpool). [Nord Pool API page](https://www.nordpoolgroup.com/en/trading/api/), [Nord Pool 15-min notice (Mar 2025)](https://www.nordpoolgroup.com/en/trading/Operational-Message-List/2025/03/market-data---update-for-sdac-15-minute-support-20250331132200/), [Nord Pool Power Data Services](https://www.nordpoolgroup.com/en/services/power-market-data-services/) |
| **Nord Pool public Data Portal API** (unofficial) | `https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices?market=DayAhead&date=YYYY-MM-DD&deliveryArea={NO1..NO5,SE1..SE4}&currency={EUR,NOK,SEK}` | None. **Undocumented, no SLA, may change at any time.** | Daily auction results | Free, but terms unclear | Verified-in-code: [evcc-io/evcc nordpool.yaml](https://github.com/evcc-io/evcc), [Home Assistant Nord Pool docs](https://github.com/home-assistant/home-assistant.io). Caveat: [api-evangelist/nordpool](https://github.com/api-evangelist/nordpool). |
| **hvakosterstrommen.no** (Norway, NO1–NO5) | `https://www.hvakosterstrommen.no/api/v1/prices/{YYYY}/{MM}-{DD}_{NO1..NO5}.json` | None | Daily file per zone | Free; terms and source **unverified** | Verified-in-code: [raycast nordic-energy-prices](https://github.com/raycast/extensions), [perbu/powercost](https://github.com/perbu/powercost) |
| **elprisetjustnu.se** (Sweden, SE1–SE4) | `https://www.elprisetjustnu.se/api/v1/prices/{YYYY}/{MM}-{DD}_{SE1..SE4}.json` | None | Daily file per zone | Free; terms **unverified** | Verified-in-code: [raycast nordic-energy-prices](https://github.com/raycast/extensions), [joakimeriksson/ai-smarthome](https://github.com/joakimeriksson/ai-smarthome) |
| **Energi Data Service** (Energinet; DK1/DK2) | `https://api.energidataservice.dk/dataset/DayAheadPrices?start=...&end=...&filter={"PriceArea":["DK1"]}&sort=TimeUTC%20ASC`. Fields include `DayAheadPriceDKK`, `TimeDK`, `TimeUTC`. | None | **Native 15-minute** data since 30 Sep 2025 (prices for 1 Oct 2025 onwards) | Free | Verified-in-code: [enoch85/ge-spot](https://github.com/enoch85/ge-spot), [evcc energinet-price.yaml](https://github.com/evcc-io/evcc), [athas/EggsML](https://github.com/athas/EggsML), [openHAB PR #18695](https://github.com/openhab/openhab-addons/pull/18695) |
| **Energy-Charts (Fraunhofer ISE)** | `https://api.energy-charts.info/price?bzn=NO2&start=YYYY-MM-DD&end=YYYY-MM-DD`. NO2 confirmed; other Nordic zones **unverified**. | None | Daily/hourly; NO2 history at least 2019–2025 | A 2026 download receipt records **CC BY 4.0** (attributed to Bundesnetzagentur/SMARD.de) | Verified-in-code: [evcc energy-charts template](https://github.com/evcc-io/evcc), [avasfx receipt JSON](https://github.com/avasfx/Temporal-aggregation-and-investment-errors-in-industrial-heat-pump-and-storage-systems), [mampfes/ha_epex_spot](https://github.com/mampfes/ha_epex_spot) |

- **Energi Data Service changes, 2025**
  - The legacy **Elspotprices** dataset was **discontinued 30 Sep 2025**. It remains available for history only.
  - **DayAheadPrices** was created empty on 8 May 2025 and has carried data since 30 Sep 2025.
  - — [openHAB PR #18695](https://github.com/openhab/openhab-addons/pull/18695), [ge-spot](https://github.com/enoch85/ge-spot), search excerpts of the Energi Data Service notices ([EnergiMCP](https://github.com/manas-katyal/energimcp))

#### D. Freight [ST for shipping names; LT for the cycle]
- **Baltic Exchange indices (paid)**
  - The Baltic Dry Index is issued daily by the London-based Baltic Exchange and disseminated through Reuters and other vendors. — [Wikipedia: BDI](https://en.wikipedia.org/wiki/Baltic_Dry_Index), [Baltic Exchange dry services](https://www.balticexchange.com/en/data-services/market-information0/dry-services.html)
  - Free display (not an API) exists on Trading Economics. — [Trading Economics BDI](https://tradingeconomics.com/commodity/baltic)
  - The 2026 price of a Baltic data subscription was not found.
- **ETF proxies: BDRY (dry bulk) and BWET (tankers)**
  - BDRY tracks near-quarter dry-bulk freight futures, weighted Capesize 50%, Panamax 40%, Supramax 10%, rebalanced annually.
  - Futures are an imperfect proxy for spot, and contango causes roll decay.
  - BWET is the tanker equivalent.
  - BDRY is now issued by Amplify ETFs.
  - — [ETF Database BDRY](https://etfdb.com/etf/BDRY/), [etf.com BDRY](https://www.etf.com/BDRY), [Amplify BDRY prospectus](https://amplifyetfs.com/wp-content/uploads/files/Amplify_BDRY_Prospectus.pdf)
- **Drewry World Container Index (free)**
  - Weekly composite USD per 40-ft container plus 8 route sub-indices: Shanghai to Rotterdam, Los Angeles, Genoa and New York; Rotterdam to Shanghai and New York; New York to Rotterdam; Los Angeles to Shanghai.
  - Free public web page at `https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry`.
  - akshare exposes `drewry_wci_index()`.
  - — [3pacs/GRID `container_freight.py`](https://github.com/3pacs/GRID), [dbk000/mcas source registry ("cost_tier": "free", weekly)](https://github.com/dbk000/mcas)
- **Shanghai Containerized Freight Index (SCFI)**
  - Published **Fridays** by the Shanghai Shipping Exchange; free web page `https://en.sse.net.cn/indices/scfinew.jsp`. — [3pacs/GRID](https://github.com/3pacs/GRID)
- **Tanker-rate nowcast from Frontline's disclosures**
  - Q2 2026: annual cash-generation potential of **USD 2.3 bn (USD 10.35/share)** at the 28 Aug spot rates; ±30% rates gives USD 3.1 bn / USD 1.5 bn. — [TradingKey Q2 2026 transcript](https://www.tradingkey.com/news/transcripts/262141186-tradingkey)
  - An earlier 2026 call gave USD 1.5 bn (USD 7/share), with ±30% giving USD 2.1 bn / USD 1.0 bn.
  - VLCC cash breakeven about **USD 24,300/day** over the next 12 months.
  - — [Motley Fool Q1 2026 transcript](https://www.fool.com/earnings/call-transcripts/2026/05/25/frontline-fro-q1-2026-earnings-call-transcript/), [Motley Fool Q4 2025 transcript](https://www.fool.com/earnings/call-transcripts/2026/02/27/frontline-fro-q4-2025-earnings-call-transcript/)

#### E. Metals and steel [ST via futures; LT via sensitivities]
- **LME (official benchmark)**
  - A limited set of **free data delivered next-day delayed** on LME.com after a simple registration.
  - Covers LME Official Prices for aluminium, copper, nickel, zinc, lead, tin, cobalt, aluminium alloy and NASAAC, **from the start of the current calendar year**.
  - Longer history must be bought through the LME portal. Redistribution is licensed.
  - — [LME market data FAQs](https://www.lme.com/about/faqs/market-data-faqs), [LME historical data](https://www.lme.com/market-data/accessing-market-data/historical-data), [LME data distribution](https://www.lme.com/en/market-data/market-data-licensing/data-distribution), [LMElive FAQs](https://www.lme.com/about/faqs/lmelive-faqs)
- **Free futures proxies on Yahoo** (used in open-source dashboards)
  - Aluminium `ALI=F` (COMEX); copper `HG=F`; US Midwest hot-rolled coil steel `HRC=F`; iron ore `TIO=F`; gold `GC=F`.
  - One client notes "LME nickel has no clean single Yahoo ticker".
  - — [Mamma-D/supply-chain-dashboard](https://github.com/Mamma-D/supply-chain-dashboard), [MeetJain23/CONFLUX](https://github.com/MeetJain23/CONFLUX), [Aphrodine/matrisk-ai](https://github.com/Aphrodine/matrisk-ai), [windfly2007-bot/hsing-invest-dashboard](https://github.com/windfly2007-bot/hsing-invest-dashboard)
- **SHFE continuous contracts via akshare** (`futures_zh_daily_sina(symbol)`, Sina source)
  - `CU0` copper, `NI0` nickel, `SN0` tin, `PB0` lead, `AO0` alumina, `HC0` hot-rolled coil, `RB0` rebar, `SS0` stainless, `AU0` gold, `AG0` silver, `SP0` pulp.
  - Daily columns: date/open/high/low/close/volume.
  - — [akfamily/akshare futures docs](https://github.com/akfamily/akshare), [PA_Agent source map](https://github.com/rosemarycox5334-debug/PA_Agent)
- **IMF monthly metals on FRED:** `PALUMUSDM`, `PCOPPUSDM`, `PNICKUSDM`, `PZINCUSDM`, `PIORECRUSDM` — [benchmarkwatcher](https://github.com/alikatgh/benchmarkwatcher)

#### F. Pulp, paper and forestry [LT mainly]
- **Fastmarkets FOEX PIX indices (paid)**
  - Weekly USD indices based on actual physical trades, e.g. PIX NBSK (Europe) and PIX China BHKP/NBSK net.
  - Subscription service; the May 2026 methodology document is current.
  - — [Fastmarkets PIX China Pulp methodology (May 2026)](https://www.fastmarkets.com/uploads/2026/04/PIX_Pulp_China_Methodology_May2026.pdf), [Metsä Fibre on pulp indices](https://www.metsagroup.com/metsafibre/news-and-publications/news-and-releases/stories/2021/indices-follow-the-pulp-market/)
  - Packaging (kraftliner) PIX indices also exist. — [Fastmarkets PIX Packaging Europe](https://www.fastmarkets.com/uploads/2025/05/PIX_Packaging-Europe_Methodology_May2025.pdf)
- **Free pulp proxy: SHFE bleached softwood kraft pulp futures**
  - Free historical data on Investing.com, a SHFE product page, and akshare symbol `SP0`.
  - — [Investing.com SHFE pulp historical](https://www.investing.com/commodities/shfe-bleached-softwood-kraft-pulp-futures-historical-data), [SHFE woodpulp](https://tsite.shfe.com.cn/eng/market/futures/chemical/sp/), [akshare docs](https://github.com/akfamily/akshare)
- **Swedish Forest Agency PxWeb API** (forestry statistics) — see §1B. [janbrus installations](https://github.com/janbrus/pxwebapi-skills)

#### G. Gold and silver [LT for Boliden; risk-off signal for ST]
- **LBMA JSON feeds**
  - `https://prices.lbma.org.uk/json/gold_am.json` and `.../gold_pm.json`. Pattern `{metal}_am|pm.json`.
  - The three values under `v` are USD, GBP and EUR. History goes back to 1968.
  - — [portfolio-performance help](https://github.com/portfolio-performance/portfolio-help), [Robin-Haupt-1/lbma-east-west-divergence](https://github.com/Robin-Haupt-1/lbma-east-west-divergence), [zentryHQ/zframes](https://github.com/zentryHQ/zframes)
- **LBMA licensing:** an ICE Benchmark Administration (IBA) licence is required "to obtain, use or redistribute real-time or historical benchmark data, including for pricing and valuation activities". — [LBMA Gold Price](https://www.lbma.org.uk/prices-and-data/lbma-gold-price), [LBMA Gold Price FAQs](https://www.lbma.org.uk/prices-and-data/lbma-gold-price/lbma-gold-price)
- **Free futures:** `GC=F` (Yahoo); SHFE `AU0`/`AG0` (akshare). — [CONFLUX](https://github.com/MeetJain23/CONFLUX), [PA_Agent](https://github.com/rosemarycox5334-debug/PA_Agent)

#### H. EU carbon (EUA) [LT for Hydro, SSAB, Yara, utilities; ST minor]
- **EEX primary auctions (free)**
  - Daily auction results. A free archive ZIP covers **2012–2025**, one file per year, with `Auction Price EUR/tCO2` and `Auction Volume (tCO2)`.
  - Archive URL: `https://www.eex.com/fileadmin/EEX/Downloads/Markets/Environmentals/EUA_Emission_Spot_Primary_Market_Auction_Report/Archive_Reports/emission-spot-primary-market-auction-report-2012-2025-data.zip`
  - Landing page: `https://www.eex.com/en/market-data/market-data-hub/environmentals/eex-eua-primary-auction-spot-download`
  - Tested 3 Aug 2026 by an open-source project. — [21bcarlisle-arch/synthetic-enterprise research note](https://github.com/21bcarlisle-arch/synthetic-enterprise)
- **Ember**
  - The carbon-price-viewer URL now redirects to Ember's European electricity prices tool, which includes EU and UK ETS front-month prices.
  - Licence is **CC BY 4.0** per the site footer. No CSV route was confirmed.
  - The Sandbag viewer is a JS widget with no download.
  - — [SamuelEnrique/erw price-sources](https://github.com/SamuelEnrique/erw), [synthetic-enterprise note](https://github.com/21bcarlisle-arch/synthetic-enterprise), [Ember European wholesale electricity price data](https://ember-energy.org/data/european-wholesale-electricity-price-data/)
- **Other free/paid EUA sources**
  - Investing.com EUA futures historical (free, manual). — [Investing.com](https://www.investing.com/commodities/european-union-allowance-eua-year-futures-historical-data)
  - KRBN ETF as a daily proxy. — [SamuelEnrique/erw](https://github.com/SamuelEnrique/erw)
  - Paid ICE EUA futures data via Databento. — [Databento](https://databento.com/futures/commodity/energy/emissions)

#### I. Service changes and discontinuations (commodity data)

| Date | Change | Source |
|---|---|---|
| 22 Jul 2024 | SISALMONI 3–6 kg index becomes 100% of Euronext salmon futures settlement | [Euronext spec](https://live.euronext.com/sites/default/files/documentation/contract-specifications/20251006%20-%20Euronext%20Technical%20specifications%20of%20the%20Salmon%20Futures%20contract.pdf) |
| Mar 2025 | Nord Pool announces Market Data API move to 15-minute day-ahead resolution (estimated 11 Jun 2025) | [Nord Pool notice](https://www.nordpoolgroup.com/en/trading/Operational-Message-List/2025/03/market-data---update-for-sdac-15-minute-support-20250331132200/) |
| 30 Sep / 1 Oct 2025 | SDAC 15-minute MTU live: ENTSO-E resolution PT15M from 2025-10-01; Energinet **Elspotprices discontinued**, replaced by DayAheadPrices | [entsoe-quickstart](https://github.com/whipeeer-creator/entsoe-quickstart), [ge-spot](https://github.com/enoch85/ge-spot) |
| ~1 Apr 2026 | **Stooq** CSV downloads now need an `apikey` (obtained via CAPTCHA); daily hit quota | [apis.io Stooq](https://apis.io/providers/stooq), [Stooq response](https://stooq.com/q/d/l/?i=d&s=%5Ejci) |
| 3 May 2026 | OPEC+ held its "first meeting without UAE". From then on, the monthly group is 7 countries: Saudi Arabia, Russia, Iraq, Kuwait, Kazakhstan, Algeria, Oman. | [CNBC](https://www.cnbc.com/2026/05/03/opec-announces-188000-barrels-per-day-output-increase-.html), [OPEC 6 Sep 2026](https://www.opec.org/pr-detail/1835613-6-september-2026.html) |

### Inferences
- **Oil and gas, short-term sleeve.** EIA and FRED Brent lag by days, so they are useless for overnight signals. Use them as the clean daily history for estimating betas [LT]. For live signals, take the front-month `BZ=F` and `TTF=F` values just before 09:00 CET from Yahoo or another intraday source [ST].
- **Salmon signals**
  - The SSB Wednesday 08:00 print lands **before** the Oslo open (09:00 CET, per general market knowledge), so it is a clean weekly event signal for Mowi, SalMar, Lerøy, Bakkafrost, Grieg and Austevoll [ST].
  - Monthly IMF `PSALMUSDM` plus SSB weekly history support cycle-adjusted earnings [LT].
  - The Euronext salmon forward curve would be valuable for the LT sleeve if settlement prices can be obtained free.
- **Power data.** ENTSO-E with a free token is the robust primary source. hvakosterstrommen.no and elprisetjustnu.se are simple fallbacks for NO and SE zones. Apps must handle 15-minute prices after 1 Oct 2025, e.g. by averaging to hourly or daily.
- **Freight data**
  - With no Baltic subscription, use BDRY/BWET daily prices plus listed shipping equities (Frontline, Hafnia, etc.) as market-implied freight proxies [ST].
  - Use Drewry WCI (Thursday web page) and SCFI (Friday web page) for container names such as Maersk and MPC Container Ships [ST/LT].
- **Metals data.** For daily signals, COMEX `ALI=F`/`HG=F` and SHFE via akshare approximate LME closely enough. LME official prices (free, next-day, current-year only) can be used to check the proxies against the benchmark.
- **Pulp data.** SHFE pulp (`SP0`) is the only free daily proxy; FOEX remains the contract benchmark.

### Gaps
- **SISALMONI:** free access, cost and API status unknown (fishpool.eu and live.euronext.com blocked; search budget exhausted).
- **Euronext salmon futures settlement prices:** whether they are downloadable free is unknown.
- **Baltic Exchange:** 2026 subscription prices not found.
- **Free tanker or dry-bulk spot rate series:** no API found beyond ETFs and equity proxies. Weekly broker reports (e.g. Fearnleys, Clarksons) were not researched.
- **Freightos FBX and Harpex:** terms not verified.
- **NBP (UK gas):** free source not verified.
- **Nordic power futures:** current venue and free data after the Nasdaq→Euronext transfer not researched.
- **ENTSO-E:** data-reuse licence not verified (site blocked).
- **hvakosterstrommen.no / elprisetjustnu.se:** licences and underlying data source not verified.
- **Yahoo:** terms of use not verified. yfinance is unofficial and Yahoo endpoints were blocked here.
- **EIA API:** rate limits and the official row cap not verified.

---

## 3. Sector mapping, sensitivity estimation and usefulness for the two sleeves

### Takeaway
Several large Nordic companies publish explicit earnings sensitivities to their key drivers:
- **Boliden:** per 10% move in each metal and in USD/SEK.
- **Frontline:** cash flow at ±30% tanker rates.
- **Equinor:** per USD 10/bbl oil and USD 1/MMBtu gas.
- **Norsk Hydro:** aluminium price; an older figure is cited below.

These let the app turn commodity moves into earnings nowcasts **[LT]**. Academic work shows the stock reactions are real but time-varying:
- Oil → Oslo Børs: a 10% oil rise lifts stock returns about 2.5% (Bjørnland 2009). Responses depend on the type of shock.
- Salmon equities: market-wide factors dominate monthly returns, and salmon price and harvest shocks add explanatory power (Misund).
- Swedish real estate: very high rate sensitivity in 2022–23.

For the **short-term sleeve**, overnight commodity and US moves are largely priced into the Nordic open. They are most useful as gap and risk filters and for event signals released before the open (the SSB salmon print, central-bank decisions).

### Cited Findings

#### Company-disclosed sensitivities (usable as earnings-nowcast coefficients)
- **Boliden, Q4 2024 report.** Effect of a 10% change on operating profit:

  | Driver | SEK m |
  |---|---|
  | Zinc | 950 |
  | Copper | 875 |
  | Gold | 550 |
  | Silver | 375 |
  | Nickel | 200 |
  | Lead | 150 |
  | Palladium | 30 |
  | Platinum | 30 |
  | USD/SEK | 2,200 |
  | EUR/USD | 1,350 |
  | USD/NOK | 300 |

  The figures exclude metal and currency hedging, contracted treatment charges and smelter inventory revaluation. — [Boliden Q4 2024 interim report](https://investors.boliden.com/sites/boliden-ir/files/pr/202502052475-1.pdf)
  Q2 2026 slides attributed the profit lift to metal prices despite a mine disruption. — [Investing.com Boliden Q2 2026](https://www.investing.com/news/company-news/boliden-q2-2026-slides-metal-prices-lift-profit-despite-mine-disruption-93CH-4802200)
- **Norsk Hydro**
  - Moody's (June 2025) notes "high sensitivity of EBITDA to volatile aluminium prices and exchange rates". — [Moody's credit opinion via Hydro](https://www.hydro.com/globalassets/06-investors/debt-investors/2025-06-12-moodys-credit-opinion-nhasa.pdf)
  - A search summary of Hydro's **2017** annual report cites a +10% aluminium price sensitivity of about **NOK 3,900 m annual EBIT**. This figure is old and second-hand, so treat it as low confidence. — [Hydro 2017 financial statements](https://www.hydro.com/contentassets/83119196c6d34660882cf4688afa7d58/appendix-1-financial-statements-and-board-of-directors-report-and-the-auditors-report-for-financial-year-2017.pdf)
  - Current quarterly reports exist (Q4 2025, Q2 2026), but their sensitivity tables were not retrieved. — [Hydro Q4 2025 report](https://www.hydro.com/globalassets/06-investors/reports-and-presentations/quarterly-reports/2026/q4vs2ln9p/fourth-quarter-report-2025.pdf), [GlobeNewswire Q2 2026](https://www.globenewswire.com/news-release/2026/07/22/3331070/0/en/Norsk-Hydro-Operational-strength-delivering-solid-results.html)
- **Equinor** discloses indicative effects of **+USD 10/bbl** oil and condensate and **+USD 1/MMBtu** gas price changes. It also reports ±30% commodity-derivative sensitivities in its 20-F. — [Equinor Q2 2026 financial statements (SEC)](https://www.sec.gov/Archives/edgar/data/1140625/000114062526000025/equinorfinancialstatements.htm), [Equinor annual reports](https://www.equinor.com/investors/annual-reports)
- **Frontline**: cash-flow-per-share sensitivity to ±30% spot tanker rates (see §2D). — [TradingKey](https://www.tradingkey.com/news/transcripts/262141186-tradingkey)
- **DNB** (rate pass-through lag)
  - Net interest income was NOK 15,299 m in Q1 2026 (−5.4% q/q on narrower spreads and fewer days) and NOK 15,132 m in Q2 2026 (−1.1% q/q).
  - "Customer repricing effective July 12, following Norges Bank's May rate hike of 25 basis points" supports Q3 NII.
  - — [DNB Q1 2026 report](https://www.ir.dnb.no/sites/default/files/pr/202604222797-1.pdf?ts=1776932139), [Investing.com DNB Q2 2026 transcript](https://www.investing.com/news/transcripts/earnings-call-transcript-dnb-posts-strong-q2-2026-results-as-stock-barely-moves-93CH-4789903)

#### Academic and practitioner evidence
- **Oil → Norwegian equities**
  - Bjørnland (2009, Scottish Journal of Political Economy): after a 10% increase in oil prices, stock returns in Norway increase by about **2.5%**. — [Wiley abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1467-9485.2009.00482.x)
  - A later study finds the OBX reacts positively to oil **supply** shocks, with the response peaking during the global financial crisis. — [Bournemouth eprint (JIFMIM)](http://eprints.bournemouth.ac.uk/21569/1/JIFMIM_post-print.pdf)
- **Shock type matters**
  - Sector sensitivities to petroleum shocks depend on the nature of the shock and differ between exporters and importers. — [ScienceDirect 2025](https://www.sciencedirect.com/science/article/pii/S0275531925001254)
  - Oil–stock correlations are time-varying. — [Energy Reports (time-varying effects)](https://www.sciencedirect.com/science/article/pii/S2352484719313812)
  - Oil & gas and mining sectors respond positively to oil price rises, while transport, manufacturing, chemicals and real estate tend to respond negatively. — [Bournemouth eprint](http://eprints.bournemouth.ac.uk/21569/1/JIFMIM_post-print.pdf)
  - Review of the oil-shock literature. — [Ma et al. 2025 review](https://onlinelibrary.wiley.com/doi/10.1111/joes.12680)
- **Salmon equities**
  - Misund studied 10 Oslo-listed salmon producers on monthly returns, 2006–2016.
  - Market-wide factors (market, Fama-French-Carhart factors, FX, oil) were the **most important** drivers of shareholder returns. Returns were also sensitive to **salmon price** and deviations in **harvest** volumes.
  - — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S2405851317302283), [IDEAS/RePEc working paper](https://ideas.repec.org/p/hhs/stavef/2016_017.html)
  - Related: valuation of salmon farmers, and the effect of the 2023 resource-rent tax. — [Aquaculture Economics & Management](https://www.tandfonline.com/doi/full/10.1080/13657305.2016.1228712), [Rent-tax study](https://www.tandfonline.com/doi/full/10.1080/13657305.2024.2342268)
- **Swedish real estate (rate sensitivity)**
  - Share-price falls from 2 Jan 2022 to 16 May 2023: Castellum −59%, Corem −79%, SBB −91%.
  - 59% of property bonds issued in 2020–21 (SEK 189 bn) were floating-rate, mostly indexed to 3M STIBOR, which reached 3.49% by end-April 2023.
  - Interest coverage fell from about 4.6x (2021) to 2.6x (Q3 2024). Riksbank cuts then improved the outlook.
  - — [MSCI](https://www.msci.com/research-and-insights/blog-post/the-struggles-of-sweden-property-market), [ING Think](https://think.ing.com/articles/sweden-real-estate-sector-rebounds-amid-interest-rate-cuts/), [AllianceBernstein](https://www.alliancebernstein.com/corporate/en/insights/investment-insights/will-swedens-woes-shake-europes-real-estate-markets.html), [KTH thesis on the Swedish real-estate bond market](https://kth.diva-portal.org/smash/get/diva2:1779011/FULLTEXT01.pdf)

### Inferences
**Driver map.** This table is an analytical mapping based on business models plus the cited sensitivities. Validate every link with the app's own rolling regressions before using it.

| Exchange / sector | Representative names | Primary external drivers (free series) | Secondary drivers | Sleeve |
|---|---|---|---|---|
| Oslo – E&P | Equinor, Aker BP, Vår Energi, DNO, Okea | Brent (`BZ=F`, EIA `RBRTE`); TTF (`TTF=F`); USD/NOK (Norges Bank EXR) | EUA; NOK rates | ST (overnight Brent and TTF gap); LT (price deck × disclosed sensitivity) |
| Oslo – oil services | Subsea7, TGS, Aker Solutions, rig owners | Brent level and trend (capex proxy); OPEC+ decisions | Rig and vessel day rates (paid; gap) | LT mostly; ST via Brent beta |
| Oslo – seafood | Mowi, SalMar, Lerøy, Bakkafrost, Grieg | SSB 03024 weekly price (Wed 08:00); SISALMONI / Euronext forward curve; EUR/NOK | Market factor (dominant, per Misund); harvest/biology news; resource-rent tax | ST (Wednesday event); LT (cycle-normalized EBIT/kg) |
| Oslo – shipping | Frontline, Hafnia, Okeanis, BW LPG, Wallenius Wilhelmsen, Höegh Autoliners, MPC Container Ships | BWET (tankers), BDRY (dry bulk), Drewry WCI / SCFI (containers); peer equity moves | Brent (tanker demand); USD | ST (proxy momentum); LT (Frontline-style cash-flow-yield maths) |
| Oslo – banks | DNB, SpareBank 1 banks | NOWA, Norges Bank policy rate and path, NOK government curve (`GOVT_GENERIC_RATES`) | Housing and credit data (SSB) | LT (NII reprices with a lag: DNB's customer repricing took effect 12 July after the 6 May 2026 hike, about 9.5 weeks); ST on decision days (10:00 CET) |
| Oslo – metals | Norsk Hydro, Elkem | Aluminium (`ALI=F`; LME next-day; SHFE), alumina (SHFE `AO0`), USD/NOK, Nordic power (ENTSO-E NO zones) | EUA | ST (metal futures); LT (sensitivity × price deck) |
| Oslo – fertiliser | Yara | TTF gas (**input cost: inverse exposure**), EUA | Grain prices | ST/LT |
| Oslo – renewables | Scatec, NEL, etc. | Rates (NOK/EUR/US 10y), power prices | Policy | LT |
| Stockholm – industrials | Atlas Copco, Sandvik, Volvo, SKF, ABB, Alfa Laval | Swedish PMI (Silf/Swedbank), Konj barometer, US/euro PMIs, EUR/SEK, USD/SEK | US futures (global beta) | ST (US overnight/global beta); LT (cycle) |
| Stockholm – banks | SEB, Handelsbanken, Swedbank, Nordea | Riksbank policy rate (`SECBREPOEFF`), STIBOR, SWESTR, SEK curve | Property credit risk | LT; ST on Riksbank days (09:30) |
| Stockholm – real estate | Balder, Castellum, Sagax, Fabege, Wallenstam, SBB | SEK 2–5y yields and STIBOR (Riksbank SWEA); EUR yields (ECB) | Credit spreads (no free source; gap) | ST (yield moves); LT (NAV discount vs yields) |
| Stockholm – mining/steel | Boliden, SSAB | Zinc, copper, gold, silver (Yahoo/SHFE/LME), USD/SEK; HRC `HRC=F`, iron ore `TIO=F` | EUA (SSAB) | ST/LT (Boliden table above) |
| Stockholm – forestry, pulp, paper | SCA, Holmen, Stora Enso (also Helsinki), Billerud | SHFE pulp `SP0` (free) / FOEX (paid); SE1–SE2 power (ENTSO-E); EUR/SEK | Swedish Forest Agency timber stats | LT |
| Stockholm – gaming | Evolution, Betsson | EUR/SEK (revenue in EUR) | Regulation news (out of scope) | LT/ST via FX |
| Stockholm – medtech | Getinge, Elekta | USD/SEK, EUR/SEK | US yields (duration/growth factor) | LT |
| DK/FI (secondary) | Maersk; Novo Nordisk; Vestas/Ørsted; UPM/Stora Enso; Neste; Outokumpu; Nordea/Sampo | Drewry WCI/SCFI (Maersk); USD/DKK (Novo); rates and power (Ørsted, Vestas); pulp and Nordic power (UPM); nickel (Outokumpu); euro rates via ECB (Nordea, Sampo) | DK1/DK2 (Energi Data Service), FI (ENTSO-E) | LT mainly |

**How practitioners estimate and use sensitivities, applied to the app**
1. **Rolling factor regressions.**
   - Model: `r_i = a + b_mkt·r_index + b_cmd·r_commodity + b_fx·r_FX + e`.
   - Use weekly returns, or daily returns aligned to the Oslo/Stockholm close.
   - Use 52-week or 250-day windows, re-estimated each run.
   - Store betas in the prediction log so the drift itself can be evaluated.
   - Orthogonalise the commodity factor against the market factor. Misund found market factors dominate salmon stocks, and oil effects depend on whether a shock is supply- or demand-driven.
2. **Earnings nowcasting (LT).**
   - Quarter-to-date average commodity price vs prior quarter (or vs the price embedded in consensus) × company sensitivity = expected EBIT surprise.
   - Worked example: a 10% rise in zinc at Boliden ≈ +SEK 950 m annualised operating profit.
   - Free consensus estimates are a gap.
3. **Cycle-adjusted valuation (LT).**
   - Value commodity producers on mid-cycle prices (e.g. a 5–10-year average or the futures strip) rather than spot. This avoids buying peak earnings in shipping, salmon and metals.
   - Use the published sensitivity to translate the spot-vs-mid-cycle gap into normalised EBIT.
4. **Short-term sleeve.**
   - Commodity moves overnight (Brent and TTF from 22:00 CET to 09:00 CET) mostly show up in the opening price.
   - With manual Nordnet execution, edge is more likely from:
     - Event releases at or before the open: SSB salmon at 08:00 Wednesday; Riksbank 09:30; Norges Bank 10:00.
     - Lagging reaction in smaller peers: smaller salmon farmers and shipping names vs Frontline/BDRY.
     - Avoiding entries against large adverse overnight factor moves.
   - Every rule should be backtested on the app's logged predictions.

### Gaps
- **Equinor:** numeric sensitivity values (sec.gov and cdn.equinor.com blocked).
- **Hydro:** current (2025/2026) sensitivity table not retrieved; only a 2017 figure via search summary.
- **Mowi and other salmon farmers:** sensitivity of EBIT to the salmon price not retrieved.
- **DNB and Swedish banks:** NII sensitivity per 100 bp not retrieved.
- **Swedish real estate:** quantified share-price betas to SEK yields not found in academic form.
- **Free Nordic consensus estimates:** no source found, so earnings-surprise nowcasts lack a free baseline.
- **Practitioner methodology:** no sell-side pieces (DNB Carnegie, Pareto, SEB, etc.) were accessible.

---

## 4. Global risk factors: S&P 500/Nasdaq futures, VIX, US yields, USD (explanatory power and timing)

### Takeaway
Free daily and intraday proxies are easy to get:
- Yahoo `ES=F`, `NQ=F`, `^VIX`, `^TNX`, `DX-Y.NYB`.
- The Cboe VIX history CSV (from 1990).
- FRED for official daily yields.

Research shows US information spills into markets that open later. US equity returns cluster around the **European open (2–3 a.m. ET)** and are linked to order imbalances at the previous US close. No source found here quantifies what share of **daily Nordic** returns US factors explain; the app should measure this itself.

### Cited Findings
- **Free Yahoo tickers used in open-source dashboards:** `ES=F` (S&P 500 futures), `NQ=F` (Nasdaq-100 futures), `^VIX`, `^TNX` (US 10-year), `DX-Y.NYB` (US Dollar Index); also `BZ=F`, `CL=F`, `GC=F`. — [simplifaisoul/osiris `src/app/api/markets/route.ts`](https://github.com/simplifaisoul/osiris), [Blackdesk-ai/blackdesk](https://github.com/Blackdesk-ai/blackdesk), [CONFLUX](https://github.com/MeetJain23/CONFLUX)
- **Cboe VIX daily CSV:** `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`. Open/high/low/close from **January 1990**; before 11 Jun 2004 only closes were recorded (OHLC identical); the mirror was last updated 23 Sep 2026. — [datasets/finance-vix](https://github.com/datasets/finance-vix), [datahub finance-vix](https://datahub.io/core/finance-vix)
- **Timing of US effects on other markets**
  - New York Fed "Overnight Drift" (Boyarchenko, Larsen, Whelan; Review of Financial Studies 2023): US equity returns are large and positive **during the opening hours of European markets**. The largest returns over 1998–2019 accrued between 2 and 3 a.m. ET, about 3.6% annualised, and were linked to order imbalances at the previous US close. — [NY Fed Staff Report 917](https://www.newyorkfed.org/research/staff_reports/sr917), [Liberty Street Economics](https://libertystreeteconomics.newyorkfed.org/2021/05/the-overnight-drift-in-us-equity-returns), [RFS abstract](https://academic.oup.com/rfs/article-abstract/36/9/3502/7076616)
  - A global return-spillover network study finds US returns affect markets that open next (Asia), with effects lasting into European markets the next day. — [arXiv 1507.06242](https://arxiv.org/pdf/1507.06242)
  - Overnight vs intraday split of European index returns. — [STOXX overnight effect analysis](https://stoxx.com/when-do-returns-come-from-an-analysis-of-the-overnight-effect-in-equities-trading/)
- **Licensing of US data on FRED:** official US yields and dollar indices are free on FRED, but third-party series (e.g. some indices) carry their own copyright. — [FRED terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html)
- **Alternative free CSV source:** since about April 2026 Stooq requires an apikey (via CAPTCHA) and enforces a daily hit limit. — [apis.io Stooq](https://apis.io/providers/stooq)

### Inferences
- **Timing logic for the app.**
  - The US cash close (16:00 ET, about 22:00 CET) comes after Oslo and Stockholm close.
  - So the prior US session's close-to-close move, plus the overnight change in `ES=F`/`NQ=F` up to about 08:55 CET, is the natural predictor of the Nordic **opening gap** [ST].
  - Close-to-close Nordic returns on day t should be regressed on US returns from day t−1 (non-overlapping) and day t (overlapping afternoon hours) separately.
- **Expected magnitudes, to be measured by the app.**
  - Global-beta sectors (Stockholm industrials, Oslo E&P via Brent) should load heavily on US and commodity overnight moves.
  - Domestic sectors (Norwegian savings banks, Swedish real estate) should load more on local rates.
  - Because the open already reflects much of this, a manual-execution app should use these factors mainly to:
    - (a) scale position sizes by VIX regime;
    - (b) avoid buying into large adverse overnight moves;
    - (c) fit the LT sleeve's risk model (beta to global equities, USD, US 10-year).
- **Collection schedule.** Snapshot `ES=F`, `NQ=F`, `^VIX`, `^TNX`, `DX-Y.NYB`, `BZ=F` and `TTF=F` at a fixed pre-open time (e.g. 08:50 CET) and at the Nordic closes. Log them with the predictions so the explanatory power can be evaluated over time.

### Gaps
- **Quantified share of US-factor explanatory power** (R², betas) for OSEBX/OMXS30 daily returns: no Nordic-specific estimate found within the search budget.
- **FRED series IDs:** VIX `VIXCLS`, 10-year `DGS10` and broad dollar `DTWEXBGS` are standard but **unverified** in this session.
- **Exchange trading hours and holiday calendars:** not verified here; presumably covered by another researcher.
- **CME Globex overnight futures hours:** not verified.

---

## 5. Calendars: central-bank meetings, OPEC+, salmon-price releases and macro release calendars (machine-readable sources)

### Takeaway
**Official sources for 2026 decision dates**
- **Norges Bank:** 21 Jan, 25 Mar, 6 May (hike), 17 Jun, 12 Aug, 24 Sep. Two GitHub calendars, citing Norges Bank, list **5 Nov and 17 Dec**, at 10:00 CET.
- **Riksbank:** decisions published at 09:30 the day after each meeting (meetings 28 Jan, 19 Mar, 6 May, 16 Jun, 19 Aug, 23 Sep).
- **ECB:** meetings 4–5 Feb, 18–19 Mar, 29–30 Apr, 10–11 Jun, 22–23 Jul, 9–10 Sep, **28–29 Oct**, 16–17 Dec, with decisions at 14:15 CET.

**Other recurring events**
- **SSB salmon:** every Wednesday at 08:00.
- **OPEC+:** the 7-country group (UAE no longer included) meets about monthly, next reportedly on 4 Oct 2026.

**Machine-readable feeds**
- **FRED:** the `releases/dates` API covers US releases, including future dates.
- **Central banks:** no official ICS or API was found for the Nordic central banks. Third-party ICS feeds exist (Central Bank Watch, smartcalendars). Hand-maintained GitHub calendars can be **wrong** (one conflicts with official Riksbank dates), so scrape official pages.

### Cited Findings
- **Norges Bank 2026 decisions**
  - 21 Jan: hold at 4.00%. 25 Mar: hold. **6 May: hike to 4.25%**. 17 Jun: hold. 12 Aug: hold at 4.25%. 24 Sep: decision with Monetary Policy Report.
  - — [NB Jan 2026](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/january-2026/), [NB Mar 2026](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/march-2026/), [NB May 2026](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/may-2026/), [NB Jun 2026](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/june-2026/), [NB Aug 2026](https://www.norges-bank.no/en/topics/monetary-policy/Monetary-policy-meetings/2026/august-2026/), [NB calendar](https://www.norges-bank.no/en/news-events/calendar/)
  - The September 2026 outcome was not retrieved.
- **Norges Bank, rest of 2026 and 2027**
  - 2026: **5 Nov** and **17 Dec (+MPR)**, both at 10:00 CET/CEST.
  - 2027: 21 Jan, 18 Mar, 5 May, 17 Jun, 19 Aug, 23 Sep, 4 Nov, 16 Dec.
  - The source is a GitHub JSON citing `norges-bank.no/en/news-events/calendar`, corroborated by a second repo for 2026. Treat as secondary.
  - — [ciaranbelcher10/economic-atlas `data-calendar-no.json`](https://github.com/ciaranbelcher10/economic-atlas), [tugceozgur/stock-analysis `polymarket_daily.py`](https://github.com/tugceozgur/stock-analysis)
- **Riksbank 2026**
  - Monetary policy meetings: 28 Jan (one search summary gives 29 Jan), 19 Mar, 6 May, 16 Jun, 19 Aug, 23 Sep.
  - The decision is published at 09:30 the day after the meeting, with a press conference at 11:00. This was verified for the September round: meeting 23 Sep, decision and Monetary Policy Report published **24 Sep 2026 at 09:30**. Assume the same pattern for other rounds but check it.
  - — [Riksbank calendar](https://www.riksbank.se/en-gb/press-and-published/calendar/), [Riksbank 28 Jan 2026 entry](https://www.riksbank.se/en-gb/press-and-published/calendar/calendar-2026/2026-01-28/), [Riksbank September 2026 decision](https://www.riksbank.se/en-gb/monetary-policy/monetary-policy-report/2026/monetary-policy-decision-september-2026/), [Minutes 19 Aug 2026](https://www.riksbank.se/en-gb/press-and-published/notices-and-press-releases/press-releases/2026/minutes-of-the-monetary-policy-meeting-on-19-august-2026/), [Minutes 16 Jun 2026](https://www.riksbank.se/en-gb/press-and-published/notices-and-press-releases/press-releases/2026/minutes-of-the-monetary-policy-meeting-on-16-june-2026/)
  - Outcomes and the Nov/Dec 2026 dates were not retrieved.
- **ECB 2026**
  - Meetings: 4–5 Feb, 18–19 Mar, 29–30 Apr, 10–11 Jun, 22–23 Jul, 9–10 Sep, 28–29 Oct, 16–17 Dec. The next decision is **29 Oct 2026 at 14:15 CET**.
  - Official page: `https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html`. ICS downloads are offered by third parties.
  - — [ECB meetings calendar](https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html), [Young Platform list](https://youngplatform.com/en/blog/news/next-meeting-ecb-calendar-complete-date/), [FinanceCalendar](https://www.financecalendar.com/ecb-rate-decisions/), [Central Bank Watch (.ics)](https://centralbank.watch/tools/calendar/), [smartcalendars.ai ECB feed](https://www.smartcalendars.ai/en/feeds/ecb-governing-council-calendar)
- **Fed FOMC:** the official page is `https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm`, which open-source projects fetch to verify dates. 2026 dates were **not verified** in this session (see the conflict below). — [DexWilder/algo-lab calendar verification note](https://github.com/DexWilder/algo-lab), [financial-agent report citing the Fed calendar](https://github.com/BichengWang/financial-agent)
- **Conflicting community calendar (do not use).** A public GitHub `macro_calendar.py` lists Riksbank 2026 dates (5 Feb, 26 Mar, 7 May, 18 Jun, 3 Sep, 5 Nov) and ECB dates (29 Jan, 5 Mar, 16 Apr, 4 Jun, …) that **contradict** the official Riksbank and ECB schedules above. — [hankkontakt/stock-scanner `core/macro_calendar.py`](https://github.com/hankkontakt/stock-scanner)
- **OPEC+**
  - 3 May 2026: "first meeting without UAE" (188,000 b/d increase). — [CNBC](https://www.cnbc.com/2026/05/03/opec-announces-188000-barrels-per-day-output-increase-.html)
  - 6 Sep 2026 statement: Saudi Arabia, Russia, Iraq, Kuwait, Kazakhstan, Algeria and Oman. — [OPEC press release](https://www.opec.org/pr-detail/1835613-6-september-2026.html)
  - Reported plan to keep October targets at the September level, with a meeting on 4 Oct 2026. Secondary source, not confirmed. — [Energynews.pro](https://energynews.pro/en/opec-weighs-maintaining-production-targets-for-october-2026)
  - July 2026 monthly expansion. — [Al Jazeera, 6 Jul 2026](https://www.aljazeera.com/economy/2026/7/6/opec-countries-say-they-will-expand-monthly-oil-production)
- **Salmon-price releases**
  - SSB weekly statistics are published every **Wednesday at 08:00**. — [SSB salmon](https://www.ssb.no/en/utenriksokonomi/statistikker/laks)
  - SISALMONI is weekly. — [Sitagri](https://www.sitagri.com/sitagri-salmon-index/)
- **Macro release calendars**
  - SCB's publishing calendar covers all official Swedish statistics; releases at 08:00 on weekdays. — [SCB publishing calendar](https://www.scb.se/en/finding-statistics/publishing-calendar/)
  - Konjunkturbarometern data are updated at month-end. — [Konj](https://www.konj.se/statistik-och-data/sa-fungerar-databaserna/)
  - FRED `https://api.stlouisfed.org/fred/releases/dates?api_key=...&file_type=json&include_release_dates_with_no_data=true`. The default `false` excludes dates with no data, "particularly excluding future release dates". — [FRED releases/dates docs](https://fred.stlouisfed.org/docs/api/fred/releases_dates.html), [fredr reference](https://sboysel.github.io/fredr/reference/fredr_releases_dates.html)

### Inferences
- **Build the event calendar as a small curated table, refreshed by scraping official pages.**
  - Norges Bank: `/en/news-events/calendar/`.
  - Riksbank: `/en-gb/press-and-published/calendar/`.
  - ECB: `mgcgc` page.
  - Fed: `fomccalendars.htm`.
  - Keep a fallback to the third-party ICS feeds.
  - Do not trust hand-maintained GitHub lists; one is demonstrably wrong.
- **Pre-open events matter most for the ST sleeve:**
  - SSB salmon, Wednesday 08:00 (before the 09:00 open).
  - Riksbank 09:30 and Norges Bank 10:00: early in the session, so intraday repricing of banks, real estate and NOK/SEK.
  - ECB 14:15 CET: mid-session.
  - FOMC: after the Nordic close, so it affects the next open.
- **OPEC+ dates should be logged as event flags for E&P names.** The group's 2026 changes (UAE exit, monthly meetings of seven countries) make Brent regime shifts around these meetings more likely.

### Gaps
- **Official Nordic central-bank calendars:** no ICS/RSS/API found (official sites blocked here).
- **Riksbank Nov/Dec 2026 dates and outcomes:** not retrieved.
- **2026 FOMC dates:** not verified.
- **Release calendars:** the SSB release-calendar API, Statistics Denmark/Finland release calendars, Swedbank PMI release times and the Euronext salmon futures expiry calendar were not verified.
- **OPEC+ 4 Oct 2026 meeting:** date unconfirmed (opec.org blocked; secondary source only).
