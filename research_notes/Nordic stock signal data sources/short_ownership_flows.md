# Short interest, ownership, flagging, fund holdings, buybacks and investor flows: Norway and Sweden (Denmark and Finland secondary)

> **Verification status, 2026-10-02:** No endpoint below is "verified live 2026-10-02". WebFetch was blocked for every primary domain tried: www.fi.se, finansinspektionen.se, ssr.finanstilsynet.no, www.skatteetaten.no, www.nbim.no, www.euronext.com, live.euronext.com, www.ssb.no, www.scb.se, www.fondbolagen.se, vff.no, www.esma.europa.eu, api.semanticscholar.org and some academic sites. The coordinator later said curl could reach www.fi.se, www.finanstilsynet.no, newsweb.oslobors.no and mfn.se. The session's auto-mode permission classifier then denied the curl request, and an agent message cannot override that, so I did not retry. Each endpoint is therefore labelled "unverified (live)". Where open-source code or captured payloads show the endpoint working, I note "third-party observed" with that party's observation date. Before the app's collectors run, the user needs to allow these hosts (and the six already named): **ssr.finanstilsynet.no** (SSR API), **api3.oslo.oslobors.no** (the NewsWeb JSON API host, which is separate from newsweb.oslobors.no), **marknadssok.fi.se** (FI Insyn/Börsinformation search), **finansinspektionen.se** (FI's possible new domain), **www.nbim.no**, **feed.mfn.se** (official MFN feed), **apiservice.borsdata.se**, **ftp3.interactivebrokers.com** (FTP), **www.finanssivalvonta.fi**, **www.finanstilsynet.dk / oam(s).finanstilsynet.dk**, **www.skatteetaten.no**, **data.ssb.no / www.ssb.no**, **api.scb.se / www.scb.se**, **vff.no**, **www.fondbolagen.se**, **live.euronext.com**.
>
> Sleeve tags used below: **[ST]** = short-term trading sleeve (intraday to a few days); **[LT]** = long-term value sleeve (months to years).

## 1. Short positions: Norway SSR, Sweden Blankningsregistret, Denmark and Finland, securities lending

### Takeaway
Both mandatory markets have free, unauthenticated, machine-readable short registers. Norway has a JSON/CSV REST API (`ssr.finanstilsynet.no/api/v2/instruments`) that returns only the last two years of history. Sweden has three `.ods` downloads at `www.fi.se/BlankningsRegister/…`, one of which is a unique per-issuer aggregate of all reported positions ≥0.1%. To get a long history, the app should snapshot both registers once a day after about 15:30 CET. Borrow-cost data for Nordic names is effectively institutional-only, apart from Interactive Brokers' free shortstock FTP files, which reflect one broker's inventory.

### Cited Findings

