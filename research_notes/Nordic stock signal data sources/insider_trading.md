# Insider (PDMR / primary-insider) transaction data for Nordic shares, and evidence on its predictive power

> **How to read these notes.** Sleeve tags: **[ST]** = short-term trading sleeve (intraday to a few days); **[LT]** = long-term value sleeve (months to years).
> **Verification status (2 Oct 2026).** WebSearch, WebFetch (GitHub only) and GitHub code search were used. Primary regulator, exchange and academic domains (fi.se, marknadssok.fi.se, newsweb.oslobors.no, finanstilsynet.no, nhh.no, ecgi.global, nber.org, ssrn, repec, arxiv, esma.europa.eu and others) were blocked for WebFetch. An attempt to verify endpoints live with curl was **denied by the permission system**, so I did not pursue it. No endpoint below is "verified live 2026-10-02" by me. I label endpoints instead as **"third-party verified (date)"** when an independent project's live run or output shows they worked recently, or **"unverified"** otherwise. Data subdomains the user would need to allow for live checks: `marknadssok.fi.se` (the FI register is *not* served from www.fi.se), `api3.oslo.oslobors.no` (NewsWeb is a JavaScript single-page app that loads from this host), `api.news.eu.nasdaq.com` and `attachment.news.eu.nasdaq.com` (Nasdaq Nordic announcements), `appft.gold.extension.gopublic.dk` (backend for the Danish FSA's OAM search) and `apiservice.borsdata.se` (Börsdata API).
> **Academic abstracts.** Journal abstracts were read from GitHub-hosted journal table-of-contents dumps (repositories danielyang1009/light-speed-engine and fagan2888/zhanghaitao1.github.io). Where only secondary summaries (GitHub research notes) were available, this is flagged.

## 1. Sweden: how Finansinspektionen's Insynsregistret works (endpoints, parameters, fields, revisions, latency, history, licence)

### Takeaway
Sweden has the best Nordic insider data. FI publishes every MAR Art. 19 notification in a free, public register at `marknadssok.fi.se`. It has an undocumented but stable CSV export (`.../Search/Search?SearchFunctionType=Insyn&...&button=export`). The CSV is UTF-16LE, semicolon-separated, has 22 columns and returns at most 1,000 rows per query, so collectors split date windows in half until each window is under the cap. The data starts in July 2016, has roughly 167k rows as of August 2026, appears as soon as the PDMR files, and includes explicit status, revision and share-programme flags. A CC0 nightly mirror on GitHub (civictechsweden) is a practical fallback that this environment can reach. Tags: **[ST] + [LT]**.

### Cited Findings

**Access method and exact endpoint (open-source consensus)**
- Export endpoint used by the civictechsweden collector: `https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search` with `SearchFunctionType=Insyn`, `Publiceringsdatum.From=YYYY-MM-DD`, `Publiceringsdatum.To=YYYY-MM-DD`, `button=export`. It forces TLS 1.2 through a custom SSL adapter and sends a browser User-Agent (`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36`). — [civictechsweden fetch_insynsregistret.py](https://raw.githubusercontent.com/civictechsweden/oppna-insynsregistret/main/fetch_insynsregistret.py)
- ErikMalmgren/Insynshandel uses the same base URL (`FI_SEARCH_URL = "https://marknadssok.fi.se/Publiceringsklient/sv-SE/Search/Search"`) and constants `FI_ENCODING="utf-16-le"`, `FI_DELIMITER=";"`, `FI_ROW_CAP=1000` and `FI_EARLIEST="2016-07-01"`. — [Insynshandel config.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/HEAD/src/insynshandel/config.py)
- ErikMalmgren sends the full parameter set: `SearchFunctionType=Insyn`, `Utgivare=` (issuer, empty), `PersonILedandeStallningNamn=` (PDMR name, empty), `Transaktionsdatum.From=`/`Transaktionsdatum.To=` (empty), `Publiceringsdatum.From`/`.To` (ISO dates), `button=export`, `Page=1`. — [Insynshandel sources/fi.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/src/insynshandel/sources/fi.py)
- ADR 0002 in the lassemand/nexus project documents the same GET endpoint with a language path of `sv-SE` or `en-GB`, no authentication, and filters `Utgivare={issuer}`, `PersonILedandeStällningNamn={pdmr}` (spelled with "ä" here), `Transaktionsdatum.From/To` and `button=export`. It also documents an issuer autocomplete: `GET https://marknadssok.fi.se/Publiceringsklient/sv-SE/AutoComplete/HämtaAutoCompleteListaFull?sokfunktion=Insyn&falt=Utgivare&sokterm={name}`, which returns a JSON array of issuer names. — [nexus ADR-0002 FI PDMR register access](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)
- A Go client calls the English variant (`/publiceringsklient/en-GB/Search/Search?button=export&SearchFunctionType=Insyn&Publiceringsdatum.From=..&Publiceringsdatum.To=..`). It sends `Accept-Encoding: gzip`, gunzips when `Content-Encoding: gzip` is returned, and decodes UTF-16 before parsing the CSV. — [AnteWall/go-finansinspektionen client.go](https://raw.githubusercontent.com/AnteWall/go-finansinspektionen/HEAD/pkg/insider/client.go)
- The HTML search UI is `https://marknadssok.fi.se/publiceringsklient/en-GB/Search/Start/Insyn`. A live check on **28 Aug 2026** returned HTTP 200 for both the HTML search and the CSV export (`?button=export&Publiceringsdatum.From=2026-08-27…`, UTF-16, semicolon-separated). It also found that **each transaction appears twice in the HTML table but once in the CSV**. — [hankkontakt/marketscan insider-reconciliation-2026-08-28](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md) (**third-party verified 2026-08-28**)
- Parameter pitfall: `FromDate`/`ToDate` with `format=json` **ignore the date filter and return all 166,978 rows**. Use `Publiceringsdatum.From/To` with `button=search` or `button=export`. — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md). (A planning document in the same repository still proposes `FromDate/ToDate/PageSize=100`; the reconciliation contradicts it — [03_fi_insider_cluster.md](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/docs/plan/03_fi_insider_cluster.md).)
- HTML paging alternative: `.../en-GB/Search/Search?SearchFunctionType=Insyn&button=search&paging=True&page=N` (with `Transaktionsdatum_From/_To`), parsing 14 HTML table cells. — [freducom/bloomvalley fi_se_insider.py](https://raw.githubusercontent.com/freducom/bloomvalley/HEAD/backend/app/pipelines/fi_se_insider.py)
- Conflicting claim: another audit in the same repository says the register has "Ingen API/CSV-export → scrape". At least four independent codebases above contradict this, so treat that audit as unreliable. — [hankkontakt nordic-data-landscape.md](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/nordic-data-landscape.md)

**Response format, limits and politeness**
- The CSV is UTF-16LE (ADR: no BOM) and semicolon-delimited, with 23 fields per line: 22 data columns plus a trailing empty one. The 1,000-row cap is detected as row count ≥ 1000. A capped window is halved at its publication-date midpoint, and a single day that is still capped is marked `truncated=True`. Each row is hashed with SHA-256 over the 22 fields joined by `\x1f`. — [Insynshandel fi.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/src/insynshandel/sources/fi.py); [nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)
- civictechsweden queries 14-day windows starting 3 July 2016 and recursively halves any window that returns exactly 1,000 rows. It strips non-breaking spaces (`\xa0`), trailing empty columns and embedded newlines. Its dedup key is publication date, issuer, declarant, person, nature, ISIN, transaction date, volume and price. Results are cached in `.insyn_cache/` with `index.json`. — [civictechsweden fetch script](https://raw.githubusercontent.com/civictechsweden/oppna-insynsregistret/main/fetch_insynsregistret.py)
- Polite-collection defaults in Insynshandel: 3.0 s between requests, 60 s timeout, 4 retries, at most 600 requests per run, and an identifying User-Agent with a contact address. Windows are a 14-day seed with a 1-day bisect floor, a 7-day recent re-scan and a 90-day re-scan. — [Insynshandel config.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/HEAD/src/insynshandel/config.py)
- Numbers use a Swedish decimal comma (replace `,` with `.`). There is no push mechanism and no published SLA; the ADR recommends polling daily. — [nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)

**Fields: the 22 CSV columns, in order**
- `Publiceringsdatum; Emittent; LEI-kod; Anmälningsskyldig; Person i ledande ställning; Befattning; Närstående; Korrigering; Beskrivning av korrigering; Är förstagångsrapportering; Är kopplad till aktieprogram; Karaktär; Instrumenttyp; Instrumentnamn; ISIN; Transaktionsdatum; Volym; Volymsenhet; Pris; Valuta; Handelsplats; Status`. — [Insynshandel fi.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/src/insynshandel/sources/fi.py)
- In English: publication date, issuer, LEI, notifying party, PDMR, position, closely associated person, correction, correction description, first-time report, linked to share programme, nature, instrument type, instrument name, ISIN, transaction date, volume, volume unit, price, currency, venue, status.
- `Publiceringsdatum` carries a time stamp (`YYYY-MM-DD HH:MM:SS`) and `Status` is `Aktuell` (current) or a cancelled/revised value. — [nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)
- **Derivatives such as swaps and options often have an empty ISIN.** Use the fallback key (Instrumentnamn, Transaktionsdatum, Volym). A single execution split into parts can produce several rows for the same person, ISIN and day; aggregate them. — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)

**`Karaktär` (nature of transaction) values and how they should be treated**
- Seed mapping in Insynshandel: only `Förvärv` (+1) and `Avyttring` (−1) count. Everything else is excluded:
  - `Teckning`: "Rights-issue subscription — excluded; mostly BTA/BTU interim paper".
  - `Tilldelning`: "54% aktieprogram and 45% priced at 0 — mostly free awards".
  - `Interntransaktion – Förvärv/Avyttring` and `Koncernintern överföring …`: internal or intra-group transfers.
  - `Lösen ökning/minskning`: paired legs of an option exercise.
  - `Utbyte` and `Konvertering` (both ökning/minskning): paired legs.
  - `Fusion` and `Fission` (ökning/minskning): corporate actions.
  - `Utdelning mottagen/lämnad`, `Gåva mottagen/lämnad`, `Arv …` and `Bodelning …`: dividends in kind, gifts, inheritance, division of marital property.
  - `Pantsättning` and `Pantsättning åter`: pledges.
  - `Lån mottaget/utlåning/återgång`: securities lending.
  - `Inlösen egenutfärdat instrument`, `Utfärdande av instrument` and `Blankning`.
  - — [Insynshandel data/seed/nature_map.csv](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/data/seed/nature_map.csv); [Insynshandel about.html](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/frontend/about.html)
- bloomvalley maps the English export's "acquisition" to buy and "disposal"/"sale" to sell, and skips everything else. It flags a trade as "significant" when value ≥ SEK 100,000 or when a CEO or CFO buys. It does **not** handle Status, Korrigering, share-programme or Närstående flags. — [bloomvalley fi_se_insider.py](https://raw.githubusercontent.com/freducom/bloomvalley/HEAD/backend/app/pipelines/fi_se_insider.py)

**Revisions and cancellations**
- Insynshandel tracks `Status` values `Aktuell`, `Reviderad` and `Makulerad`. Revised or withdrawn reports are *superseded, not deleted*. About 180 rows with erroneous price totals are excluded, rows without an LEI are excluded, and duplicate or incorrect LEIs can merge unrelated companies. — [Insynshandel README](https://github.com/ErikMalmgren/Insynshandel); [about.html](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/frontend/about.html)
- The English export shows the same transaction with statuses "Current", "Revised" and "History". Deduplicate and keep the latest version. — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)
- Example: GomSpace Group AB has 148 transactions (2018–2026), including 21 corrections and 14 cancelled records. Recommended practice is to filter `Status == "Aktuell"`. — [nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)

**Latency, thresholds and history depth**
- A PDMR must report no later than three business days after the transaction date. Since **4 Dec 2024** (Listing Act, Regulation (EU) 2024/2809) the threshold is **EUR 20,000 per calendar year per issuer** (previously EUR 5,000), and the transaction that crosses the threshold is included. — [FI Q&A insynshandel 2024-12-04](https://www.fi.se/contentassets/ee10c244dd51477ab830b5f235274acc/2024-12-04-fragor-och-svar-insynshandel.pdf) (via search summary); [FI Insynshandel](https://www.fi.se/sv/marknad/investerare/insynshandel/)
- Information reported to FI goes into FI's market register and transactions are **published automatically**. — [FI Insynshandel (rapportering)](https://www.fi.se/sv/marknad/rapportering2/insynshandel/) (via search summary)
- Publication latency: rows appear "directly on e-ID-authenticated notification (no delay documented)". A 2-day window (27–28 Aug 2026) held 115 rows, and the register held **166,978 records** on 28 Aug 2026. — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)
- MAR took effect on **3 July 2016**; queries before that date return zero rows. — [nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)
- Insynshandel's production schedule is hourly weekday ingests plus nightly gap-filling via GitHub Actions. — [Insynshandel README](https://github.com/ErikMalmgren/Insynshandel)
- A legacy pre-MAR register (`insynsok.fi.se`) was targeted by an older Python library (BSD licence, "under development"). — [djonsson/insynsregistret](https://github.com/djonsson/insynsregistret)
- ESAP (the EU single access point) will carry MAR data (insider transactions) **at the earliest from 10 Jan 2028 (phase 2)**. — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)

**Licence, ToS and personal data**
- FI's information is free to use and reuse without special permission or agreement, on condition that FI is cited as the source along with the date (PSI-directive framing). The insider register is public. — [FI Öppen data](https://www.fi.se/sv/om-fi/om-webbplatsen/oppen-data/); [FI Insynsregistret](https://www.fi.se/sv/vara-register/insynsregistret/) (via search summaries)
- civictechsweden republishes the full register as `data/insynsregistret.csv` (~41 MB, ~166k+ rows) under **CC0 1.0**; its code is AGPL-3.0. It updates nightly at 01:00 UTC through GitHub Actions (`uv run run.py --full` rebuilds from July 2016). — [civictechsweden/oppna-insynsregistret](https://github.com/civictechsweden/oppna-insynsregistret)
- The commit log shows daily "Update insider trading data" commits through **1 Oct 2026** (checked 2 Oct 2026). — [commits page](https://github.com/civictechsweden/oppna-insynsregistret/commits/main) (**third-party verified 2026-10-01**). My WebFetch of the raw CSV failed on the tool's 10 MB size limit, not on a network block.
- Insynshandel deliberately has **no person index or name search and builds no personal profiles**, and states it is "not an official publication". — [about.html](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/frontend/about.html)

**Other Swedish trackers (secondary)**
- Insynshandel (insyn.malmgren.dev) converts values to SEK at the Riksbank rate of the transaction date and aggregates over 30d/90d/365d/YTD/all windows. — [Insynshandel README](https://github.com/ErikMalmgren/Insynshandel)
- Commercial or free list sites (details unverified): [tradevenue.se/insynshandel](https://tradevenue.se/insynshandel), [borskollen.se/insynshandel](https://www.borskollen.se/insynshandel), [insynshandel.com](https://insynshandel.com/about).
- Nasdaq's former insider list at `nasdaqomxnordic.com/Insider` now redirects to `nasdaq.com/european-market-activity` and contains no insider table. Nasdaq refers users to the national competent authority. — [hankkontakt reconciliation, 28 Aug 2026](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md) (**discontinued; observed 2026-08-28**)

**Source cards**
- **FI Insynsregistret (direct)**
  - Owner: Finansinspektionen. Access: undocumented CSV export over HTTP GET, no authentication.
  - Endpoint: as above. Fields: the 22 columns. History: July 2016 to today.
  - Latency: minutes after the PDMR files, which must happen within 3 business days of the trade.
  - Cost: free. Licence: free reuse with attribution.
  - Tags: [ST][LT]. Status: third-party verified 2026-08-28.
- **civictechsweden mirror**
  - Owner: Civic Tech Sweden. Access: CSV on GitHub (raw.githubusercontent.com), nightly.
  - Licence: CC0. Cost: free.
  - Tags: [LT], and [ST] only as a backfill because it lags by about a day. Status: third-party verified 2026-10-01.

### Inferences
- Collector design for the app: query `button=export` by **publication date**, in small windows (1–3 days for the incremental run), with bisection when the 1,000-row cap is hit.
  - Decode UTF-16LE, then normalise decimal commas and `\xa0`.
  - Upsert on a hash of the 22 fields, keep the newest `Status`, and drop `Makulerad`/"History" rows from signals.
  - Re-scan the last 90 days nightly to pick up revisions. This copies the Insynshandel cadence.
- Use `Publiceringsdatum` (which has a time) as the signal timestamp, never `Transaktionsdatum`, to avoid look-ahead.
- **Structural break on 4 Dec 2024.** Raising the threshold from EUR 5k to 20k removes small trades, so trade counts before and after that date are not comparable. Normalise, or require a minimum value (for example EUR 20k cumulative) across the whole history.
- The register covers issuers whose PDMRs notify FI, i.e. Swedish issuers including those on First North, Spotlight and NGM. Foreign issuers listed in Stockholm report to their home regulator. This scope is inferred, not verified.
- The GitHub mirror is the most robust free path from this environment. Use FI direct only once the user allows `marknadssok.fi.se`.

### Gaps
- Not verified first-hand on 2026-10-02 (curl denied; marknadssok.fi.se blocked for WebFetch). Status vocabulary needs a first-hand check: Swedish `Aktuell/Reviderad/Makulerad` versus English `Current/Revised/History`.
- Not checked: whether `Page=` has any effect on the export, and the exact `Karaktär` vocabulary in the English export.
- FI's exact Öppen data licence wording was not read (fi.se blocked); the attribution requirement comes from a search summary.
- No measured distribution of `Publiceringsdatum − Transaktionsdatum`. The app should compute it from the data.
- The CSV has no post-trade holding column. Cumulative holdings must be reconstructed or sourced elsewhere.

## 2. Norway: where PDMR ("primærinnsider") notifications are published since MAR (1 March 2021), APIs, parsing, and Euronext changes

### Takeaway
No Norwegian structured register exists. PDMRs report to Finanstilsynet on Altinn form **KRT-1500**, and issuers publish the trade as a stock-exchange notice on **Oslo Børs NewsWeb, category 1102 ("Meldepliktig handel for primærinnsidere" / mandatory notification of trade by primary insiders)**. NewsWeb's undocumented JSON API at **`https://api3.oslo.oslobors.no/v1/newsreader/{list,message,attachment,issuers}`** is what every open-source scraper uses. It still worked on 1 Oct 2026 according to a third-party GitHub Action. Trade details sit in free-text bodies and often in PDF attachments. Every open-source parser found uses regex and silently drops PDF-only, option and incentive-plan notices; no LLM-based parser was found. Tags: **[ST] + [LT]**, but extraction quality is the bottleneck.

### Cited Findings

**Regulatory flow**
- PDMRs and closely associated persons report trades electronically to Finanstilsynet through Altinn form **"KRT-1500 Skjema for melding om transaksjoner utført av personer med ledelsesansvar (primærinnsidere) og deres nærstående"**.
- For 2021, the obligation started once transactions reached EUR 5,000 after 1 March 2021; January–February 2021 trades did not count.
- Issuers have **two days from receiving the notification** to publish it.
- — [Finanstilsynet: Meldeplikt for personer med ledelsesansvar](https://www.finanstilsynet.no/tilsyn/markedsatferd/meldeplikt-for-personer-med-ledelsesansvar/); [Finanstilsynet KRT-1500 page](https://www.finanstilsynet.no/rapportering/fellesrapporteringer/mar-meldeplikt-for-handler-av-personer-med-ledelsesansvar-primarinnsidere-og-deres-narstaende); [BAHR: MAR trer i kraft 1. mars](https://bahr.no/newsletter/mar-trer-i-kraft-1-mars-hva-ma-du-gjore) (via search summaries)
- Threshold conflict: search summaries of Finanstilsynet pages still cite **EUR 5,000**. Finanstilsynet's 2023 news item described the Listing Act simplification for primary-insider reporting as forthcoming. I found no confirmation that Norway has moved to EUR 20,000. — [Finanstilsynet: Endringer i markedsmisbruksforordningen…](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2023/endringer-i-markedsmisbruksforordningen-og-prospektforordningen)
- Historical context: in the 1985–1992 regime studied by Eckbo & Smith, insiders had to report within one month. — [Eckbo & Ødegaard working paper (search summary)](https://www.ecgi.global/sites/default/files/working_papers/documents/eckboodegaardfinal.pdf)

**Publication channel and category**
- Data source is "Oslo Børs NewsWeb, category 1102 — mandatory notifications of trade by primary insiders (MAR Article 19)". — [remebjornatle/innsider README](https://github.com/remebjornatle/innsider)
- Code comment: `1102` = "Meldepliktig handel for primærinnsidere". — [viljarem/InveStock-V1 insider_monitor.py](https://raw.githubusercontent.com/viljarem/InveStock-V1/main/insider_monitor.py)
- NewsWeb pages in 2026 list messages under the category "MELDEPLIKTIG HANDEL FOR PRIMÆRINNSIDERE". — [NewsWeb](https://newsweb.oslobors.no/query.jsp?symbol=NEXT&action=1&languageID=1) (search result)
- Public message URLs have the form `https://newsweb.oslobors.no/message/<messageId>`. — [NicolaiBaklund/SAB data-sources.md](https://raw.githubusercontent.com/NicolaiBaklund/SAB/main/docs/data-sources.md)

**Exact API mechanics (unofficial and undocumented)**
- Base `https://api3.oslo.oslobors.no/v1/newsreader`, with four endpoints:
  - `/list` (GET), parameters `category`, `issuer`, `market`, `messageTitle`, `fromDate`, `toDate` (YYYY-MM-DD).
  - `/message` (GET), parameter `messageId`.
  - `/attachment` (GET), parameters `messageId` and `attachmentId`.
  - `/issuers` (POST), returning `issuerId`, `name`, `issuerSign`, `isActive`.
  - — [kennyng90/bjelle-ai newsweb.ts](https://raw.githubusercontent.com/kennyng90/bjelle-ai/main/apps/workers/src/source/newsweb.ts)
- List fields: `messageId`, `title`, `publishedTime`, `issuerId`, `issuerName`, `issuerSign`, `markets`, `category`, `correctionForMessageId`, `correctedByMessageId`, `numbAttachments`. The message endpoint adds `body` and `attachments[{id,name}]`. — [bjelle-ai newsweb.ts](https://raw.githubusercontent.com/kennyng90/bjelle-ai/main/apps/workers/src/source/newsweb.ts)
- Response shape is `data.messages[]`, with `publishedTime` in ISO 8601 ending in "Z"; message detail is `data.message.body` and `data.message.attachments[]`. The API base can be discovered from `https://newsweb.oslobors.no/urls.json` (field `api_large`). viljarem calls the API with **POST** and `Accept`/`Content-Type: application/json`. — [viljarem insider_monitor.py](https://raw.githubusercontent.com/viljarem/InveStock-V1/main/insider_monitor.py)
- innsider calls `GET /v1/newsreader/list?category=1102&fromDate=…&toDate=…` with the header `Origin: https://newsweb.oslobors.no`, then `GET /v1/newsreader/message?messageId=…`. — [innsider insider_lib.py](https://raw.githubusercontent.com/remebjornatle/innsider/main/insider_lib.py)
- Wide date ranges return an **`overflow` flag**, which innsider does not handle ("could truncate results"). — [innsider CLAUDE.md](https://raw.githubusercontent.com/remebjornatle/innsider/main/CLAUDE.md)
- SAB paginates by "date range bisecting on overflow" and uses `issuer=<numeric id>`. — [SAB data-sources.md](https://raw.githubusercontent.com/NicolaiBaklund/SAB/main/docs/data-sources.md)
- Category items carry `id` and `category_no`. STB reports that "issuer-filteret i API-et virker ikke" (the issuer filter does not work), so it filters `issuerId` client-side, using 14 chunks of about 23 days. This **conflicts with SAB**, which uses `issuer=`. — [Sindre31/STB update-data.mjs](https://raw.githubusercontent.com/Sindre31/STB/HEAD/scripts/update-data.mjs)
- `market=XOSL` restricts results to the main market and excludes Euronext Growth and Expand; one project POSTs with an empty JSON body. — [disclosure-automation endpoint scan](https://raw.githubusercontent.com/suam4597-ship-it/disclosure-automation/main/apps/backend/disclosure_api/docs/globalpulse_eu_listed_company_disclosure_endpoint_scan.md)
- Another project POSTs to `/list` with an empty body to get the maximum `messageId`, then walks IDs with `GET /message` at a 0.15 s delay. It ingests only categories 1001, 1002 and 1104, not 1102. — [AIDataNordic newsweb_ingest2.py](https://raw.githubusercontent.com/AIDataNordic/nordic_financial_mcp/HEAD/newsweb_ingest2.py)
- **Liveness: third-party verified 2026-10-01.**
  - innsider's GitHub-Actions output `docs/data.json` has `generated_at` "2026-10-01T13:58:18Z", covers 2026-07-03 to 2026-10-01 and contains **146 parsed trades**.
  - Its top-level keys are `from_date, to_date, total_parsed, total_buy_value, total_sell_value, buys, sells, trades, generated_at`.
  - Sample row: `{"messageId": 683363, "ticker": "NOFIN", "company": "Nordic Financials ASA", "date": "2026-09-30", "action": "buy", "shares": 18181, "price": 1.33, "value": 24181, "insider": "Svend Egil Larsen"}`. Another row has `"insider": null`.
  - — [innsider docs/data.json](https://raw.githubusercontent.com/remebjornatle/innsider/main/docs/data.json)
- An archive shows message 681723 (2026-09-07) fetched via `https://api3.oslo.oslobors.no/v1/newsreader/message?messageId=681723`. Its body only says "Please see attachment on www.newsweb.no". — [SkeieDK/finance-archive NHY.OL 2026-09](https://raw.githubusercontent.com/SkeieDK/finance-archive/HEAD/narrative/NHY.OL/2026-09.json)

**Free text and PDFs: how projects parse them**
- "Trade details (action, shares, price) live in a free-text `body` field"; there is no structured trade API.
- PDF-only announcements, option exercises, corrections, LTI/incentive allocation tables and unusual formats are "silently skipped".
- Numbers mix English (`1,234,567.89`) and Norwegian (`1.234.567,89`) formats. Norwegian/English twin notices are de-duplicated by skipping the Norwegian body when an English twin exists. Same-day internal transfers between related insiders are not de-duplicated.
- Insider-name extraction succeeds about **75%** of the time.
- — [innsider CLAUDE.md](https://raw.githubusercontent.com/remebjornatle/innsider/main/CLAUDE.md)
- innsider uses language-specific regexes: English "bought/purchased/acquired … at/for … NOK"; Norwegian "… aksjer … kjøpt/ervervet … snittpris/kurs/pris … NOK/kr". It also uses a heuristic to tell decimal commas from thousands separators. — [innsider insider_lib.py](https://raw.githubusercontent.com/remebjornatle/innsider/main/insider_lib.py)
- STB's regexes:
  - action: `\b(kjøpt|ervervet|tegnet|solgt|avhendet)\b`
  - shares: `(?:kjøpt|…|avhendet)\s+(\d[\d ]*)\s+aksjer`
  - price: `kurs(?:\s*(?:på|NOK))?…`
  - role: `(konsernsjef|konserndirektør|styreleder|styremedlem|finansdirektør|primærinnsider)`
  - corrections containing "inkurie" or "korreksjon" are dropped.
  - — [STB update-data.mjs](https://raw.githubusercontent.com/Sindre31/STB/HEAD/scripts/update-data.mjs)
- viljarem classifies buy or sell from **title keywords** only ("salg/solgt/sale/disposal" versus "kjøp/purchase/acquisition/tildel/award") and defaults to "ukjent" (unknown). It has no PDF handling and no LLM. — [viljarem insider_monitor.py](https://raw.githubusercontent.com/viljarem/InveStock-V1/main/insider_monitor.py)
- SAB downloads attachments, which are typically PDFs, through `/attachment` and merges body and attachments into Markdown. — [SAB data-sources.md](https://raw.githubusercontent.com/NicolaiBaklund/SAB/main/docs/data-sources.md)

**Euronext rebranding and migration (2024–2026)**
- The marketplace is now branded "Euronext Oslo Børs" (for example, "Moreld overført til Euronext Oslo Børs"). — [Euronext press release](https://www.euronext.com/en/about/media/euronext-press-releases/moreld-lists-euronext-oslo-bors)
- Trading migrated to Euronext's Optiq platform; cash markets went live on 9 November according to the snippet, which does not show the year. — [The TRADE](https://www.thetradenews.com/oslo-bors-migration-euronext-optiq-platform-set-complete-end-year/)
- Listed-company news "are displayed on the NewsWeb website and is updated immediately, 24/7". Publication runs through the Oslo Børs publication service / EuroStockNews. — [Euronext Oslo Børs publication service](https://www.euronext.com/en/corporate-services/oslo-bors-publication-service); [EuroStockNews](https://www.corporatesolutions.euronext.com/products/eurostocknews)
- Supervisory tasks moved from Oslo Børs to Finanstilsynet on **1 April 2025** (title of a law-firm newsletter; content not read). — [BAHR newsletter](https://bahr.no/newsletter/finans-overforing-av-tilsynsoppgaver-fra-oslo-bors-til-finanstilsynet-1-april-2025)
- Despite the rebrand, open-source clients active in Sept–Oct 2026 still call `api3.oslo.oslobors.no` and `newsweb.oslobors.no`. — [innsider data.json](https://raw.githubusercontent.com/remebjornatle/innsider/main/docs/data.json); [SkeieDK archive](https://raw.githubusercontent.com/SkeieDK/finance-archive/HEAD/narrative/NHY.OL/2026-09.json)
- One portfolio engine notes that "Oslo/Euronext lacks a stable public JSON news endpoint here" and degrades to zero hits. That reflects its own design choice, not the absence of api3. — [Dividend-Lab nordic-primary-sources.ts](https://raw.githubusercontent.com/Nils-henrik/Dividend-Lab/main/lib/model-portfolios/engine/nordic-primary-sources.ts)

**Norwegian trackers**
- innsider: a free GitHub Pages dashboard refreshed daily. It ranks by value, by liquidity (% of daily volume) and by distinct insiders, over 7, 30, 90 and 180 days. — [innsider README](https://github.com/remebjornatle/innsider)
- Investtech's paid "Insider barometer" covers Oslo Børs; details are unverified. — [Investtech Insider barometer](https://www.investtech.com/main/market.php?MarketID=1&product=60)

**Source card: NewsWeb category 1102**
- Owner: Euronext Oslo Børs. Access: unofficial JSON API (GET or POST observed), no authentication, CORS `Origin` header used.
- Fields: message metadata plus free-text body and attachments, with correction links. History: the category predates MAR (depth not verified).
- Latency: real time, 24/7. Cost: free. ToS: no published API terms found.
- Tags: [ST][LT]. Status: third-party verified 2026-10-01.

### Inferences
- Recommended NewsWeb pipeline:
  - **Poll** `list?category=1102&fromDate=D-2&toDate=D` every 5–15 minutes in market hours (hourly otherwise), and bisect when `overflow` is returned.
  - **Fetch** `message`; when the body is short or references an attachment, fetch `/attachment` (PDF to text).
  - **Extract** with a regex fast path plus **LLM extraction**, using a JSON schema that mirrors the MAR notification template: name, position, closely-associated flag, issuer, ISIN, nature, price, volume, date, venue, and holdings after the trade if stated.
  - **Gate** with a confidence score and a "needs review" queue.
  - **Collapse** NO/EN twins and handle `correctionForMessageId`/`correctedByMessageId`.
- The regex-only parse rate is evidently low: 146 trades over 90 days from the whole Norwegian market, with options, LTI and PDF notices dropped. A Norwegian signal built only from regex output will be biased toward simple open-market notices.
- Because the issuer filter may be unreliable, pull by category and date range and filter client-side.
- Norway's 2021 data started at a EUR 5k threshold. If Norway adopts the Listing Act's EUR 20k, expect the same structural break as Sweden.

### Gaps
- Not verified first-hand (curl denied): exact current response JSON, the `overflow` semantics, whether GET or POST is the canonical method for `/list`, and whether `issuer=` works.
- How far back category 1102 history goes, and what the category held under the pre-2021 Norwegian rules. I recall pre-MAR primary insiders reported to Oslo Børs and notices were published on NewsWeb, but this is unverified.
- Whether Finanstilsynet publishes any structured PDMR dataset: none was found; only the Altinn reporting form.
- Whether Norway has incorporated the Listing Act changes (EUR 20k threshold) and from what date.
- NewsWeb/api3 terms of use for automated collection.
- No open-source LLM-based parser for 1102 notices was found: a GitHub code search for "newsweb oslobors insider openai extract" returned 0 results on 2 Oct 2026.

## 3. Denmark and Finland (secondary markets, brief)

### Takeaway
Neither country has a public structured PDMR register. PDMRs report to the regulator, but those reports are not published. Issuers publish "Managers' transactions" company announcements, mainly through **Nasdaq Copenhagen and Nasdaq Helsinki**. These are reachable through Nasdaq's unofficial news API (`api.news.eu.nasdaq.com/news/query.action?...&cnscategory=Managers' Transactions`) and, for Denmark, as archived company announcements in the Danish FSA's OAM. Both countries apply the post-Listing Act **EUR 20,000** threshold and the **2-business-day** issuer publication rule. Tags: **[LT]** mainly; **[ST]** is possible through the Nasdaq API.

### Cited Findings
- **Denmark: rules**
  - PDMR transactions must be reported to Finanstilsynet within three working days. The issuer must publish within **two working days after receiving the notification**. The reporting obligation arises at **EUR 20,000** per calendar year.
  - OAM holds publicly available company announcements, but **reports from major shareholders and leading employees are not publicly available in OAM**.
  - — [Finanstilsynet DK: MAR for ledende medarbejdere](https://www.finanstilsynet.dk/finansielle-temaer/kapitalmarked/mar-for-ledende-medarbejdere); [Søg indberetning / selskabsmeddelelser](https://www.finanstilsynet.dk/finansielle-temaer/kapitalmarked/selskabsmeddelelser); [Hvilke meddelelser skal indberettes i OAM](https://www.finanstilsynet.dk/nyheder-og-presse/nyheder-og-pressemeddelelser/2022/jun/indberetningoam) (via search summaries)
- **Denmark: OAM search API** (unofficial; unverified by me)
  - Request: `POST https://appft.gold.extension.gopublic.dk/api/9217fa13-5d9a-46c6-9921-69ee7e6cfaf6/search` with body `{"query":"","page":1,"pageSize":25,"sorting":{"key":"PublicationDateColumn","direction":"descending"},"filters":[{"type":"dropdown","key":"CategoryFilter","options":[...]}]}`.
  - Category options include `YearlyFinancialReport, HalfYearlyFinancialReport, InsideInformation, OwnShares, RelatedPartyTransactions, TakeoverBid, TotalVotingRightsAndShareCapital, Prospectus` and others; `ShortSelling` exists but was excluded.
  - Response fields: `paging.totalCount` and `data.rows[].{id, HeadlineColumn, IssuerColumn, CategoryColumn, PublicationDateColumn}`. Details are at `/details/{id}`.
  - The project reports a "staging live poll pass".
  - — [disclosure-automation DK OAM notes](https://raw.githubusercontent.com/suam4597-ship-it/disclosure-automation/main/apps/backend/disclosure_api/docs/globalpulse_denmark_dfsa_oam_company_announcements_candidate_notes.md); [endpoint scan](https://raw.githubusercontent.com/suam4597-ship-it/disclosure-automation/main/apps/backend/disclosure_api/docs/globalpulse_eu_listed_company_disclosure_endpoint_scan.md)
  - Another audit concludes Danish PDMR reports are "INTE offentligt tillgängliga i OAM" (not publicly available in OAM). — [hankkontakt nordic-data-landscape](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/nordic-data-landscape.md)
- **Finland: rules**
  - FIN-FSA follows the EUR 20,000 threshold under MAR 19(8). PDMRs notify the company and FIN-FSA within three business days. The company publishes within **two business days of receiving the notification**, usually as a stock-exchange release ("Johdon liiketoimet" / Managers' transactions).
  - — [Nasdaq Helsinki insider guidelines, in force 4 Dec 2024](https://www.nasdaq.com/docs/2024/12/03/P%C3%B6rssin_sis%C3%A4piiriohje_4.12.2024.pdf) (via search summary)
  - A FIN-FSA page exists at `https://www.finanssivalvonta.fi/en/capital-markets/issuers-and-investors/managers-transactions/` (content unverified). — [aksje-app nordic_market_sources.py](https://raw.githubusercontent.com/aksje-app/aksje-app/main/nordic_market_sources.py)
- **Nasdaq Nordic news API**, covering Helsinki and Copenhagen (and Stockholm) announcements (unofficial; unverified by me)
  - Request: `https://api.news.eu.nasdaq.com/news/query.action?type=json&maximumAge=90d&market=Main Market, Helsinki&cnscategory=Managers' Transactions&limit=20&start=<offset>`.
  - Fields used: `results.item[].messageUrl`, `releaseTime`, `company`.
  - Detail pages are HTML and parsed by regex for Name, Position, Issuer, ISIN, Transaction date, Nature (ACQUISITION/DISPOSAL) and volume/price (aggregated VWAP), with blocks split on `_{10,}`.
  - The project waits 0.5 s between detail pages and 1.0 s between batches, with at most 10 pages per run. No PDF or LLM handling.
  - — [freducom/bloomvalley nasdaq_nordic_insider.py](https://raw.githubusercontent.com/freducom/bloomvalley/HEAD/backend/app/pipelines/nasdaq_nordic_insider.py)
  - Full parameter template seen in another client: `showAttachments=true&showCnsSpecific=true&showCompany=true&callback=handleResponse&countResults=false&freeText=&market=Main%20Market%2C+Helsinki&cnscategory=&company=&fromDate=&toDate=&globalGroup=exchangeNotice&globalName=NordicMainMarkets&displayLanguage=fi&timeZone=CET&dateMask=yyyy-MM-dd+HH%3Amm%3Ass&limit=20&dir=DESC&start=`. For First North it uses `market=First North Finland` and `globalName=NordicFirstNorth`. With `callback=handleResponse` the response is JSONP. — [etsubu/StonksBot NasdaqNordicDisclosures.java](https://raw.githubusercontent.com/etsubu/StonksBot/HEAD/src/main/java/com/etsubu/stonksbot/scheduler/omxnordic/NasdaqNordicDisclosures.java)
  - Attachments come from `attachment.news.eu.nasdaq.com`. Responses are cached for 1 hour. — [Dividend-Lab nordic-primary-sources.ts](https://raw.githubusercontent.com/Nils-henrik/Dividend-Lab/main/lib/model-portfolios/engine/nordic-primary-sources.ts)
- **Discontinued:** Nasdaq's insider table at `nasdaqomxnordic.com/Insider` is gone (redirect observed 28 Aug 2026). — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)

### Inferences
- For Danish and Finnish Nordnet-tradable shares, the practical free source is the Nasdaq news API, filtered on CNS category "Managers' Transactions" and on market values "Main Market, Copenhagen", "Main Market, Helsinki", "First North Denmark" and "First North Finland". The Copenhagen and Denmark market strings are inferred by analogy. Notices follow the MAR template, so they parse more consistently than Norwegian free text.
- Danish OAM is a useful archive and backfill source but probably not a latency-optimal feed.

### Gaps
- None of the Nasdaq API parameters were verified live; the exact Copenhagen market strings and CNS category spelling are unconfirmed.
- Not established whether OAM has a dedicated managers'-transactions category (none appears in the filter list captured), and whether Danish PDMR announcements are filed under another category.
- The content of FIN-FSA's managers'-transactions page, and what replaced Finland's pre-2016 public insider register, are unknown.
- No information on Nasdaq news API terms of use for automated collection.

## 4. Third-party aggregators, APIs and paid feeds (cost, coverage, latency, ToS)

### Takeaway
Only **Börsdata** offers a documented, keyed REST endpoint for Nordic insider transactions (`/v1/holdings/insider`, Pro+ tier, Nordic only, about 10 years of history). Everything else found is either a website to scrape (insiderscreener, Swedish list sites, Investtech, broker pages) or an enterprise feed whose 2026 terms could not be verified. Because FI and NewsWeb are free and primary, the app should use them as the backbone, with Börsdata as an optional, cleaner cross-check for SE/NO/DK/FI. Tags: Börsdata **[LT]** (batch); scraped sites **[LT]** (monitoring only).

### Cited Findings
- **Börsdata (Sweden)**
  - Endpoints: `GET https://apiservice.borsdata.se/v1/holdings/insider?authKey=KEY&instList=97,3,6` (max 50 instruments), plus `/v1/holdings/shorts` and `/v1/holdings/buyback`. Insider data spans about 10 years, Nordic companies only, Pro+ members only. — [Börsdata API wiki: Holdings](https://github.com/Borsdata-Sweden/API/wiki/Holdings)
  - Response schema: `HoldingsInsiderTableArrayRespV1.list[]` → `{insId, values: InsiderRowV1[], error}`. Each `InsiderRowV1` has `misc` (bool), `ownerName`, `ownerPosition`, `equityProgram` (bool), `shares` (int64), `price`, `amount`, `currency`, `transactionType` (int32), `verificationDate` and `transactionDate` (date-times). — [Börsdata swagger.json (copy in emmanuelay/borsdata-mcp)](https://raw.githubusercontent.com/emmanuelay/borsdata-mcp/HEAD/client/assets/swagger.json)
  - Authentication is a query-string `authKey` (case-sensitive). Rate limit is 100 calls per 10 s (HTTP 429 when exceeded), and staying under 10k calls per day is recommended.
  - The REST API moved from PRO to PRO+; **from 1 Feb 2025, new PRO memberships cannot call the REST API**. Holdings endpoints were added on 2023-09-14.
  - — [Borsdata-Sweden/API README](https://github.com/Borsdata-Sweden/API); [wiki](https://github.com/Borsdata-Sweden/API/wiki)
  - Price: "59 EUR/month" for API access according to a third-party audit; unverified, so check borsdata.se. — [hankkontakt nordic-data-landscape](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/nordic-data-landscape.md)
  - Update frequency is not specified in the documentation. — [Holdings wiki](https://github.com/Borsdata-Sweden/API/wiki/Holdings)
- **insiderscreener.com**
  - Company pages `https://www.insiderscreener.com/en/company/[slug]` and an "explore" page for **Nordic Markets**. Fields: notification date, transaction date, type, insider name/position/role, shares, price, value; multi-currency (SEK, DKK, EUR, …).
  - "No official API". The scraper claims to respect robots.txt.
  - — [Goran1310/insiderscreener README](https://raw.githubusercontent.com/Goran1310/insiderscreener/HEAD/README.md)
- **Finnhub** is used as an insider-trade fallback ("Insynshandel via Finnhub API"), and was suggested as an independent cross-check for FI. Its Nordic coverage is unverified. — [hankkontakt system-ai-2026-09-01](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/docs/archive/system-ai-2026-09-01.md); [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)
- **Investtech** sells an "Insider barometer" for Oslo Børs (paid; method unverified). — [Investtech](https://www.investtech.com/main/market.php?MarketID=1&product=60)
- **Swedish list sites** (free web pages, presumably FI-derived, scraping terms unknown): [tradevenue.se](https://tradevenue.se/insynshandel), [borskollen.se](https://www.borskollen.se/insynshandel), [insynshandel.com](https://insynshandel.com/about).
- **Practitioner note:** a "2iQ composite" (2iQ Research) is cited for conviction-bucket returns (top bucket about +20% 12-month excess return). This is secondary and unverified, but it confirms 2iQ as a European insider-data vendor. — [rspiegelberg directors-dealings research notes](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)
- **Nasdaq Nordic's own insider list was discontinued**: the page redirects and has no insider table (observed 28 Aug 2026). — [hankkontakt reconciliation](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/.opencode/audit/insider-reconciliation-2026-08-28.md)

### Inferences
- Börsdata exposes `equityProgram` and `transactionType`, which helps exclude incentive-programme awards. It is worth evaluating for SE, DK and FI, and especially for **Norway**, where it may already have structured what NewsWeb only offers as free text. Verify Norwegian coverage and latency with a trial before relying on it.
- Broker pages (Avanza/Placera, Nordnet) and media lists (Finansavisen, Placera, MarketScreener) are UI-only. Scraping them adds ToS risk and no data beyond FI and NewsWeb. Avoid them except for manual spot checks.
- **GDPR (inference, not legal advice).** PDMR names are personal data, published under MAR's legal obligation. A purely personal app is plausibly within the GDPR household exemption, but minimise anyway: store a salted hash of the insider identity plus role class, keep names out of logs, and do not build person profiles. That follows the Insynshandel design of no person index.

### Gaps
- Not found or verified (WebSearch budget exhausted; vendor domains not reachable): 2026 pricing, coverage, latency and ToS for Avanza/Placera insider lists, Nordnet insider pages (www.nordnet.se blocked here), Modular Finance (Holdings/Monitor), MarketScreener, Inderes, Finansavisen's "innsidehandel" lists, Infront, LSEG/Refinitiv, FactSet and 2iQ.
- Börsdata's actual 2026 price and the `transactionType` code list (integer enum) were not obtained.
- No authoritative GDPR guidance specific to re-hosting PDMR names was retrieved.

## 5. Evidence: do insider trades predict returns in Nordic markets and internationally (characteristics, horizon, magnitude, decay, MAR era, costs)?

### Takeaway
Internationally, the robust result is that **insider purchases, not sales, predict returns**. The effect is concentrated in **small firms** and in **non-routine ("opportunistic") trades**, with value-weighted alphas of about 0.8–1%+ per month for the best-filtered subsets. Much of the effect accrues within the first weeks after a trade. The Nordic evidence is thinner and weaker:
- **Norway:** the classic Oslo study found zero or negative insider performance (1985–1992).
- **Finland:** post-purchase abnormal returns are small and short-lived (about 0.25% over 5 days in 2005–2010).
- **Sweden:** studies emphasise non-informational motives, and only some insiders' sales are informative.

Treat Nordic insider buying as a **modest, conditional tilt**, not a stand-alone alpha source, and validate it with the app's own logs.

### Cited Findings

**Nordic evidence**
- **Norway (Eckbo & Smith, JF 1998, 53(2))**: "Using three alternative performance estimators in a time-varying expected return setting, we document **zero or negative abnormal performance** by insiders… robust to a variety of trade characteristics." The setting was the "closely held" Oslo Stock Exchange in a period of lax enforcement. The average OSE mutual fund outperformed the insider portfolio. — [JF 53(2) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2053/Volume%2053%20-%20Issue%202.md). The sample period was 1985–1992, with a 1-month reporting rule. — [Eckbo & Ødegaard WP (search summary)](https://www.ecgi.global/sites/default/files/working_papers/documents/eckboodegaardfinal.pdf)
- **Norway, later work**: Eckbo & Ødegaard, "Insider trading and gender" (NHH WP, Oct 2019) and "Board gender-balancing and insider trading performance" (ECGI WP) study Oslo insider-trading performance; their numbers could not be read (blocked). — [NHH WP](https://www.nhh.no/contentassets/c40debc00fba4bd38c12b7e1b00f49c7/inside_paper_2019_10.pdf); [ECGI WP](https://www.ecgi.global/sites/default/files/working_papers/documents/eckboodegaardfinal.pdf)
- **Sweden (Kallunki, Nilsson & Hellström, JAE 2009)**: insiders' "portfolio rebalancing objectives, tax considerations and behavioral biases play the most important role in their trading decisions". Insiders with a large share of wealth in insider stock **sell more before bad-news earnings**. — [SSRN 1426899](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1426899) (via search summary)
- **Sweden (Kallunki, Kallunki, Nilsson & Puhakka, JFE 2018, 130(1))**: on Swedish archival data, "**less wealthy insiders are more likely to time their insider selling, and to sell in greater magnitudes, prior to abnormal price declines**", especially those with lower risk aversion as measured by criminal behaviour. The paper notes "the surprisingly small average insider returns reported in the literature". — [JFE 130(1) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JFE/Volume%20130/Volume%20130%20-%20Issue%201.md)
- **Finland (Aalto thesis, Nasdaq OMX Helsinki, 1 Jul 2005 – 28 Feb 2010)**: 114 firms, 2,569 purchase days and 2,018 sale days. Insiders earned significant abnormal returns, but for the overall sample, post-transaction CARs were **significant only for the first five days after purchases, at 0.25%**. — [Aaltodoc 123456789/499](https://aaltodoc.aalto.fi/handle/123456789/499) (via search summary)
- **Finland, MAR era (Turku thesis, Helsinki 2022–2023)**: CEO purchases produced the highest positive CAAR in **large** companies. **Small** companies had higher average abnormal returns, and large companies had negative average returns. — [UTUPub 10024/177414](https://www.utupub.fi/handle/10024/177414) (via search summary)
- **Finland, COVID (Turku thesis, 2024)**: insider purchases peaked during the 2020 crash, but abnormal returns after purchases were significantly lower during the crisis. — [Ruska 2024](https://www.utupub.fi/bitstream/10024/177881/1/Masters_thesis_Henrik_Ruska_15_5_2024.pdf) (via search summary)
- **Sweden, theses (content not readable)**: SSE "Abnormal Returns in Insider Trading", "Insider trading on the Stockholm Stock Exchange" and "The Effect of Regulation Changes in the Swedish Insider…"; Lund "Insider trading by Swedish CEOs". — [SSE 3339](http://arc.hhs.se/download.aspx?MediumId=3339); [SSE 165](http://arc.hhs.se/download.aspx?MediumId=165); [SSE 1018](http://arc.hhs.se/download.aspx?MediumId=1018); [Lund](https://lup.lub.lu.se/student-papers/record/9095485/file/9095491.pdf)

**European and cross-country evidence**
- **Fidrmuc, Korczak & Korczak (JBF 2013)**: more than 240,000 insider transactions in **15 European countries and the US**. "Abnormal returns after insider transactions are **positively correlated with country-level shareholder protection**". Protection strengthens the reaction to purchases and weakens the negative signal from sales. — [JBF abstract (TOC dump)](https://raw.githubusercontent.com/fagan2888/zhanghaitao1.github.io/HEAD/JBF_7.xml)
- **Fidrmuc, Goergen & Renneboog (JF 2006, UK)**: faster reporting in the UK may explain larger UK abnormal returns. Director and outside ownership matter, and "it is important to adjust for news released before directors' trades": trades preceded by M&A news or CEO replacements contain significantly less information. — [JF 61(6) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2061/Volume%2061%20-%20Issue%206.md)
- **UK, costs (secondary)**: Friederich, Gregory, Matatko & Tonks (2002) find directors' buy alpha is "positive gross but ~zero net of spread". MAR closed periods shift buying to the first window *after* results. — [rspiegelberg notes](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)

**US and international core results**
- **Seyhun (JFE 1986)**: about 60,000 transactions (1975–1981). The paper investigates whether outsiders can earn abnormal profits by reading the Official Summary, insiders' profitability, what drives insiders' predictive ability, and trading costs. — [JFE 16(2) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JFE/Volume%2016/Volume%2016%20-%20Issue%202.md)
- **Lakonishok & Lee (RFS 2001)**: NYSE, AMEX and Nasdaq stocks, 1975–1995.
  - "Very little market movement is observed when insiders trade and when they report their trades."
  - Insiders are contrarian and predict market movements.
  - Cross-sectional predictability "is driven by insider's ability to predict returns in **smaller firms**".
  - "Informativeness… is coming from **purchases**, while insider selling appears to have no predictive ability."
  - — [RFS 14(1) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/RFS/Volume%2014/Volume%2014%20-%20Issue%201.md)
  - Secondary magnitude claims: "heavy insider buying beats the market roughly 6% over 12 months" ([eBull notes](https://raw.githubusercontent.com/Luke-Bradford/eBull/HEAD/.claude/skills/quant/strategy-evidence.md)); "+0.5–0.7% monthly" ([rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)).
- **Cohen, Malloy & Pomorski (JF 2012, 67(3))**:
  - Strategy on "opportunistic" traders: "**value-weighted abnormal returns of 82 basis points per month**, while abnormal returns associated with routine traders are **essentially zero**".
  - The most informed are "local, nonexecutive insiders from geographically concentrated, poorly governed firms".
  - — [JF 67(3) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2067/Volume%2067%20-%20Issue%203.md)
  - Routine means trading in the same calendar month for 3 consecutive years, so 3 years of history are needed to classify an insider. — [trailingedge classifier notes](https://raw.githubusercontent.com/caganco/trailingedge/HEAD/docs/stage0/OPPORTUNISTIC_CLASSIFIER.md); [mgmt767 course notes](https://raw.githubusercontent.com/learn-investments/mgmt767/HEAD/docs/04_insider_trading.qmd)
  - Caution: the 82 bps is a long/short factor alpha (data to 2007), not a retail long-only net return. — [boring-alpha audit](https://raw.githubusercontent.com/hao6yu/boring-alpha/HEAD/research/insider-purchase-audit-2026-09-13/RESULTS.md)
- **Ali & Hirshleifer (JFE 2017)**: insiders identified as opportunistic **from their profitable trading before quarterly earnings announcements** generate "monthly four-factor alphas **exceeding 1%**" in a value-weighted strategy. — [JFE 126(3) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JFE/Volume%20126/Volume%20126%20-%20Issue%203.md)
- **Akbas, Jiang & Koch (JF 2020)**, secondary: long-short on short-horizon insiders' recent strong trades earns **2.08%/month**, versus 0.77% for long-horizon insiders. — [mgmt767 course notes](https://raw.githubusercontent.com/learn-investments/mgmt767/HEAD/docs/04_insider_trading.qmd)
- **Ravina & Sapienza (RFS 2010, 23(3))**: **independent directors** "earn positive substantial abnormal returns when they purchase", and differ little from executives at most horizons. Returns are higher in weaker-governance firms, and audit-committee directors outperform. — [RFS 23(3) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/RFS/Volume%2023/Volume%2023%20-%20Issue%203.md)
- **Marin & Olivier (JF 2008)**: "insiders' **sales peak many months before a large drop** in the stock price, while insiders' **purchases peak only the month before a large jump**". The *absence* of selling is informative ("the dog that did not bark"). — [JF 63(5) abstract (TOC dump)](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2063/Volume%2063%20-%20Issue%205.md)
- **Jeng, Metrick & Zeckhauser (RESTAT 2003)**, secondary only and **inconsistent across secondary sources**:
  - purchase alpha reported as "~8% annually" ([ccrjohn8787 notes](https://raw.githubusercontent.com/ccrjohn8787/investing-agent-sdk/HEAD/docs/INSIDER_DATA_EVALUATION.md)) or "~11.2% annualized" ([eBull](https://raw.githubusercontent.com/Luke-Bradford/eBull/HEAD/.claude/skills/quant/strategy-evidence.md));
  - sales show no comparable alpha;
  - decay: about **25% of cumulative alpha within 5 days and about 50% by month-end**, with the rest spread over 6–12 months ([rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)).
  - My recollection of the primary abstract is "more than 6% per year" for purchases, with sales not significant (unverified).
- **Cluster buying**, secondary only:
  - Kang, Kim & Wang (2018): cluster purchases earn **3.8% over 21 days vs 2.0% solo** ([trading-companion scorer](https://raw.githubusercontent.com/alexpayne556-collab/trading-companion-2026/HEAD/src/research/academic_insider_scorer.py)); about +7.4% over 12 months for small-cap clustered purchases ([rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)).
  - Alldredge & Blank (2019): coordinated or cluster buys amplify alpha, more so in smaller, low-coverage stocks; "2.1% monthly abnormal returns for coordinated buys" ([rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md); [trading-companion](https://raw.githubusercontent.com/alexpayne556-collab/trading-companion-2026/HEAD/src/research/academic_insider_scorer.py)).
  - One note gives the journal as JFQA, but I believe it is the *Journal of Financial Research* (unverified).
- **Seniority**, secondary:
  - "Seyhun (1986): CEO/CFO/Chair trades outperform non-executive director signals" ([rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)). This is contested by CMP (non-executives most informed) and Ravina & Sapienza (independent directors ≈ executives).
  - CFO-vs-CEO figures seen in GitHub notes ("21.5% vs 19.3%") have unclear attribution and are not usable. — [trading-companion](https://raw.githubusercontent.com/alexpayne556-collab/trading-companion-2026/HEAD/src/research/academic_insider_scorer.py)

**Transaction costs and implementability**
- A US cost illustration: replacing four $5,000 positions a month with a 10/50 bp per-side execution loss costs about 3.84%/11.52% of $5,000. Entry must follow actual publication and a tradable session (most Form 4s are accepted after 16:00 ET). — [boring-alpha audit](https://raw.githubusercontent.com/hao6yu/boring-alpha/HEAD/research/insider-purchase-audit-2026-09-13/RESULTS.md)
- A recent replication on 47,369 US purchases, mostly 2023 onward, found positive but **statistically insignificant** excess returns: +2.12% at 1 month (t = 0.98), +8.41% at 3 months (t = 1.22), +12.05% at 6 months (t = 1.06), +6.39% at 12 months (t = 0.50). The authors attribute this to only about 4 usable years. They argue the signal is naturally low-turnover. — [eBull strategy-evidence](https://raw.githubusercontent.com/Luke-Bradford/eBull/HEAD/.claude/skills/quant/strategy-evidence.md)
- Practitioner conviction buckets (Dardas / 2iQ, secondary): top bucket about +20% 12-month excess, average buy about 0%, low-conviction buys negative. — [rspiegelberg](https://raw.githubusercontent.com/rspiegelberg-cmd/directors-dealings/HEAD/docs/research/alpha-research-2026-06-10.md)

### Inferences
- **Nordic prior.** Norway's classic result (zero or negative), Finland's short-lived +0.25% over 5 days, and Swedish evidence that much insider trading is non-informational all suggest a weaker *average* signal than in the US. Strong shareholder protection in the Nordics (per Fidrmuc–Korczak–Korczak) suggests that filtered purchases should still carry information. Start with **small weights** and let logged outcomes decide.
- **Horizon.** Decay evidence (about 25% within 5 days, about 50% within a month) and the Finnish 5-day window mean that **[ST]** value is concentrated in the first days after publication. **[LT]** value comes from tilting toward names with filtered net buying over 1–6 (up to 12) months.
- **Sales.** Weight sales near zero as a return predictor, but use **heavy or repeated selling by several insiders** as a risk flag or veto, especially in long-term holdings (Marin & Olivier; Kallunki et al. 2018).
- **Costs.** Many Nordic insider-bought names are small caps with wide spreads. UK evidence that alpha is about zero net of spread suggests **[ST]** use only in liquid names, or as confirmation for an existing setup rather than a stand-alone trade.

### Gaps
- Primary texts of Jeng–Metrick–Zeckhauser (2003), Alldredge & Blank (2019), Kang–Kim–Wang (2018), Wang–Shin–Francis (2012, CFO vs CEO), Scott & Xu (2004, "Some insider sales are positive signals") and Bettis et al. (large-volume trades, costs) were not accessible. Their magnitudes above are secondary or flagged.
- No peer-reviewed **MAR-era (post-2016) Nordic** study with return magnitudes was found. SSE, NHH/BI and CBS theses exist but were unreadable here.
- The Eckbo & Ødegaard results (Norwegian insider-trade performance by gender and board composition) were not obtained.
- Other relevant titles not read: "Are directors' dealings informative? Evidence from European stock markets" (FMPM 2011) ([Springer](https://link.springer.com/article/10.1007/s11408-011-0156-z)); "Is 'Not Trading' Informative?" (FAJ 2022) ([T&F](https://www.tandfonline.com/doi/abs/10.1080/0015198X.2021.1984825)); Eugster et al. 2021, "IQ and corporate insiders' decisions to time insider and outsider trading" ([EFM](https://onlinelibrary.wiley.com/doi/10.1111/eufm.12302)); "Corruption and insider trading" (JCF 2024) ([RePEc](https://ideas.repec.org/a/eee/corfin/v89y2024ics0929119924001160.html)).

## 6. What the app should compute (filters, features, weights) and which sleeve the signal fits

### Takeaway
Build one normalised insider-event table from FI (SE), NewsWeb 1102 (NO) and the Nasdaq "Managers' Transactions" feed (DK/FI). Count only **open-market buys and sells**; exclude awards, option legs, subscriptions, internal transfers, gifts, inheritance, pledges, lending and corrections. Derive per-issuer features:
- net open-market buy value scaled by market cap and liquidity;
- number of distinct buyers over 30 and 90 days;
- opportunistic versus routine status;
- insider role;
- days since publication;
- a pre-trade news check.

Use the result mainly as an **[LT] tilt/confirmation** factor (1–6 months). Use it in **[ST]** only for fresh (≤5 trading days), clustered, liquid buys.

### Cited Findings
- Exclusions supported by data semantics:
  - `Tilldelning` is mostly free awards (54% share programmes, 45% priced at zero).
  - `Teckning` is mostly BTA/BTU interim paper.
  - `Lösen ökning/minskning` are paired option-exercise legs.
  - `Interntransaktion` is an own or related-account transfer.
  - Gifts, inheritance, marital division, pledges and lending involve no discretionary market decision.
  - — [nature_map.csv](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/data/seed/nature_map.csv)
  - FI also flags `Är kopplad till aktieprogram` (linked to a share programme) and `Närstående` (closely associated person). — [fi.py](https://raw.githubusercontent.com/ErikMalmgren/Insynshandel/main/src/insynshandel/sources/fi.py)
  - Börsdata flags `equityProgram`. — [Börsdata swagger](https://raw.githubusercontent.com/emmanuelay/borsdata-mcp/HEAD/client/assets/swagger.json)
- Cluster features used in practice:
  - **≥3 unique insiders buying within 30 calendar days**; `cluster_score = unique_buyers_30d × log1p(total_buy_amount_30d / market_cap) × exec_weight` (1.5× if a CEO, CFO or chair is present); an `EXEC_BUY` flag for C-suite buys in the prior 90 days; routine traders excluded (same person, recurring monthly or annual patterns). — [hankkontakt 03_fi_insider_cluster.md](https://raw.githubusercontent.com/hankkontakt/marketscan/HEAD/docs/plan/03_fi_insider_cluster.md)
  - The same document asserts that "cluster… persistent signal (1–3 months); individual trades only 2–5 day windows". This is a design note, not evidence.
  - innsider ranks by value, by liquidity (trade value as % of daily volume) and by distinct insiders. — [innsider README](https://github.com/remebjornatle/innsider)
  - Insynshandel aggregates over 30d/90d/365d/YTD windows in SEK at the trade-date Riksbank rate, with market-cap percentages. — [Insynshandel README](https://github.com/ErikMalmgren/Insynshandel)
- Opportunistic versus routine needs 3 years of history (same-month trading 3 years in a row). In sparse-disclosure regimes, one adaptation uses ≥3 distinct purchase months with ≥60% in the same calendar month over 36 months. — [trailingedge](https://raw.githubusercontent.com/caganco/trailingedge/HEAD/docs/stage0/OPPORTUNISTIC_CLASSIFIER.md)
- Only about 10% of US purchasing insiders have the history needed for that classification. — [eBull](https://raw.githubusercontent.com/Luke-Bradford/eBull/HEAD/.claude/skills/quant/strategy-evidence.md)
- Evidence anchors for weights:
  - purchases ≫ sales, and small firms are stronger ([Lakonishok & Lee](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/RFS/Volume%2014/Volume%2014%20-%20Issue%201.md));
  - opportunistic ≫ routine ([CMP](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2067/Volume%2067%20-%20Issue%203.md); [Ali & Hirshleifer](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JFE/Volume%20126/Volume%20126%20-%20Issue%203.md));
  - adjust for news before the trade ([Fidrmuc et al. 2006](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/JF/Volume%2061/Volume%2061%20-%20Issue%206.md));
  - independent directors' buys are informative too ([Ravina & Sapienza](https://raw.githubusercontent.com/danielyang1009/light-speed-engine/HEAD/RFS/Volume%2023/Volume%2023%20-%20Issue%203.md));
  - Nordic short-window effect after purchases (+0.25% over 5 days) ([Aalto](https://aaltodoc.aalto.fi/handle/123456789/499)).
- Timing anchor: signal time = publication time. FI `Publiceringsdatum` has a timestamp ([nexus ADR](https://raw.githubusercontent.com/lassemand/nexus/main/docs/adr/0002-fi-pdmr-register-access.md)) and NewsWeb `publishedTime` is in UTC ISO format ([viljarem](https://raw.githubusercontent.com/viljarem/InveStock-V1/main/insider_monitor.py)). Entry only after publication and in a tradable session ([boring-alpha](https://raw.githubusercontent.com/hao6yu/boring-alpha/HEAD/research/insider-purchase-audit-2026-09-13/RESULTS.md)).

### Inferences

**Suggested schema**
- `source, country, issuer_name, issuer_lei, isin, ticker, insider_key (salted hash), role_raw, role_class (CEO/CFO/Chair/ExecOther/Board/Other), closely_associated, nature_raw, nature_class (OPEN_BUY / OPEN_SELL / EXCLUDED: award / option / subscription / internal / gift / pledge / lending / corporate), share_programme_flag, instrument_type, volume, volume_unit, price, currency, value_local, value_sek, value_nok, venue, trade_date, published_at, status, is_correction, message_id_or_url, parse_method (csv / regex / llm), parse_confidence`.

**Features to compute per issuer and day**
- (a) Net open-market buy value over 30d and 90d, scaled by market cap (bps) and by average daily traded value.
- (b) Number of distinct buyers over 30d and 90d (the cluster flag at ≥2 and ≥3), and distinct sellers.
- (c) The largest single buy, in value and as % of market cap.
- (d) Role mix: any CEO, CFO or chair buy; board-only buys.
- (e) Opportunistic flag:
  - Sweden can use FI history back to 2016;
  - Norway's history since 2021 is enough by 2024+;
  - insiders without 3 years of history get "unknown", not "routine".
- (f) Days since publication, with an exponential decay. An [ST] half-life of about 5 trading days and an [LT] half-life of about 60–90 trading days are a starting guess, tuned from logs.
- (g) Pre-trade news flag: an issuer announcement in the prior 5–10 days (takeover/M&A, CEO change, report). Down-weight trades that follow M&A news or a CEO change; flag buys made right after reports, when closed periods end.
- (h) Selling-pressure flag: ≥2 distinct sellers in 90d, or a large sale relative to market cap, used as a risk veto in [LT].
- (i) Post-Dec-2024 threshold normalisation: ignore events under about EUR 20k across the whole history.
- (j) Data-quality weight: down-weight Norwegian LLM or regex extractions below a confidence cut-off; corrections and cancellations override earlier events.

**Not computable from free sources**
- Trade size relative to the insider's prior holding (FI has no holdings column; Norwegian texts sometimes state post-trade holdings, unverified).
- Trade size relative to salary.
- Approximate by trade value relative to market cap and the insider's own past trade sizes.

**Sleeve fit**
- **[LT]**: primary use. A positive tilt for value candidates with filtered net insider buying (especially clusters or opportunistic buys) over the last 1–6 months, and a negative screen for heavy multi-insider selling.
- **[ST]**: secondary. Event trigger only for publication-day or next-day entries on clustered or large opportunistic buys in liquid names; the expected edge is small (about 0.25%/5 days in Finland) relative to Nordic small-cap spreads.
- Log every signal with `published_at` and evaluate 1/5/21/63/126/252-day market- and size-adjusted forward returns. US replication shows that a few years of data are statistically weak, so the app should accumulate history (FI back to 2016) before trusting the weights.

### Gaps
- No Nordic-specific estimates exist for cluster, role or opportunistic effects in the MAR era. Weights must be learned from the app's own logged outcomes or a backfilled event study using FI data since 2016.
- The `transactionType` codes in Börsdata and the English `Karaktär` strings in FI's en-GB export need first-hand inspection before the classification is final.