**Regulatory frame (EU SSR 236/2012, applied in Norway via the EEA)**
- Norway's register implements Regulation (EU) No 236/2012 for shares, sovereign bonds and CDS where Finanstilsynet is the Relevant Competent Authority. Net short positions ≥0.1% of issued share capital must be notified, plus each further 0.1% change. Positions held at 23:59 must be reported by 15:30 CET the next trading day. Positions ≥0.5% are public; smaller ones are visible only to Finanstilsynet and ESMA. — [Finanstilsynet: Short selling and reporting of short positions](https://www.finanstilsynet.no/en/supervision/market-conduct/short-selling-and-reporting-of-short-positions/); [SSR About page](https://ssr.finanstilsynet.no/Home/About)
- Threshold history: in 2021 Finanstilsynet announced the notification threshold had been "reset at 0.2%" after the temporary COVID-era measures. The current Finanstilsynet page states the threshold as 0.1%. — [Finanstilsynet 2021 news](https://www.finanstilsynet.no/en/news-archive/news/2021/short-sale-reporting-threshold-for-net-short-positions-reset-at-0.2/); [Finanstilsynet short-selling page](https://www.finanstilsynet.no/en/supervision/market-conduct/short-selling-and-reporting-of-short-positions/)

**NORWAY: Finanstilsynet Short Sale Register (SSR), [ST][LT]**
- *Owner/URL:* Finanstilsynet; web UI at `https://ssr.finanstilsynet.no/` with per-instrument pages at `https://ssr.finanstilsynet.no/Home/Details/<ISIN>` (e.g. NO0013033795). — [SSR details page](https://ssr.finanstilsynet.no/Home/Details/NO0013033795)
- *API base and docs:* `https://ssr.finanstilsynet.no/api/v2/` serves ReDoc. `https://ssr.finanstilsynet.no/swagger` redirects (302) to `/swagger/index.html?url=/api/v2/openapi.json`, and the spec itself is at `/api/v2/openapi.json`. — [trymhaak/open-apis manifest 2026-06-25](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/manifest.json)
- *Endpoints, from the OpenAPI spec captured 2026-07-08:*
  - `GET /api/v2/instruments` ("Get public shorting history"; no params; returns an array of `InstrumentShortingHistory`)
  - `GET /api/v2/instruments/export-json` (the same data as a download)
  - `GET /api/v2/instruments/export-csv?separator=;&locale=nb-NO` (defaults `;` and `nb-NO`; binary CSV)
  - Source: [trymhaak/open-apis ssr-openapi.json](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-07-08/ssr-openapi.json)
- *Not available:* `GET /api/v2/instruments/{isin}` and `GET /api/v2/aggregated` both returned 404, so there is no per-ISIN or aggregate endpoint. — [trymhaak manifest 2026-06-25](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/manifest.json)
- *Schema:* `InstrumentShortingHistory {isin, issuerName, events[]}`. Each event is an `AggregatedShortEvent {date, shortPercent ("Aggregated (total) short percentage"), shares (aggregated shorted shares, int64), activePositions[]}`. Each active position is an `UnderlyingShortPosition {date, shortPercent, shares, positionHolder}`. — [ssr-openapi.json](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-07-08/ssr-openapi.json)
- *Authentication:* none. Third-party probes found that all GET endpoints returned HTTP 200 application/json without auth, and the spec declares no securitySchemes. Accounts and 2FA apply only to position submitters. — [trymhaak manifest](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/manifest.json)
- *Size and coverage (third-party observed):* `/instruments` is about 1.4 MB and `export-csv` about 171 KB. The sample held 98 instruments, with the most recent event dated 2026-06-23. — [trymhaak manifest 2026-06-25](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/manifest.json). A 2026-05-08 fetch of `/instruments` returned 1,416,075 bytes with HTTP 200. — [trymhaak manifest 2026-05-08](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-05-08/manifest.json)
- *History depth:* Finanstilsynet's open-data page states (Nynorsk): "Vi leverer berre informasjon om [shortposisjonar] som var aktive dei siste to åra", i.e. only positions active within the past two years. — [Finanstilsynet open-data landing page, captured 2026-06-25](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/finanstilsynet-open-data-landing.html); [catalog YAML](https://github.com/trymhaak/open-apis/blob/main/catalog/by-provider/finanstilsynet/shortsalregister.yaml)
- *Update frequency and latency:* "every business day at 15:30 CET". — [catalog YAML](https://github.com/trymhaak/open-apis/blob/main/catalog/by-provider/finanstilsynet/shortsalregister.yaml). One open-source collector polls at 16:00 Oslo time Mon–Fri and writes daily JSONL snapshots. — [sondreskarsten registry.yaml](https://github.com/sondreskarsten/doffin-parser/blob/3c267cf00b75ea08cb5699fd87ef3eb937fc6d04/tests/registry.yaml)
- *Other scrapers using the same endpoint:* [samuelsmb/SSR backend/ssr.py](https://github.com/samuelsmb/SSR/blob/351b38c7c61c59746174d309d9b9577af2d89514/backend/ssr.py) (`https://ssr.finanstilsynet.no/api/v2/instruments/`) and [aksje-app short_data_sources.py](https://github.com/aksje-app/aksje-app/blob/8200aa925c374198a7a4fd32be4013fc5926e966/short_data_sources.py), which caches for 12 h.
- *Licence (sources conflict):* the catalog YAML lists the licence as "proprietary" with terms at `https://ssr.finanstilsynet.no/Home/Terms`, and found no explicit open licence. — [catalog YAML](https://github.com/trymhaak/open-apis/blob/main/catalog/by-provider/finanstilsynet/shortsalregister.yaml). The manifest instead records **NLOD 2.0** from the data.norge.no (FDK) record and notes that this is "NOT stated verbatim on any ssr.finanstilsynet.no HTML page". — [trymhaak manifest](https://github.com/trymhaak/open-apis/blob/main/raw/finanstilsynet/2026-06-25/manifest.json)
- *Cost:* free. *Status in this environment:* ssr.finanstilsynet.no is blocked, so the endpoint is unverified (live).

**SWEDEN: Finansinspektionen (FI) Blankningsregistret, [ST][LT]**
- *What is published:* FI continuously publishes the total of all short positions reportable to it under EU SSR 236/2012. All positions above 0.1% of issued share capital are included in the sum; positions below 0.1% are not, because they need not be reported. The figures update continuously as reports arrive. Users can search per issuer for the latest position date, the aggregate short percentage, and the named holders of public (≥0.5%) positions. Coverage is shares on regulated markets and MTFs where FI is competent authority. The aggregate series started in 2022. — [FI news 2022: Start för fortlöpande publicering av aggregerade blankningspositioner](https://www.fi.se/sv/publicerat/nyheter/2022/start-for-fortlopande-publicering-av-aggregerade-blankningspositioner/); [Realtid](https://www.realtid.se/marknader/fi-publicerar-aggregerade-blankningspositioner/)
- *Register relaunch:* FI launched a new short register in 2020. — [FI news 2020: Nytt blankningsregister lanseras i dag](https://www.fi.se/sv/publicerat/nyheter/2020/nytt-blankningsregister-lanseras-idag/)
- *Download endpoints (third-party observed; two independent codebases agree):*
  - `https://www.fi.se/BlankningsRegister/GetAktuellFile`: current positions ≥0.5% with holders named (~598 KB)
  - `https://www.fi.se/BlankningsRegister/GetHistFile`: past and closed positions ≥0.5% (~1.7 MB)
  - `https://www.fi.se/BlankningsRegister/GetBlankningsregisterAggregat`: "Summa blankning %" per issuer, covering all positions ≥0.1%, with no holder names (~609 KB)
  - Sources: [boeriksson/candlechart NEWS_SOURCES.md](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md); [H4jen/yspy short_selling_tracker.py](https://github.com/H4jen/yspy/blob/bfd3cfe60bfe119e5cfdc4c40b3f9842a6c88ab8/short_selling/short_selling_tracker.py)
- *Format and fields:* OpenDocument `.ods` (zipped XML), with data starting at row 6 (`skiprows=6`). Current and historic files have 6 columns: position holder, issuer, ISIN, position %, position date, comment. The aggregate file has 4: issuer name, **LEI**, "Summa blankning %", date of latest position. — [candlechart](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md); [yspy](https://github.com/H4jen/yspy/blob/bfd3cfe60bfe119e5cfdc4c40b3f9842a6c88ab8/short_selling/short_selling_tracker.py). Swedish header names seen in one parser: "Namn på emittent", "Innehavare av positionen", "Position i procent", "Datum för positionen". — [Budradar api/companies.js](https://github.com/janssonsigge-jpg/Budradar/blob/main/api/companies.js)
  - *Format conflict:* two 2026 audits describe the files as "Excel"/"xlsx". — [nolltillmiljoner free-data audit 2026-09-22](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md); [marketscan alpha audit 2026-08-28](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md). The code-based sources consistently parse `.ods`.
- *HTML views:* the per-issuer page is `https://www.fi.se/sv/vara-register/blankningsregistret/emittent/?id=<LEI>` and the per-holder page is `…/blankningsregistret/Positionsinnehavare/?id=<GUID>`. The same paths also appear in search results under **finansinspektionen.se**, which may point to a domain move (unverified). — [FI emittent page](https://www.fi.se/sv/vara-register/blankningsregistret/emittent/?id=549300HX9MRFY47AH564); [finansinspektionen.se emittent page](https://finansinspektionen.se/sv/vara-register/blankningsregistret/emittent/?id=549300LZSA4S0L54VQ25); [Positionsinnehavare page](https://finansinspektionen.se/sv/vara-register/blankningsregistret/Positionsinnehavare/?id=1a97d5d4-2dc6-4650-a8bd-6a5ca2fa3598)
- *A different download URL:* `https://www.fi.se/sv/vara-register/blankningsregistret/GetAktuellaPositioner/`. One scraper falls back to a local `.ods` copy "due to temporary blob URLs", so the page's download button may not be a stable link. — [Budradar companies.js](https://github.com/janssonsigge-jpg/Budradar/blob/main/api/companies.js)
- *Size of the register (third-party observed 2026-09-21):* about 1,785 issuers in the aggregate file and about 238 named positions ≥0.5%. — [candlechart](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md). A third-party site reports a different figure, "279 companies have 501 active disclosed short positions". The date and definition of that count are unclear. — [shortregister.com/SE](https://shortregister.com/SE/); [midgardfinance Sweden shorts](https://www.midgardfinance.com/shorts/sweden.html)
- *Interpretation caveats:* "En saknad rad är inte 0 %", i.e. an issuer missing from the register does not mean 0% short. — [Dividend-Lab data-parity.ts](https://github.com/Nils-henrik/Dividend-Lab/blob/26074ff02b9b10a39d8634450b054db67b821420/lib/companies/data-parity.ts). The register should not be labelled total market short interest, because positions below the threshold are absent. — [nolltillmiljoner audit](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md)
- *History:* `GetHistFile` covers past and closed ≥0.5% positions. — [candlechart](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md). A third-party aggregator claims Swedish data runs from 2010-05-14. — [shortregister.com/SE](https://shortregister.com/SE/)
- *Licence and attribution:* a third-party summary says FI data requires stating the source "FI" and the retrieval date, with no published rate limits, and recommends daily polling with backoff. — [candlechart](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md). FI has an open-data page. — [FI Öppen data](https://www.fi.se/sv/om-fi/om-webbplatsen/oppen-data/)
- *Cost:* free.

**DENMARK (secondary)**
- In 2017 the Danish FSA's OAM (`oasm.finanstilsynet.dk/dk/vismeddelelse.aspx?aid=…`) carried short-position announcements such as "Maverick Capital, Ltd. holds a short position at 0.86 % in shares issued by Pandora A/S". It also carried issuers' weekly buyback-transaction announcements (e.g. Vestas, 20–24 Nov 2017). — [PythonSpiderMan/Spider_finanstilsynet.dk README](https://github.com/PythonSpiderMan/Spider_finanstilsynet.dk/blob/272db37a67405814d418ce22ac7f252c42afb1ff/README.md)
- A 2026 audit records that in the DFSA OAM, major shareholders' and managers' reports to the DFSA are "IKKE offentligt tilgængelige" (not publicly available). — [marketscan nordic-data-landscape.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/nordic-data-landscape.md)

**FINLAND (secondary)**
- FIN-FSA publishes net short positions at `https://www.finanssivalvonta.fi/en/capital-markets/short-selling/net-short-positions/`. The open-source tracker that references this page had not implemented parsing, so the file format is unknown. — [H4jen/yspy](https://github.com/H4jen/yspy/blob/bfd3cfe60bfe119e5cfdc4c40b3f9842a6c88ab8/short_selling/short_selling_tracker.py)
- ESMA keeps a list of national websites where net short positions are published. — [ESMA ssr_websites_ss_positions.pdf](https://www.esma.europa.eu/sites/default/files/library/ssr_websites_ss_positions.pdf)

**Securities lending, utilisation and borrow cost**
- *S&P Global Securities Finance:* an institutional securities-lending data product. — [S&P Global Securities Finance](https://www.spglobal.com/market-intelligence/en/solutions/products/securities-finance). Its monthly snapshots report market-level figures, e.g. January 2026 lending revenue of $1.23bn, balances +27% YoY, and an average fee of 0.41%. — [S&P Securities Finance January Snapshot 2026](https://www.spglobal.com/market-intelligence/en/news-insights/research/2026/02/securities-finance-january-snapshot-2026). I found no public price or retail tier.
- *Interactive Brokers "shortstock" FTP [ST]:* free anonymous FTP at `ftp://shortstock:@ftp3.interactivebrokers.com/usa.txt` (user `shortstock`, blank password, about 15-minute updates). It is pipe-delimited with the header `#SYM|CUR|NAME|CON|ISIN|REBATERATE|FEERATE|AVAILABLE`. — [joemccann/radon short-locate-borrow.md](https://github.com/joemccann/radon/blob/cb47c52ab055221fd7d88ead72ff28acb554e7d7/docs/short-locate-borrow.md). An older country list includes `swedish` but no Norway, Denmark or Finland files: australia, austria, belgium, british, canada, dutch, france, germany, hongkong, india, italy, japan, mexico, spain, swedish, swiss, usa. — [ymawji/ib-stock-borrow](https://github.com/ymawji/ib-stock-borrow/blob/master/download_ib_stock_borrow.py). There is no free history archive. — [Phantomape/ginger notes 2026-07-03](https://github.com/Phantomape/ginger/blob/85f0f1563aa90da405b06b8aa097296885d40e4c/docs/alpha_direction_history_debate_20260703.md). The data is "Interactive Brokers' OWN lendable inventory and borrow fee — one broker's view, not the market's". — [ghost-protocol-v2 public.py](https://github.com/seancole713-source/ghost-protocol-v2/blob/7a1edea642e74db274082c4e69749930de7e5d67/edge/providers/public.py)
- *Börsdata API `/v1/holdings/shorts` [ST][LT]:* "Returns Holdings shorts", Nordic instruments only, authenticated with `authKey`. — [emmanuelay/borsdata-mcp swagger.json](https://github.com/emmanuelay/borsdata-mcp/blob/main/client/assets/swagger.json). Cost and terms are covered in section 2.

### Inferences
- Norway's API returns only two years of history, so the app should store a full snapshot of `/api/v2/instruments` every business day after 15:30 CET (16:00 Oslo is a safe poll time). This builds its own point-in-time history; the same snapshotting is needed for FI's aggregate file, which carries only the latest value per issuer.
- The fields support both sleeves:
  - [ST] new positions, increases, crossings of 0.5%/1%/2%, and the number of distinct holders in each daily diff
  - [LT] level of aggregate short % (Sweden ≥0.1%; Norway is probably the sum of public ≥0.5% positions), used as a risk filter or score penalty
- Sweden's aggregate (≥0.1%) captures more informed short selling than Norway's public-only data. This matters because of the bunching just below 0.5% documented in section 7. Weights for Norwegian and Swedish names should therefore be calibrated separately.
- GDPR: position holders are mostly legal entities, but natural persons can appear. For a personal app, the safest design is to store holder names only as hashed IDs or counts, or to discard them after computing aggregates.
- Securities-lending utilisation and fee data is not realistically affordable for a personal app. The free IBKR file, where a Swedish file exists, can serve as a crude squeeze or crowding flag [ST], but it should not be treated as market-wide utilisation.

### Gaps
- Live verification was not possible (permission denied; hosts blocked). The current Swedish file format (`.ods` vs `.xlsx`) and the exact current URLs on www.fi.se vs finansinspektionen.se need checking with one request each.
- It is unconfirmed whether the SSR `events[].shortPercent` aggregate includes only public positions (≥0.5%) or all notified ones. The schema description says only "Aggregated (total) short percentage".
- I could not confirm the start date of Norway's EU-SSR register, or where longer-than-two-year Norwegian history can be obtained officially (FOI request? third-party archives?).
- Denmark's and Finland's current download formats and endpoints are unverified. The DFSA OAM URL above dates from 2017.
- S&P Global Securities Finance pricing and Nordic coverage depth: no public information found.
- Possible EU-level 2025–26 changes to SSR publication (e.g. centralisation at ESMA): not researched successfully (search budget exhausted).

## 2. Ownership registers and shareholder lists (Norway and Sweden)

### Takeaway
Full beneficial-ownership data is not freely available in either country at useful frequency. Norway's Skatteetaten publishes an annual, free, per-shareholder CSV as of 31 December, released in May, with no API. Euronext Securities Oslo (VPS) sells top-shareholder and investor-type data. Sweden's share books are kept by Euroclear Sweden, but nominee registration hides underlying owners. Practical structured Swedish ownership data comes from paid Modular Finance Holdings, which can be reached cheaply through Börsdata Pro+, subject to strict licence terms.

### Cited Findings

**NORWAY: Skatteetaten Aksjonærregisteret [LT]**
- *Content:* anyone can access shareholder information as of 31 December of each income year. The extract contains company name and organisation number, shareholder names, birth year, postcode and place, share class, shares held at year-end, and total shares in the company. It is downloadable as `.csv` and made available in May after the income year. The search snippet also says the register covers all Norwegian limited companies and foreign companies registered on Oslo Børs. — [Skatteetaten: Aksjonærregisteret](https://www.skatteetaten.no/en/deling/aksjonarregisteret/); [Skatteetaten: Bruke data fra Skatteetaten](https://www.skatteetaten.no/en/deling/)
- *Access mechanics:* the bulk CSV is "ordered free via skatteetaten.no/deling/aksjonarregisteret/". After a form is submitted, a ShareFile email link arrives within 5 business days and expires after one week. There is **no API**. The data opens mid-May each year; the 2025 data opened on 18 May 2026, and the next release is expected around May 2027. — [nilseng/aksjegrafen ROADMAP.md](https://github.com/nilseng/aksjegrafen/blob/3fb396dded5804e95a42dc0bd86daf3d14f5d048/docs/ROADMAP.md)
- *Public status:* Skatteetaten has stated that shareholder information in the register is public. — [Cision PDF "Aksjeeieropplysninger i Skatteetatens aksjonærregister er offentlige"](https://mb.cision.com/Main/12480/9812782/407219.pdf)
- *Third-party search front-ends:* [aksjeeiere.no](https://www.aksjeeiere.no/) and [Byndle opplysning](https://opplysning.byndle.no/aksjonaerregisteret).

**NORWAY: Euronext Securities Oslo (VPS) data products and statistics [LT]**
- Euronext Securities Oslo sells a "Top Shareholder Information" data service. — [Euronext: Top Shareholder Information](https://www.euronext.com/en/csd/oslo/data-services/top-shareholder-information)
- Its "Investor Figures" product offers "structured, aggregated market and investor data at security (ISIN) level" on investor behaviour and ownership dynamics; contact is data.vps@euronext.com. — [Euronext CSD Oslo data services](https://www.euronext.com/en/csd/oslo/data-servicesold)
- A separate "Shares and Voting Rights file" product exists for Euronext Oslo Børs. — [Euronext Oslo Børs Shares and Voting Rights file](https://www.euronext.com/en/products-services/euronext-oslo-bors-shares-and-voting-rights-file)
- Statistics Norway's securities statistics give "a current overview of the issue and ownership of securities registered in Euronext Securities Oslo", built from monthly extracts received from Euronext Securities Oslo. — [SSB: Securities](https://www.ssb.no/en/bank-og-finansmarked/verdipapirmarkeder/statistikk/verdipapirer)

**SWEDEN: share books, nominee opacity, commercial ownership data**
- For CSD-registered (avstämnings-) companies, the share book (aktiebok) can be kept through Euroclear Sweden. Shares held in custody accounts can be nominee-registered (förvaltarregistrerade): the nominee appears in the share book and the underlying owner is visible only in the nominee's own register. — [Dividend-Lab learning article](https://github.com/Nils-henrik/Dividend-Lab/blob/26074ff02b9b10a39d8634450b054db67b821420/data/learning/articles/vad-ar-en-aktie.ts)
- *Holdings by Modular Finance [LT][ST]:* an ownership-analysis tool for Swedish listed companies that also includes insider trading, short data, liquidity data and broker statistics. Ownership data for unlisted companies is an add-on. Lund University gives students access; contact is support@holdings.se. — [Lund University LibGuides](https://libguides.lub.lu.se/c.php?g=694482&p=4983293); [Holdings product page](https://modularfinance.com/holdings); [MFN: Holdings unlisted launch](https://mfn.se/all/a/modfin/modular-finance-launches-ownership-data-for-unlisted-companies-in-holdings); [MFN: Holdings UK launch](https://mfn.se/a/modfin/modular-finance-lanserar-holdings-uk). I found no public price.
- *Börsdata Pro+ (resells Holdings data):* Börsdata announced "Ny Holdings data (Pro+)". — [Börsdata news](https://borsdata.se/news/holdings-release). A 2026 third-party audit records the following:
  - Pro+ includes "Holdings Insider, Holdings Shorts, Holdings Buyback, Governance" at about **59 EUR/month**.
  - The REST API moved to Pro+ from **1 Feb 2025**; new Pro members cannot get REST keys.
  - Rate limit is 100 calls per 10 s (429 + Retry-After); stay under 10,000 calls per 24 h.
  - Licence: "Endast privatpersoner, egen analys", with commercial use, redistribution and "bygga externa system/hemsidor/widgets som visar API-data" forbidden.
  - Source: [marketscan nordic-data-landscape.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/nordic-data-landscape.md)
- *Börsdata holdings endpoints (from the published swagger):*
  - `GET https://apiservice.borsdata.se/v1/holdings/insider?authKey=…&instList=<ids, max 50>`. Rows contain `ownerName, ownerPosition, shares, price, amount, currency, transactionType, verificationDate, transactionDate, misc, equityProgram`.
  - `GET /v1/holdings/shorts?authKey=…`
  - `GET /v1/holdings/buyback?authKey=…&instList=…`
  - All three are "Nordic instruments only".
  - Source: [emmanuelay/borsdata-mcp swagger.json](https://github.com/emmanuelay/borsdata-mcp/blob/main/client/assets/swagger.json); [carlwestman/borsdata-mcp-server client.ts](https://github.com/carlwestman/borsdata-mcp-server/blob/1d0c9a6a7c42272a7fcf3e84c1f3b81c4157eb59/src/api/client.ts)

**Related: PDMR (insider) transactions as an ownership-change source [ST][LT] (may overlap another researcher's scope)**
- FI Insynsregistret export: `https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search?SearchFunctionType=Insyn&Publiceringsdatum.From=YYYY-MM-DD&Publiceringsdatum.To=YYYY-MM-DD&button=export`. It returns UTF-16LE CSV, `;`-delimited, with decimal comma and 22 columns. Exports stop silently at 1,000 rows, so date ranges must be split. Coverage starts 2016-07-03. A nightly UTF-8 mirror exists at `raw.githubusercontent.com/civictechsweden/oppna-insynsregistret/HEAD/data/insynsregistret.csv`. — [candlechart NEWS_SOURCES.md](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md)
- In Norway, PDMR trades are NewsWeb category 1102 ("Meldepliktig handel for primærinnsidere"). — [viljarem/InveStock-V1 insider_monitor.py](https://github.com/viljarem/InveStock-V1/blob/3d9f139ce2d169a29dd3833a65ba9c35b6803af6/insider_monitor.py)

### Inferences
- The Norwegian Aksjonærregisteret is only useful for the [LT] sleeve, e.g. year-over-year changes in retail vs. institutional vs. foreign holder counts, or ownership concentration. It arrives about 4.5 months after its reference date, contains natural persons' names, birth years and postcodes, and must be ordered manually. Storing it raises GDPR questions. A purely personal app may fall under GDPR's household exemption, but the app should still store only aggregates per company rather than person-level rows.
- For Sweden, Börsdata Pro+ (about 59 EUR/month) is probably the cheapest structured route to ownership, short, insider and buyback data across the Nordics. Its licence bans "external systems/websites/widgets showing API data", which is a grey zone for a private web app. Keeping the app private and single-user, and showing only derived scores, reduces the risk; the user should check the exact terms.
- Top-20 shareholder lists on company IR pages (Norway; usually VPS-based) could be scraped per company, but there is no uniform format. Nominee accounts hide the beneficial owners of large foreign stakes.

### Gaps
- Not verified: whether Aksjonærregisteret covers ASA companies listed on Euronext Oslo with full nominee look-through (very likely not), and its exact CSV column names.
- I could not confirm 2026 prices for Euronext Securities Oslo "Top Shareholder Information" or "Investor Figures", or whether retail buyers can purchase them.
- The Euronext VPS rules for Norwegian holders' use of nominee accounts, and when they changed, are not researched (no source retrieved).
- Euroclear Sweden's public share-book access (viewing or ordering extracts, fees), "Monitor" (Modular Finance), and Swedish "ägarlistor" sites (e.g. Avanza/Nordnet top-owner tabs, holdings.se) were not verified.
- SCB Aktieägarstatistik (semi-annual ownership by sector, including foreign ownership) could not be fetched. SCB's PxWeb API v2 launched in October 2025 per [nolltillmiljoner audit](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md), but table IDs are unknown.
- Börsdata's exact ToS text and current Pro+ price (59 EUR/month comes from a secondary source).

## 3. Major-shareholding notifications (flagging)

### Takeaway
Sweden: FI itself publishes each flagging notice, by 12:00 on the trading day after it receives it. The notice goes into FI's Börsinformation database and is also distributed as a press release through MFN under the author "Finansinspektionen", so a feed can be built (`mfn.se/all/a/fi-se.json`). Norway: notices are published on NewsWeb (the OAM) under category 1006 "Major shareholding notifications", which the NewsWeb JSON API can filter. A 2026 consultation proposes moving receipt and publication from Oslo Børs to Finanstilsynet, so this channel may change. Neither country offers an official structured dataset with parsed holder, threshold, or before/after percentage; parsing the message text is required.

### Cited Findings

**SWEDEN [ST][LT]**
- *Thresholds:* 5, 10, 15, 20, 25, 30, 50, 66⅔ and 90% of votes or shares. Note that Sweden uses 30% rather than ⅓. Flagging applies to companies whose shares are listed on a regulated market (e.g. Nasdaq Stockholm, NGM Main Regulated), when a change crosses a threshold in either direction. — [FI: Flaggning](https://www.fi.se/sv/marknad/investerare/flaggning/)
- *Publication:* FI publishes flaggningsmeddelanden by 12:00 noon on the trading day after a flagging notification reaches FI, and stores them in the Börsinformation database. That database also holds annual and half-year reports and published inside information for issuers with Sweden as home member state. — [FI: Börsinformation](https://www.fi.se/sv/vara-register/borsinformation/). A 2026 audit says the database covers material "since July 2007" in XHTML/iXBRL and flags "RIGHTS REVIEW REQUIRED". — [nolltillmiljoner audit](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md)
- *Distribution as press releases:* FI flagging notices appear as releases titled "Finansinspektionen: Flaggningsmeddelande i <Company>". — [Inderes: Flaggningsmeddelande i Micro Systemation AB](https://www.inderes.se/releases/finansinspektionen-flaggningsmeddelande-i-micro-systemation-ab-publ-56); [Inderes: Flaggningsmeddelande i NOTE AB](https://www.inderes.fi/sv/releases/finansinspektionen-flaggningsmeddelande-i-note-ab-publ-22); [MFN.se > Finansinspektionen](https://mfn.se/all/a/fi-se)
- *Feed endpoint used by scrapers (unverified live):* `https://mfn.se/all/a/fi-se.json?limit=200`, parsed from `content.title`/`html`, `author.name` and `publish_date` to extract company, holding %, threshold crossed and direction (upp/ner). — [Budradar api/companies.js](https://github.com/janssonsigge-jpg/Budradar/blob/main/api/companies.js). The same project polls `https://mfn.se/all/s/nordic.json?limit=300` for bid detection. — [Budradar api/bidco.js](https://github.com/janssonsigge-jpg/Budradar/blob/a44ef764d1cb899f63ac186c31c129641dfbda54/api/bidco.js)
- *Official MFN feed API (blocked here):* Modular Finance's own client libraries read `https://feed.mfn.se/v1/feed/<entity_id>`. Items carry `group_id`, `url`, `author.entity_id`, `properties.type` and `properties.tags` (e.g. `":regulatory"`, `"sub:ci"`, `"sub:report"`) and `content.publish_date`. — [modfin/mfn-clients js test](https://github.com/modfin/mfn-clients/blob/d0a5c70d5a3c8f5c3e80a283a86f6d44188f5449/js-client/mfn-client.test.js). The mfn.se list pages accept `.rss`/`.json` suffixes with `limit`, `offset` and `filter=(and(or(.properties.tags@>["sub:report"])))`-style filters. — [kafk/Aktier2 mfn-news route.ts](https://github.com/kafk/Aktier2/blob/e5adc8b78dd27559ff399fdb8c354ae7b1f46ffb/src/app/api/mfn-news/route.ts); [HEriks report_scraper.py](https://github.com/HEriks/investing-utilities/blob/243a745d497a01e73617952139820814bc5aa760/report_scraper.py)
- *MFN terms:* a 2026 audit describes MFN as "gratis att bläddra" (free to browse) with "no API → scrape/RSS". — [marketscan nordic-data-landscape.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/nordic-data-landscape.md)

**NORWAY [ST][LT]**
- *Legal basis and channel:* the flagging duty follows Verdipapirhandelloven § 4-2, verdipapirforskriften chapter 4, and the regulation of 6 Dec 2007 no. 1359. Notifications go to the issuer and to Finanstilsynet "or the entity Finanstilsynet designates". The regulation designates Oslo Børs as recipient and publisher for Norway-home-state companies listed on Oslo Børs and Euronext Expand. The duty is fulfilled by publication in the OAM, which is NewsWeb. — [Finanstilsynet: Rapportering og offentliggjøring av flaggemeldinger](https://www.finanstilsynet.no/rapportering/fellesrapporteringer/rapportering-og-offentliggjoring-av-flaggemeldinger-flaggeplikt/); [Finanstilsynet: Flaggeplikt](https://www.finanstilsynet.no/tilsyn/markedsatferd/flaggeplikt/); [Veiledning til vphl. kap. 4](https://www.finanstilsynet.no/contentassets/1989e1faf1e94111a1978e446d7740f7/veiledning-til-verdipapirhandelloven-kapittel-4--flaggeplikt.pdf)
- *Change log:*
  - **From 1 April 2025** Finanstilsynet took over from Oslo Børs the supervision of ongoing disclosure, delayed disclosure of inside information, **share buyback programmes and price stabilisation**, and the role of takeover authority. Delayed-disclosure notices now go through Altinn form KRT-1801 instead of NewsPoint. Flagging handling was unchanged, with Oslo Børs remaining recipient. — [BAHR newsletter](https://bahr.no/newsletter/finans-overforing-av-tilsynsoppgaver-fra-oslo-bors-til-finanstilsynet-1-april-2025); [Wiersholm](https://wiersholm.no/nyhetsbrev/overforing-av-myndighet-fra-oslo-bors-til-finanstilsynet-viktige-endringer-fra-1-april-2025/); [Regjeringen](https://www.regjeringen.no/no/aktuelt/finanstilsynet-overtar-myndighetsoppgaver-fra-oslo-bors/id3093034/); [Finanstilsynet news 2025](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2025/finanstilsynet-har-overtatt-tilsynet-med-lopende-informasjonsplikt-utsatt-offentliggjoring-av/); [Euronext: Viktige endringer for utstederne fra og med 1. april 2025](https://www.euronext.com/nb/media/13300/download)
  - **2026 consultation:** Finanstilsynet proposes repealing §§ 1–2 of regulation 2007/1359 so that Finanstilsynet, not Oslo Børs, receives and publishes flagging notices. The comment deadline was **14 Sep 2026** (case 25/9961). Linked context includes the ESAP implementation. As of this research, the outcome and effective date are not known. — [Finanstilsynet hearing 2026](https://www.finanstilsynet.no/nyhetsarkiv/horinger/2026/horing-overforing-av-oppgaven-med-mottak-og-offentliggjoring-av-flaggemeldinger-fra-oslo-bors-til); [Regjeringen ESAP hearing](https://www.regjeringen.no/no/dokumenter/horing-gjennomforing-av-esap-regelverket/id3139165/)
  - Enforcement continues: in 2026 Finanstilsynet issued an infringement fine for a flagging breach. — [Finanstilsynet 2026: Flaggeplikt – vedtak om overtredelsesgebyr](https://www.finanstilsynet.no/nyhetsarkiv/tilsynsrapporter/2026/flaggeplikt-vedtak-om-overtredelsesgebyr)
- *NewsWeb JSON API (third-party documented; host `api3.oslo.oslobors.no`, unverified live):*
  - The base is `https://api3.oslo.oslobors.no/v1/newsreader`; the SPA's runtime config is `https://newsweb.oslobors.no/urls.json`. — [suam4597 disclosure endpoint scan](https://github.com/suam4597-ship-it/disclosure-automation/blob/97ffe185cb486bcad82c3689d80b7dd2584ddb1a/apps/backend/disclosure_api/docs/globalpulse_eu_listed_company_disclosure_endpoint_scan.md)
  - `list?category=&issuer=<numeric id>&fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD&market=XOSL&messageTitle=` works with GET or POST. It returns `data.messages[]` with `messageId, title, category, markets, issuerName, issuerSign, issuerId, publishedTime, numbAttachments, clientAnnouncementId`. — [NicolaiBaklund/SAB newsweb.py](https://github.com/NicolaiBaklund/SAB/blob/main/src/data/newsweb.py); [suam4597 scan](https://github.com/suam4597-ship-it/disclosure-automation/blob/97ffe185cb486bcad82c3689d80b7dd2584ddb1a/apps/backend/disclosure_api/docs/globalpulse_eu_listed_company_disclosure_endpoint_scan.md)
  - `message?messageId=<id>` returns the body and attachments; `attachment?messageId=&attachmentId=` returns the file. — [SAB newsweb.py](https://github.com/NicolaiBaklund/SAB/blob/main/src/data/newsweb.py)
  - There is no paging. The list caps at **600** results and sets `data.overflow=true`, so callers must bisect date ranges. Dates are day-granular. Recommended politeness is 1 request per second. Payloads mix Norwegian and English, use non-breaking spaces in numbers, and can carry correction links in both directions. — [kennyng90/bjelle-ai fixtures LESMEG.md (payloads fetched Aug 2026)](https://github.com/kennyng90/bjelle-ai/blob/main/apps/workers/test/fixtures/newsweb/LESMEG.md)
  - **Category IDs:**
    - 1001 annual report, 1002 half-year report, 1003 quarterly report, 1004 home member state
    - 1005 inside information, **1006 major shareholding notifications**, **1007 acquisition/disposal of own shares**, **1008 total number of voting rights and capital**, 1009 changes in rights, 1010 additional regulated information
    - 1101 ex-date, **1102 managers' transactions**, **1103 prospectus**, 1104 non-regulatory press release, 1105 interest-rate adjustment
    - 1202 trading halt, 1207 exchange announcement, 1208 third-party announcement, 1301 FSA announcement, 1302 central bank announcement
    - Source: [kennyng90/bjelle-ai newsweb.ts](https://github.com/kennyng90/bjelle-ai/blob/main/apps/workers/src/source/newsweb.ts); 1102 independently in [InveStock insider_monitor.py](https://github.com/viljarem/InveStock-V1/blob/3d9f139ce2d169a29dd3833a65ba9c35b6803af6/insider_monitor.py)
  - *Terms:* there is no official open API. The messages are legally mandated public information, but redistribution terms "må sjekkes" (must be checked). — [bjelle-ai CONCEPT.md](https://github.com/kennyng90/bjelle-ai/blob/main/docs/CONCEPT.md)

**DENMARK (secondary):** a 2026 audit records that major shareholders' reports to the DFSA are not publicly available in the OAM; issuers publish them as company announcements. — [marketscan nordic-data-landscape.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/nordic-data-landscape.md)

### Inferences
- Collector design:
  - Norway: poll NewsWeb `list?category=1006` (plus 1007, 1008 and 1102) for today and yesterday every 5–15 minutes during market hours.
  - Sweden: poll the MFN FI feed `fi-se.json` with the same cadence.
  - For both, parse holder, direction, old and new % and threshold from the title and body with regexes, and keep the raw text so parsing can be fixed later.
- Signals: [ST] uses the announcement-day reaction, which may also catch new strategic or activist holders. [LT] uses accumulation by known long-term holders such as Folketrygdfondet, NBIM or Swedish AP funds, and exits by founders.
- The Norwegian consultation could move publication from NewsWeb to a Finanstilsynet register or the ESAP-linked OAM. The collector should be designed to switch sources, and the outcome should be monitored after the 14 Sep 2026 deadline.
- Flagging applies only to regulated markets. First North/Spotlight/Euronext Growth names have no statutory flagging under these rules (inferred from FI's description, which names regulated markets only), which leaves a gap for small caps.

### Gaps
- Norway's exact flagging thresholds were not verified from a primary source in this session. The brief's list (5/10/15/20/25/⅓/50/⅔/90%) is consistent with practice but has no citation here.
- I found no official structured (CSV/JSON with parsed fields) flagging dataset for either country. Whether Holdings or Börsdata expose flagging-derived "major holders" with history is unknown.
- The FI Börsinformation search endpoint (probably on marknadssok.fi.se) and its export options were not identified.
- No Nordic study of flagging-announcement returns was found (see section 7).

## 4. Fund holdings and fund flows

### Takeaway
Sweden has an unusually good free source: FI publishes every Swedish UCITS fund's full holdings each quarter as a ZIP of XML files, from Q4 2018, with about a two-month lag. That supports a fund-ownership-change signal for the [LT] sleeve. Norway has no equivalent public per-fund holdings dataset that I could verify. NBIM's holdings API gives year-end snapshots back to 1998 (half-year snapshots unverified). Monthly flow statistics from Fondbolagens förening (SE) and VFF (NO) are market-level only.

### Cited Findings

**SWEDEN: FI "Fondinnehav per kvartal" [LT]**
- *Page:* `https://www.fi.se/sv/vara-register/fondinnehav-per-kvartal/`. Scrapers find the newest `.zip` link on this page. — [cyberw/fondjamforaren download.py](https://github.com/cyberw/fondjamforaren/blob/a8e388671a7773b6a628df3da202803a1e670a82/download.py); [PeterBlenessy/stoqster fiAPI.js](https://github.com/PeterBlenessy/stoqster/blob/74046d7a9459387eb1cadfb05c33877f0e1355fd/src/api/fiAPI.js)
- *Observed download URL (Mar 2026):* `https://www.fi.se/FondInnehavLista/download?filnamn=Fondinnehav_2025Q4_2026-03-17 17.09.zip`. This file extracted to **706 XML files**, one per fund. — [cyberw/fondjamforaren README](https://github.com/cyberw/fondjamforaren/blob/a8e388671a7773b6a628df3da202803a1e670a82/README.md). Another project documents a different pattern, `fondinnehav-kv{N}-{YYYY}.zip`, which may be outdated. — [stoqster api-integrations-fi.md](https://github.com/PeterBlenessy/stoqster/blob/main/docs/api-integrations/api-integrations-fi.md)
- *XML fields:*
  - Fund level: `Fond_namn`, `Fond_ISIN-kod`, `Fond_institutnummer`, `Fondförmögenhet`, `Förvaltningsavgift_fast`
  - Holdings under `FinansiellaInstrument/FinansielltInstrument`: `Instrument_namn`, `Instrument_ISIN-kod`, `Instrumentkategori`, `Marknadsvärde`, `Andel_av_fondförmögenhet`
  - Parsers must handle both a single instrument and an array.
  - Source: [stoqster api-integrations-fi.md](https://github.com/PeterBlenessy/stoqster/blob/main/docs/api-integrations/api-integrations-fi.md)
- *Coverage and lag:* quarterly ZIP/XML from **Q4 2018**, published with about a **two-month delay**. It covers Swedish securities funds but excludes special funds (specialfonder), and also includes assets, fees, benchmark, active risk and standard deviation. Corrections replace the visible version, and filenames contain the latest reporting timestamp. Foreign-domiciled funds sold in Sweden are not covered. — [nolltillmiljoner free-data audit 2026-09-22](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md). The audit gives the page as `https://www.fi.se/sv/vara-register/fondinnehav/`, which differs from the slug above.
- *Cost:* free. Reuse rights were flagged as "needs validation" by that audit.

**NORWAY: NBIM (Government Pension Fund Global) holdings [LT]**
- *API (third-party observed, downloaded 2026-08-01):* `https://www.nbim.no/api/investments/v2/report/?assetType=eq&date=YYYY-12-31&fileType=csv|xlsx`. The CSV is UTF-16LE and semicolon-delimited. The Excel version keeps typed numeric columns and incorporation-country values that are blank in the CSV export. The snapshots are year-end positions only, not trades, and company names are not stable identifiers across years. — [binchen19/djr data/raw/gpfg/README.md](https://github.com/binchen19/djr/blob/main/data/raw/gpfg/README.md)
- *History:* the manifest has entries from `date=1999-12-31` onward. — [binchen19/djr gpfg_source_manifest.csv](https://github.com/binchen19/djr/blob/877d14bec6d1431404101d9955d3e0c08507a1f7/data/processed/gpfg_source_manifest.csv). A legacy endpoint is `https://www.nbim.no/api/investments/history.json?year=<YYYY>`. — [uchicago-dsi/debit-scrapers nbim.py](https://github.com/uchicago-dsi/debit-scrapers/blob/139e9f1dd7d3c534a02e18cbc4f6bd3149db98d3/services/extract/src/pipeline/extract/workflows/banks/nbim.py)
- NBIM's source page for these files is `https://www.nbim.no/en/investments/all-investments/`. — [binchen19/djr README](https://github.com/binchen19/djr/blob/main/data/raw/gpfg/README.md)
- Media coverage on 12 Aug 2026 discussed NBIM's half-year results and holdings, including newly disclosed stakes such as SpaceX. — [CNBC 2026-08-12](https://www.cnbc.com/2026/08/12/norway-sovereign-wealth-fund-spacex-nvidia-apple-nbim.html)

**FUND FLOWS (market-level) [LT, market sentiment]**
- *Fondbolagens förening (SE)* publishes monthly fund-savings statistics as press releases, also distributed via Cision. Examples:
  - July 2026: total net savings SEK 28.3bn, with the largest inflows to long-term bond funds, then equity funds (mainly global and Swedish).
  - June 2026: equity funds net +SEK 9.6bn.
  - May 2026: total +SEK 26.8bn, equity funds +SEK 10.5bn.
  - April 2026: +SEK 20.1bn total, equity +SEK 10.9bn.
  - Year to date through July: SEK 95bn, or SEK 112bn excluding the premium pension.
  - Sources: [Cision: 28 miljarder till fonder i juli](https://news.cision.com/se/fondbolagens-forening/r/28-miljarder-till-fonder-i-juli,c4381804); [Fondbolagen: Stort nysparande i fonder även under maj](https://fondbolagen.se/aktuellt/pressrum/pressmeddelanden/stort-nysparande-i-fonder-aven-under-maj/); [Placera 2026-05-11](https://www.placera.se/nyheter/fondsparandet-okar-muntrare-tongangar-2026-05-11)
- *Verdipapirfondenes forening (NO)* publishes monthly statistics news. Examples:
  - H1 2026: Norwegian retail clients net bought NOK 38.2bn of funds, NOK 18.4bn of it in equity funds; all client groups combined net bought NOK 154.1bn, NOK 57.6bn in equity funds.
  - April 2026: retail NOK 9.9bn net, NOK 4.7bn in equity funds.
  - Sources: [VFF: Rekordsterk nettotegning H1 2026](https://vff.no/nyheter/2026/rekordsterk-nettotegning-i-verdipapirfond-i-forste-halvdel-av-2026); [VFF: Høy fart i april](https://vff.no/nyheter/2026/hoy-fart-i-norske-verdipapirfond-i-april); [VFF news](https://vff.no/nyheter)
- A 2026 audit found "No comprehensive Nordic ETF/fund flows database" beyond FI holdings; fund-flow tracking requires commercial sources. — [nolltillmiljoner audit](https://github.com/ingencopycat/nolltillmiljoner/blob/main/docs/internal/free-data-audit-2026-09-22/report.md)

### Inferences
- The FI quarterly XML supports [LT] stock-level signals from the change, quarter over quarter, in the share of a company's market cap held by Swedish funds. Examples are breadth of ownership (number of funds holding), crowding (high fund ownership plus heavy inflows), and "smart" fund cohorts (small-cap specialist funds). Because of the roughly two-month lag, these are slow signals and should not be used in the [ST] sleeve.
- Swedish funds also hold Norwegian stocks, so FI's data partly covers Norwegian names. There is no Norwegian equivalent.
- NBIM's year-end file is mostly global and is mainly useful as an [LT] "quality or index-like ownership" descriptor for Norwegian names. Because NBIM is largely index-tracking, it carries little alpha information.
- Market-level fund flows (SE/NO) are at most a regime or risk-appetite input, not stock selection.

### Gaps
- Folketrygdfondet (GPFN) holdings: I found no download endpoint or scraper. Its large Oslo Børs stakes are visible through flagging (NewsWeb 1006) and annual reports, but this is unverified.
- Norwegian per-fund holdings disclosures (UCITS semi-annual reports, fund-company websites) and Morningstar holdings access/cost were not researched (blocked and out of search budget).
- Not verified: whether NBIM publishes 30 June snapshots via the same API (`date=YYYY-06-30`).
- Download endpoints and file formats for the Fondbolagen and VFF statistics are unverified; both domains were blocked.

## 5. Buybacks: how programmes and executions are published, and structured data

### Takeaway
Buyback announcements and the weekly/daily execution reports required by MAR article 5 are free but unstructured. In Norway they are NewsWeb category 1007, which can be pulled through the JSON API. In Sweden they are MFN/Cision press releases with HTML tables. In Denmark they go through the OAM. The only structured Nordic buyback dataset I found is Börsdata's `/v1/holdings/buyback`, from Modular Finance Holdings, which requires Pro+.

### Cited Findings
- *Norway:* NewsWeb category **1007** = acquisition or disposal of the issuer's own shares; **1008** = total number of voting rights and capital, which is useful for share-count changes after cancellations or issues. — [bjelle-ai newsweb.ts](https://github.com/kennyng90/bjelle-ai/blob/main/apps/workers/src/source/newsweb.ts). Supervision of buyback programmes and price stabilisation moved from Oslo Børs to Finanstilsynet on **1 April 2025**. — [BAHR](https://bahr.no/newsletter/finans-overforing-av-tilsynsoppgaver-fra-oslo-bors-til-finanstilsynet-1-april-2025); [Euronext issuer notice](https://www.euronext.com/nb/media/13300/download)
- *Sweden:* buyback execution reports are company press releases on MFN. One open-source tracker for Evolution identifies them by keywords ("återköp", "förvärv av egna aktier", "repurchase of own shares") and parses the HTML tables into Datum, Antal aktier, Snittkurs and Transaktionsvärde. It adds daily volume and percent of daily volume, and filters implausible values. — [evuul/evodata buybacksSync.js](https://github.com/evuul/evodata/blob/e52d7884786a4bb4e98f5969218d9b98099858e9/src/lib/buybacksSync.js)
- *Denmark:* weekly buyback-transaction announcements appeared in the DFSA OAM (e.g. "Vestas – Transaktioner i forbindelse med aktietilbagekøbsprogram i perioden 20.–24. november 2017"). — [Spider_finanstilsynet.dk README](https://github.com/PythonSpiderMan/Spider_finanstilsynet.dk/blob/272db37a67405814d418ce22ac7f252c42afb1ff/README.md)
- *Structured dataset (paid):* `GET https://apiservice.borsdata.se/v1/holdings/buyback?authKey=…&instList=<≤50 ids>`. It returns `BuybackRowV1 {change (int64), changeProc (double), price, currency, shares (int64), sharesProc (double), date}` for Nordic instruments only. — [borsdata-mcp swagger.json](https://github.com/emmanuelay/borsdata-mcp/blob/main/client/assets/swagger.json); [borsdata-mcp-server client.ts](https://github.com/carlwestman/borsdata-mcp-server/blob/1d0c9a6a7c42272a7fcf3e84c1f3b81c4157eb59/src/api/client.ts). Access requires Pro+ (about 59 EUR/month; REST API Pro+ only since 1 Feb 2025). — [marketscan nordic-data-landscape.md](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/nordic-data-landscape.md)
- *Anecdotal, unvalidated hobby backtests of NewsWeb category reactions:*
  - One repo assigns "MAJOR SHAREHOLDING NOTIFICATIONS" a score of 2.53 and "MANDATORY NOTIFICATION OF TRADE PRIMARY INSIDERS" 4.60 ("avg net return per category"). — [Hallis1221/obs-news-reaction signals.py](https://github.com/Hallis1221/obs-news-reaction/blob/a8c7854de056364471fe65b849670bfeba23841a/src/obs_news_reaction/signals.py)
  - Another lists "MAJOR SHAREHOLDING NOTIFICATIONS" at +0.15% (58% positive) and "TOTAL NUMBER OF VOTING RIGHTS" at +2.82%. — [Hallis1221/obs-react classifier.py](https://github.com/Hallis1221/obs-react/blob/e7c88b1098fba5d201fd3256fe3f57421ed9082e/src/obs_react/analysis/classifier.py)
  - Sample sizes and methods are undocumented, so these are low quality.

### Inferences
- A free buyback dataset can be built from the following, each in its own collector:
  - Norway: NewsWeb 1007 and 1008 message bodies, which usually state shares bought, average price and cumulative holding
  - Sweden: MFN releases matched by keyword
  - Denmark: OAM
- Parsed fields:
  - **Programme announced** (size, max shares, period) [ST] for the announcement effect, [LT] as shareholder yield
  - **Execution intensity** (shares bought ÷ ADV, % of shares outstanding per week) [ST] for price support and [LT] for net payout and dilution
- Börsdata Pro+ is the low-effort structured alternative. Its licence restrictions (see section 2) apply.

### Gaps
- No official Nordic buyback register exists. FI and Finanstilsynet receive MAR article 5 transaction reports, but I found no public structured publication of them.
- Not verified: Börsdata `holdings/buyback` coverage by country (Oslo, Copenhagen and Helsinki listings) and its history depth.
- Swedish buyback reporting conventions (weekly vs. daily, the Safe Harbour template) were not verified from primary sources.

## 6. Other flows and events: index rebalancing, IPOs and lock-ups, equity issues, foreign-investor flows

### Takeaway
Index calendars have changed. OBX/OSEBX reviews now take effect after the third Friday of **March and September**, having moved from June/December. OMXS30 is still reconstituted on the first trading day of January and July, but since 1 July 2025 its selection is driven by free-float market cap. NewsWeb categories (1103 prospectus, 1005 inside information, 1008 voting rights/capital) are the cheapest free event feed for IPOs, private placements and dilution in Norway. Foreign-ownership data exists only at aggregate level (SSB monthly from Euronext Securities Oslo) or as paid Euronext "Investor Figures".

### Cited Findings
- *OBX / OSEBX (Euronext Oslo):* OBX is revised semi-annually, with composition changes and capping implemented after the close on the **third Friday of March and September**. Review cut-off is after the close on the penultimate Friday of February and August. Reviews were previously effective after the third Friday of June and December (cut-off: penultimate Friday of May and November). OSEBX is also revised semi-annually on the March/September schedule. — [OBX Index Family Rulebook v24-02](https://live.euronext.com/sites/default/files/documentation/index-rules2/OBX_Index_Family_Rulebook.pdf); [OBX factsheet (as of 31 Mar 2026)](https://live.euronext.com/sites/default/files/documentation/index-fact-sheets/OBX_Total_Return_Index_Factsheet.pdf); [OSEBX factsheet](https://live.euronext.com/sites/default/files/documentation/index-fact-sheets/Oslo_Bors_Benchmark_GI_Index_Factsheet.pdf); [Oslo Børs indices consultation summary](https://live.euronext.com/sites/default/files/documentation/product/Oslo%20Bors%20Equity%20Indices%20consultation%20summary%20of%20responses%20update.pdf). The March cycle was in use by 2023. — [Euronext: March 2023 review results of the OBX family](https://www.euronext.com/en/about/media/euronext-press-releases/euronext-announces-march-2023-review-results-obxr-family)
- *OMXS30 (Nasdaq Stockholm):* reviewed semi-annually and reconstituted on the first trading day of January and July. **On 1 July 2025** the primary inclusion criterion changed from liquidity to free-float market cap, with a minimum liquidity requirement of SEK 50m average daily value traded over six months. — [Wikipedia: OMX Stockholm 30](https://en.wikipedia.org/wiki/OMX_Stockholm_30). Nasdaq announces changes by press release shortly before the effective date. For example, the release of 22 June 2022 added SBB B and removed SKA B effective 1 July 2022, and a June 2025 release covered the July 2025 review. — [Nasdaq PR 2022-06-22](https://www.nasdaq.com/press-release/nasdaq-announces-semi-annual-changes-to-the-omx-stockholm-30-index-2022-06-22); [Mondo Visione: June 2025 OMXS30 changes](https://mondovisione.com/media-and-resources/news/nasdaq-announces-semi-annual-changes-to-omx-stockholm-30-index-2025623/); [Nasdaq IR release](https://ir.nasdaq.com/news-releases/news-release-details/semi-annual-review-omx-stockholm-30-index-2). Nasdaq RSS subscriptions (market notices, company news) are at `https://subscribe.news.eu.nasdaq.com/rss`, and a corporate-actions Excel is available at `/news/corporate-actions` on nasdaqomxnordic.com. — [candlechart NEWS_SOURCES.md](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md)
- *IPOs, prospectuses, issues:* NewsWeb categories 1103 prospectus, 1005 inside information, 1008 total number of voting rights and capital, and 1202 trading halt. — [bjelle-ai newsweb.ts](https://github.com/kennyng90/bjelle-ai/blob/main/apps/workers/src/source/newsweb.ts). FI also keeps a prospectus register (Prospektregistret) for rights issues and IPOs. — [candlechart NEWS_SOURCES.md](https://github.com/boeriksson/candlechart/blob/main/NEWS_SOURCES.md)
- *Foreign/sector ownership (Norway):* SSB securities statistics are built from monthly Euronext Securities Oslo extracts. — [SSB: Securities](https://www.ssb.no/en/bank-og-finansmarked/verdipapirmarkeder/statistikk/verdipapirer). Euronext Securities Oslo's "Investor Figures" provides ISIN-level aggregated investor data (paid). — [Euronext CSD Oslo data services](https://www.euronext.com/en/csd/oslo/data-servicesold)

### Inferences
- [ST] index-event signals:
  - OBX/OSEBX adds and deletes between the announcement (after the late-February/late-August cut-off) and the effective date (third Friday of March/September)
  - OMXS30 changes announced in late June/December, effective the first trading day of July/January
  - The 2025 free-float-cap rule makes OMXS30 changes more predictable from market-cap rankings, so the app can pre-compute candidates
- [ST] private placements on Oslo Børs (often announced after market close as inside information, category 1005, with a "bookbuilding completed" follow-up) can be detected by title keywords ("private placement", "rettet emisjon", "successfully completed"). The placement price and discount should be logged. [LT] the dilution in 1008 updates should feed per-share metrics.
- Lock-up expiry dates appear only in IPO prospectuses and announcements. A small parser that stores "lock-up X days from first day of trading" per IPO would make expiry an [ST] event calendar.

### Gaps
- MSCI (quarterly reviews), FTSE GEIS and STOXX Nordic review calendars and methodologies: not verified this session (sources blocked, search budget exhausted).
- I found no structured Nordic IPO lock-up dataset, and no Nordic evidence on lock-up-expiry returns.
- I found no study on Oslo Børs private-placement discounts and post-issue returns.
- SCB Aktieägarstatistik (Swedish foreign ownership share, semi-annual) and Euroclear Sweden ownership statistics are unverified.
- I found no daily or weekly foreign-flow data by stock for either market. The exchanges' member or broker statistics, e.g. "mäklarstatistik" in Holdings per [Lund LibGuides](https://libguides.lub.lu.se/c.php?g=694482&p=4983293), are the nearest proxy, and are paid.

## 7. Evidence on predictive value (short interest, ownership and flows, buybacks) and sleeve fit

### Takeaway
The best evidence is pan-European work on EU-SSR disclosures. Large disclosed short positions are followed by negative abnormal returns over days to about three months, and the most informed short sellers hide just below the 0.5% threshold. Nordic buyback studies show announcement returns of roughly +2% over 2–5 days, plus signs of under-reaction and long-run drift. I found no rigorous Norway-specific short-interest study, and no Nordic study of flagging or fund-flow returns.

### Cited Findings
**Short interest / disclosed short positions**
- **Jones, Reed & Waller (2016), *Review of Financial Studies* 29(12): "Revealing Shorts".** Disclosure of large short positions, required EU-wide since 2012, reduces short interest, bid-ask spreads and price informativeness. Reported abnormal returns include about −1.78% over three days around disclosure, and a statistically significant −5.23% 90-day CAR after specific disclosures. The −0.25% average daily return difference over the first ten trading days implies about −2.75% cumulative. The authors interpret large short sellers as well-informed rather than manipulative. — [EconPapers (RFS 2016)](https://econpapers.repec.org/article/ouprfinst/v_3a29_3ay_3a2016_3ai_3a12_3ap_3a3278-3320..htm); [Warwick seminar version PDF](https://warwick.ac.uk/fac/soc/wbs/subjects/finance/events/seminars/revealingshorts_may_2014_small.pdf). These numbers come from search-result summaries, so the exact event definitions should be checked in the paper.
- **Jank, Roling & Smajlbegovic (2021), *Journal of Financial Economics* 139(1): 209–233: "Flying under the radar".** Positions bunch just below the disclosure threshold, with an excess mass of 92.8% for first-time disclosure decisions. Positions held by such "secretive" investors are followed by more negative returns, i.e. they hold superior information. — [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X20302075); [EUR open-access PDF](https://pure.eur.nl/files/56168354/1_s2.0_S0304405X20302075_main.pdf); [Bundesbank research brief 2017 "Short selling below the radar"](https://www.bundesbank.de/en/publications/research/research-brief/2017-10-short-selling-764476)
- **Jank & Smajlbegovic (2017), "Dissecting Short-Sale Performance: Evidence from Large Position Disclosures".** A secondary summary reports that hedge funds earn about 5.5% a year in Fama-French alpha on their disclosed short positions. — [ResearchGate](https://www.researchgate.net/publication/315309828_Dissecting_Short-Sale_Performance_Evidence_from_Large_Position_Disclosures); [marketscan alpha audit](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md)
- **Secondary, unverified summaries in the same audit:**
  - Della Corte et al. report a "short conviction" strategy earning over 8% a year gross across 15 EU markets in 2012–2018.
  - Ashby (2024, Cambridge; doi 10.17863/cam.110731) finds that naive long/short portfolios on UK regulatory short data have "at most marginal significance; the short side loses".
  - Source: [marketscan alpha audit](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md)
- **Other studies found but not reviewed:**
  - Sweden: a thesis on the ten most shorted OMXS Large Cap shares finds short sellers can earn excess returns over OMXS30GI. — [DiVA: "Luck or skills for short sellers"](https://www.diva-portal.org/smash/get/diva2:1666268/FULLTEXT01.pdf)
  - Sweden: a thesis on short-seller research reports targeting Swedish companies. — [DiVA thesis](https://www.diva-portal.org/smash/get/diva2:1879198/FULLTEXT02.pdf)
  - Finland: an Aalto thesis on whether EU-SSR net-short publications are followed by abnormal returns on the Helsinki exchange. Its findings were not retrieved. — [Aaltodoc](https://aaltodoc.aalto.fi/items/ecd245ac-9e32-46fc-8729-089138cdae02)
  - A 2024 paper on disclosure rules: "Short sale disclosure rules: an information story". — [Springer, Rev. Quant. Finance & Accounting 2024](https://link.springer.com/article/10.1007/s11156-024-01375-0)

**Buybacks (Nordic)**
- **Norway (Skjeltorp 2004, Norges Bank / BI):**
  - 318 repurchase announcements, 1998–2001, with a CAR of about +2.52% over (−2,+2).
  - The market "seems to under-react to the announcement signal".
  - Positive excess returns occur on actual repurchase days, consistent with price support and with superior timing by repurchasing firms.
  - Long-term excess returns were found only for firms that announced but did not execute.
  - Programmes grew from 28 announced in 1998 to 112 in 2001.
  - Source: [ResearchGate: The market impact and timing of open market share repurchases in Norway](https://www.researchgate.net/publication/228391537_The_market_impact_and_timing_of_open_market_share_repurchases_in_Norway); as summarised in [Lund University thesis](https://lup.lub.lu.se/student-papers/record/9212044/file/9212045.pdf)
- **Sweden:**
  - Råsbrant: on Stockholm 2000–2009, programme initiation announcements earn a two-day abnormal return of about +2%. — [SSRN 1780967](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1780967)
  - Swedish listed real-estate firms: +1.96% on announcement day and +2.32% CAR over the first ten days. — [DiVA thesis](https://www.diva-portal.org/smash/get/diva2:497867/FULLTEXT01.pdf)
  - Stockholm 2005–2013 long-run abnormal returns after announcements: 14.34% for large firms, 20.13% for mid and 6.61% for small (thesis-level evidence). — [DiVA: Long-term Abnormal Returns Following Share Repurchase Announcements](https://www.diva-portal.org/smash/get/diva2:1222662/FULLTEXT01.pdf)
  - 218 Nasdaq Stockholm announcements, 2020–2025: positive, significant CAARs for both capital-structure and incentive-programme motives. — [Uppsala master's thesis](https://uu.diva-portal.org/smash/get/diva2:2083163/FULLTEXT01.pdf)
- **International context:** Manconi, Peyer & Vermaelen study buybacks around the world and long-term shareholder value. — [JFQA](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/are-buybacks-good-for-longterm-shareholder-value-evidence-from-buybacks-around-the-world/4006D9DB64B8CB12086858D9DBF0A2B5); [ECGI WP 436/2014](https://www.ecgi.global/sites/default/files/working_papers/documents/finalmanconipeyervermaelen_0.pdf). A 2026 audit judged buyback evidence "in Europe generally weak" as a core factor and used it only as a secondary quality and net-payout input. — [marketscan alpha audit](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md)

**Ownership change and institutional flows**
- Insider (PDMR) clusters in Sweden: theses report that clusters of three or more distinct buyers amplify the signal. Aggregated insider buying predicts 30/60-day excess returns, and sell clusters have more explanatory power than buy clusters. These are Swedish theses (Lund 2015, DiVA 2018/2024) cited secondarily. — [marketscan alpha audit](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md)
- The same audit states that institutional and fund ownership flows were "not explicitly covered" by its literature review. — [marketscan alpha audit](https://github.com/hankkontakt/marketscan/blob/e5052ddca257445316be23bdc887132e8871df34/.opencode/audit/alpha-nordisk-smabolag-research-2026-08-28.md)

### Inferences
Sleeve mapping and suggested use (to be validated by the app's own logging):

| Signal | Sleeve | Horizon suggested by evidence | Notes |
|---|---|---|---|
| New or increased public short (≥0.5%) in NO SSR / SE FI | ST (and LT filter) | Days to 90 days (JRW 2016: about −2.75% over 10 days, −5.23% over 90 days) | Use the daily diff; weight by holder track record; use as a negative tilt in a long-only allocation |
| Aggregate short % (SE ≥0.1%; NO public) | LT risk filter | Months | Catches sub-threshold "secretive" shorts in Sweden (Jank et al. 2021); avoid the top 5–10% most shorted |
| Short covering (positions dropping below 0.5%) | ST | Days to weeks | Not directly studied in Nordic sources found; log and test |
| IBKR borrow fee / availability (SE only, if file exists) | ST | Days | Squeeze and crowding flag; one broker's view |
| Buyback programme announcement | ST, plus LT drift | 2–5 days (+2% to +2.5% CAR); possible multi-month drift (Skjeltorp; Swedish theses) | NewsWeb 1007 / MFN keywords |
| Buyback execution intensity | ST (price support) / LT (net payout) | Days (support); quarters (payout) | Shares bought ÷ ADV |
| Flagging notice (new 5%+ holder, threshold crossings) | ST event / LT ownership | Unknown, no Nordic study found | Log announcement-day and +20-day returns to learn the effect |
| FI quarterly fund holdings change | LT | Quarters | Two-month publication lag |
| Index add/delete (OBX/OSEBX/OMXS30) | ST | Announcement to effective date | Pre-compute candidates; OMXS30 is now cap-based |
| Private placement / dilution (NewsWeb 1005/1008) | ST (discount pressure) / LT (dilution) | Days / years | No Nordic evidence found |
| Aksjonærregisteret yearly changes; NBIM year-end | LT descriptor | Years | Low frequency; GDPR-sensitive (names) |
| Market-level fund flows (Fondbolagen, VFF) | LT regime | Months | Not stock-specific |

- Because the most-informed shorts sit below 0.5%, Swedish data should be more informative than Norwegian data for the same rule. The formula should keep country-specific coefficients.
- The app proposes how to split a cash account across Nordnet-tradable shares, which is effectively long-only. Short-interest signals should therefore act as negative tilts or avoid-filters, not as short positions. Whether Nordnet supports retail shorting of Nordic names was not checked.

### Gaps
- I found no peer-reviewed Norway-specific study of SSR disclosures and returns. The Finnish (Aalto) thesis result was not retrieved.
- I found no Nordic evidence on returns around flagging notices, fund-holding changes (FI fondinnehav), OBX/OSEBX/OMXS30 index inclusion effects, IPO lock-up expiries, or Oslo private placements. These need the app's own event studies.
- The figures from Della Corte et al., Ashby (2024) and Jank & Smajlbegovic (2017) are from a secondary audit and were not checked against the papers.
- The Jones/Reed/Waller numbers come from search-result summaries. The exact windows (3-day vs. 10-day vs. 90-day) and samples should be confirmed in the published paper.
