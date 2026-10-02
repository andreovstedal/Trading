# Allocation, Prediction Logging & Evaluation Framework for a Two-Sleeve Nordic Retail Stock App (research notes, as of 2026-10-02)

*How these notes were sourced: the egress proxy blocked direct fetches of ESMA, EUR-Lex, Finanstilsynet, FI, Lovdata, Riksdagen, Nordnet, several law-firm sites, Crossref, arXiv and the Bailey/López de Prado paper host. The session's web-search budget also ran out partway through. As a result:*
- *Regulatory, fee and exchange-policy facts come from search-result summaries of the official pages cited. The wording is paraphrased, not verbatim.*
- *Tool facts (versions, dates, licences, features) were checked directly against PyPI JSON metadata and GitHub raw files on 2026-10-02.*
- *Claude API facts come from Anthropic's bundled claude-api reference, cached 2026-09-25, and are cited to the matching official doc URLs.*
- *Items marked **†** cite standard references from prior knowledge that could not be re-fetched in this session. The reference itself is standard, but check the exact figures and wording before publishing.*

---

## 1. Sleeve split: fixed vs dynamic allocation between the short-term trading sleeve and the long-term value sleeve, short-term risk controls, cash buffer

### Takeaway
Use a **fixed, user-set policy** (for example 80–90% long-term value, 0–15% short-term, 2–5% cash) and enforce hard guardrails on it. Allow only slow, rules-based shifts, and only after the sleeve has passed an out-of-sample evidence test. Three reasons:
- Base rates for retail short-term trading are poor.
- Minimum courtage makes small short-term positions very expensive.
- Statistical evidence that one sleeve beats another builds up over **years, not months**. For example, MinTRL for an annualised Sharpe of 0.5 is about 11 years of daily data.

### Cited Findings
- Barber, Lee, Liu & Odean studied the complete trading records of the Taiwan stock market from 1992 to 2006:
  - fewer than 1% of day traders were predictably profitable from year to year;
  - heavy day traders earned gross profits that did not cover their transaction costs;
  - in a typical six-month period, more than eight in ten day traders lost money.
  — [Barber et al., "The Cross-Section of Speculator Skill" (PDF)](https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf); [Barber et al., "Do Individual Day Traders Make Money? Evidence from Taiwan" (PDF)](http://www.econ.yale.edu/~shiller/behfin/2004-04-10/barber-lee-liu-odean.pdf)
- Brazil mini-index futures: among individuals who kept day trading for more than 300 days, about 97% lost money, and only about 1% earned more than the minimum wage. — [Chague, De-Losso & Giovannetti, "Day Trading for a Living?" (SSRN 3423101) †](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)
- The source papers for the evidence-gating statistics, as listed in the references of the open-source **pypbo** package (which implements all four in Python):
  - Probabilistic Sharpe Ratio (PSR) and Minimum Track Record Length (MinTRL): Bailey & López de Prado, "The Sharpe Ratio Efficient Frontier", *Journal of Risk* 15(2), 2012/13, SSRN 1821643;
  - Deflated Sharpe Ratio (DSR): *Journal of Portfolio Management* 40(5):94–107, 2014, SSRN 2460551;
  - Probability of Backtest Overfitting (PBO): Bailey, Borwein, López de Prado & Zhu, *Journal of Computational Finance*, SSRN 2326253.
  — [pypbo README (GitHub)](https://github.com/esvhd/pypbo)
- MinTRL formula: MinTRL = 1 + [1 − γ̂₃·SR̂ + ((γ̂₄ − 1)/4)·SR̂²] · (Z_α / (SR̂ − SR*))²
  - SR̂ is the observed Sharpe ratio at the sampling frequency (for example daily), γ̂₃ is skewness, γ̂₄ is kurtosis, and SR* is the benchmark Sharpe.
  - Negative skew and fat tails lengthen the required record.
  — [Bailey & López de Prado (2012), SSRN 1821643 †](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1821643)
- skfolio ships **Risk Budgeting**, Hierarchical Risk Parity and Nested Clusters Optimization estimators. These can be used to set the capital split from target risk contributions per sleeve. — [skfolio on PyPI](https://pypi.org/project/skfolio/)
- Stop-loss rules lower expected returns when prices follow a random walk, but can add value when returns have momentum or serial correlation. — [Kaminski & Lo (2014), "When do stop-loss rules stop losses?", *J. Financial Markets* †](https://doi.org/10.1016/j.finmar.2013.07.001)
- Nordnet Norway (search summaries of Nordnet's price list and a comparison site):
  - Mini class: 0.15% courtage, minimum NOK 29 on Nordic markets. Suits orders below about NOK 52,667.
  - Normal class: 0.049%, minimum NOK 79.
  — [Nordnet NO prisliste](https://www.nordnet.no/kundeservice/prisliste); [Nordnet NO FAQ – kurtasjeklasse Mini](https://www.nordnet.no/faq/priser/kurtasje/hvordan-endrer-jeg-til-kurtajeklasse-mini); [Smartepenger price overview](https://www.smartepenger.no/sparing/2072-prisoversikt-aksjemeglere-pa-nett)

### Inferences
**Proposed default policy (user-editable, versioned in `policy_json`):**

| Sleeve | Default | Allowed range | Notes |
|---|---|---|---|
| Long-term value | 85% | 60–100% | Rebalanced monthly or quarterly with a no-trade band |
| Short-term trading | 10% | 0–25% (hard cap) | Starts as **paper-only** until the evidence gate is passed |
| Cash buffer | 5% | 2–10% | Covers courtage, FX conversion, integer-share rounding residuals, opportunistic entries |

**Why not performance-chasing allocation?** MinTRL arithmetic, assuming normal returns, a 95% one-sided test and SR* = 0:

| Annualised Sharpe | Required record |
|---|---|
| 0.5 (daily SR ≈ 0.0315) | ≈ 2,700 trading days (≈ 10.8 years) |
| 1.0 | ≈ 680 days (≈ 2.7 years) |
| 1.6 | ≈ 270 days (≈ 1.1 years) |

Comparing *two* sleeves is harder still, because the difference between them carries the variance of both. A short track record is therefore close to useless for moving capital between sleeves. The UI should show this explicitly as an "evidence meter".

**Evidence-gated dynamic rule.** This is optional and replaces a free-floating "allocate to the winner" rule:
1. Count only out-of-sample results: shadow or paper results after the model version was frozen, plus live results. All results are net of modelled courtage and spread.
2. A sleeve may grow only when **all** of the following hold:
   - track length ≥ MinTRL at the observed SR, skew and kurtosis;
   - PSR(SR* = 0) ≥ 0.95;
   - if several variants were tried, DSR computed with N = the number of variants in the trial registry (Section 4) ≥ 0.95.
3. Use a shrunk Sharpe: SR_post = SR̂ · T / (T + T₀), with a prior strength T₀ of about 2–3 years of observations. Target risk weights ∝ max(0, SR_post), scaled by at most half-Kelly (see Section 2).
4. Move at most 5 percentage points per quarter, always within the user's hard bounds. Never auto-increase leverage or concentration.

**Risk-budget alternative.** Specify the **share of total portfolio volatility** the short-term sleeve may contribute, for example 15–25%, rather than its share of capital. Then size the capital from realised volatility using the risk-budgeting estimators above. This automatically shrinks the sleeve when it becomes more volatile.

**Short-term sleeve risk controls.** These are design heuristics. No source gives retail-specific thresholds (see Gaps).
- **Loss limits:**
  - daily loss limit about 2–3% of sleeve value, after which no new entries that day;
  - weekly loss limit about 5–6%, after which new entries pause until next week;
  - **circuit breaker** at a 10–15% drawdown from the sleeve's high-water mark: the sleeve reverts to paper mode, its capital moves to cash or long-term, and a review is required (including re-checking the model version).
- **Trade and position limits:**
  - at most 2–3 new trades per day and about 10 per week;
  - at most 3–5 open positions;
  - any single position at most 25–35% of the sleeve and at most 5% of the total account;
  - no averaging down.
- **Exit rules:**
  - a time-stop equal to the forecast horizon, for example exit after 5 trading days unless re-signalled;
  - price stop-losses only if backtests show momentum or serial correlation at that horizon (Kaminski & Lo).
- **Universe filters:** a minimum average daily traded value and a maximum quoted spread. Ban instruments where the user may hold non-public information (Section 7).

**Cost drag makes trade caps essential.** With Nordnet NO Mini (0.15%, minimum NOK 29):
- A NOK 40k sleeve split into 4 × NOK 10k positions pays NOK 58 per round trip, or 0.58%. 150 round trips a year cost about NOK 8,700, roughly 22% of the sleeve per year *before* spreads.
- At 4 × NOK 20k (an NOK 80k sleeve) each round trip costs about 0.30%, roughly 11% of the sleeve per year.
- The trade cap and the minimum position size therefore matter as much as signal quality.

**Cash buffer.** Keep 2–5% unallocated, and show it explicitly. It absorbs:
- integer-share rounding: PyPortfolioOpt's `DiscreteAllocation` returns leftover cash;
- courtage, FX conversion between NOK and SEK listings, and dividend timing;
- the need to avoid forced sales to fund new entries.

### Gaps
- No source gives empirically grounded daily/weekly loss-limit or trade-cap values for retail accounts. The thresholds above are heuristics and should be labelled as such in the app.
- No Nordic-specific study of retail short-term trading profitability was found. The evidence above is from Taiwan and Brazil.
- Nordnet's FX conversion fee (NOK↔SEK) was not found.
- Effects of the Norwegian ASK and Swedish ISK account wrappers (tax drag, eligible instruments) were not researched.

---

## 2. Allocation within each sleeve: from signal scores to weights, constraints, small-portfolio practice, and expressing uncertainty

### Takeaway
For 5–20 positions and NOK/SEK 50k–1m, use **robust, low-parameter weighting**: rank → top-N → equal or inverse-volatility weights, with small score tilts. Apply hard caps, fee-aware minimum position sizes and no-trade bands. Use Ledoit-Wolf shrinkage, Black-Litterman with signal-derived views, or HRP only as *tilts or diagnostics* once the signal's expected returns are shown to be calibrated. Avoid unconstrained mean-variance and full Kelly. **Nordnet minimum courtage, not optimisation theory, is the binding constraint on how many positions a small account can hold.**

### Cited Findings
- DeMiguel, Garlappi & Uppal compared 14 optimal-portfolio models across seven empirical datasets:
  - none was consistently better than naive 1/N on Sharpe ratio, certainty-equivalent return or turnover;
  - sample mean-variance needs an estimation window of more than **3,000 months for 25 assets** (more than 6,000 for 50) to beat 1/N;
  - extensions meant to curb estimation error shortened that window only moderately.
  — [DeMiguel, Garlappi & Uppal (2009), *Review of Financial Studies*](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901); [working paper PDF](https://users.nber.org/~confer/2006/si2006/ap/uppal.pdf)
- skfolio's README:
  - flags classical optimisation's sensitivity to "input parameters (expected returns and covariance), weight concentration, high turnover";
  - lists Risk Budgeting, Hierarchical Risk Parity, Nested Clusters Optimization, Entropy Pooling, Ledoit-Wolf, Walk Forward, Combinatorial Purged Cross-Validation, Transaction Costs and Turnover Constraints.
  — [skfolio on PyPI](https://pypi.org/project/skfolio/)
- PyPortfolioOpt:
  - offers Ledoit-Wolf shrinkage with three targets (`constant_variance`, `single_factor`, `constant_correlation`);
  - offers Black-Litterman allocation (`BlackLittermanModel(S, pi=..., absolute_views=..., omega=...)`), Hierarchical Risk Parity, and "L2 regularisation, shrunk covariance";
  - offers `DiscreteAllocation(weights, latest_prices, total_portfolio_value=...)`, which turns weights into whole share counts for a given account value.
  — [PyPortfolioOpt on PyPI](https://pypi.org/project/pyportfolioopt/); [PyPortfolioOpt Black-Litterman docs](https://pyportfolioopt.readthedocs.io/en/latest/BlackLitterman.html)
- Riskfolio-Lib offers:
  - Mean-Risk and Logarithmic Mean-Risk (Kelly criterion) optimisation with 26 convex risk measures;
  - HRP and HERC with 37 risk measures, and Nested Clustered Optimization;
  - Black-Litterman, Bayesian Black-Litterman and Augmented Black-Litterman;
  - Entropy Pooling, and constraints on tracking error and turnover.
  — [Riskfolio-Lib on PyPI](https://pypi.org/project/riskfolio-lib/)
- quantstats includes a `kelly_criterion` statistic. — [quantstats on PyPI](https://pypi.org/project/quantstats/)
- Ledoit-Wolf covariance shrinkage. — ["Honey, I Shrunk the Sample Covariance Matrix" (2004) †](http://www.ledoit.net/honey.pdf)
- Black-Litterman blends equilibrium returns with investor views weighted by confidence. — [Black & Litterman (1992), *Financial Analysts Journal* †](https://doi.org/10.2469/faj.v48.n5.28)
- HRP (López de Prado 2016) allocates through hierarchical clustering and recursive bisection, without inverting the covariance matrix. — [SSRN 2708678 †](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678)
- Kelly growth-optimal betting. — [Kelly (1956), *Bell System Technical Journal* †](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x)
- Fundamental Law of Active Management: IR ≈ IC × √breadth. — [Grinold (1989), *J. Portfolio Management* †](https://doi.org/10.3905/jpm.1989.409211). Constraints such as long-only lower the "transfer coefficient": IR ≈ TC × IC × √breadth. — [Clarke, de Silva & Thorley (2002), *FAJ* †](https://doi.org/10.2469/faj.v58.n5.2468)
- Square-root market-impact law: impact grows roughly with σ·√(Q/V). — [Tóth et al. (2011), arXiv:1105.1694 †](https://arxiv.org/abs/1105.1694)
- Nordnet Norway (search summary of price-list pages):
  - Mini: 0.15%, minimum NOK 29 on Nordic markets; 0.2%, minimum NOK 49 outside the Nordics.
  - Normal: 0.049%, minimum NOK 79. Mini fits orders below about NOK 52,667.
  - New customers get a welcome offer of minimum courtage from NOK 1 for the current and next month.
  — [Nordnet NO prisliste](https://www.nordnet.no/kundeservice/prisliste); [Smartepenger](https://www.smartepenger.no/sparing/2072-prisoversikt-aksjemeglere-pa-nett)
- Nordnet Sweden (search summary):

  | Class | Order size (SEK) | Courtage | Minimum |
  |---|---|---|---|
  | Mini | ≤ 15,600 | 0.25% | 1 SEK (Nordic) |
  | Liten | 15,600–46,000 | 0.15% | 39 SEK |
  | Mellan | 46,000–143,478 | 0.069% | 69 SEK |
  | Fast | > 143,478 | 99 SEK flat | — |

  New customers reportedly trade Nordic exchanges courtage-free until 30 June 2027 (promotion; verify). — [Nordnet SE prislista](https://www.nordnet.se/kundservice/prislista); [Nordnet SE FAQ courtageklasser](https://www.nordnet.se/faq/courtage-avgifter/courtage/vilken-courtageklass-passar-mig-bast); [Kvalitetsaktier courtage comparison 2026](https://kvalitetsaktier.se/courtage-jamforelse)
- Quantile dotplots are discrete, frequency-framed displays of a predictive distribution. Lay users read probabilities from them more precisely than from continuous density displays. — [Kay, Kola, Hullman & Munson (2016), "When (ish) is my bus?", CHI †](https://doi.org/10.1145/2858036.2858558)

### Inferences
**Fee-driven minimum position size.** These figures follow from the fee schedules above.
- NO Mini becomes proportional (0.15%) above NOK 29 / 0.0015 ≈ **NOK 19,300**. Below that, the NOK 29 minimum makes small trades disproportionately expensive: an NOK 10k trade costs 0.29% one way.
- NO Normal becomes proportional only above about NOK 161k.
- SE Liten becomes proportional above SEK 26k, Mellan above about SEK 100k, and Fast costs 0.05% at SEK 200k.
- **Rule:** min_position ≈ max(min_fee / target_fee_rate, liquidity floor). With Mini, a target of ≤0.15% one-way gives a minimum of about NOK 20k. The maximum number of positions is then (account × (1 − cash%)) / min_position:

  | Account (NOK) | Long-term positions | Short-term sleeve |
  |---|---|---|
  | 50k | 2–3 (consider a broad ETF/fund core instead of single stocks) | Paper-only |
  | 200k | 6–8 | 1–2 positions at most |
  | 500k | 10–15 | — |
  | 1m | 15–20 (more adds little diversification but more monitoring and courtage) | — |

**Recommended weighting ladder (simple → complex).** Move up a step only when evidence justifies it.
1. **Top-N equal weight** within each sleeve. This is the default and is supported by DeMiguel et al.
2. **Top-N inverse-volatility** (risk-parity-lite), using 60–120-day volatility with a Ledoit-Wolf-style shrink to the cross-sectional median.
3. **Score-tilted equal weight**: wᵢ ∝ (1 + κ·zᵢ), with κ chosen so that tilts are at most ±50% of the equal weight, then clipped and renormalised. This keeps the portfolio robust while still using score strength.
4. **Black-Litterman with signal views**, only once calibration is demonstrated (Section 4):
   - convert composite z-scores to expected active returns with the Grinold–Kahn rule αᵢ ≈ IC × σᵢ × zᵢ †;
   - set each view's uncertainty from the standard error of the realised IC, so a weak or short track record automatically gives weak tilts;
   - use an equal-weight or market-cap prior and LW covariance.
5. **HRP/HERC** as a diversification overlay once N ≥ 10. Use clusters as correlation buckets for caps, which matters because Norwegian portfolios cluster in energy, seafood, shipping and banks.
6. **Avoid** unconstrained mean-variance and full Kelly. Fractional Kelly must be capped by the constraints below.

**Fractional Kelly arithmetic (derived).**
- For log-normal returns, growth at a fraction c of the Kelly bet is g(c) = c·(2 − c)·g*.
- **Half-Kelly** therefore keeps about 75% of maximum growth at about 50% of the volatility.
- Betting **2× Kelly**, which is what happens if the edge estimate is double the true edge, gives zero expected log-growth.
- Since the app's edge estimates are noisy, use Kelly only to **cap gross exposure** (for example, short sleeve at most 0.25–0.5× estimated Kelly), never to set single-stock weights.

**Constraint set for both sleeves** (values are starting heuristics):

| Constraint | Long-term value | Short-term trading |
|---|---|---|
| Max weight per stock | 15–20% of sleeve (e.g., 12.5% EW with 8 names) | 25–35% of sleeve, ≤5% of account |
| Max per sector / HRP cluster | 30–35% | 50% |
| Liquidity cap | position ≤ 1–2% of 20-day average daily traded value | ≤ 0.5–1% of ADV and quoted spread ≤ ~0.5% |
| Minimum position | ≥ fee-efficient size (above) | same |
| No-trade band | skip if \|Δw\| < 2–3 pp or trade < min position | n/a (signal-driven) |
| Turnover penalty | λ·‖Δw‖₁ in optimiser, or rebalance only monthly/quarterly | hard trade caps (Section 1) |
| Eligibility | Nordnet-tradable, Oslo Børs/Euronext Growth/Nasdaq Stockholm/First North | same + intraday liquidity filter |

The square-root impact law says that trading 1% of ADV in a stock with 3% daily volatility costs on the order of 0.3% in impact. For small caps this is comparable to courtage, so the liquidity cap matters.

**Expressing confidence and uncertainty in the UI.**
- **Per line:**
  - rank and score percentile;
  - "probability of beating the equal-weight universe over the horizon", read from the **calibration table** (realised hit rate in that probability bucket, and n);
  - expected excess return as a range, shown as a quantile dotplot or fan chart rather than a point estimate;
  - *cost-adjusted* edge (expected edge minus round-trip courtage and spread);
  - data freshness: the newest source timestamp used and whether quotes are 15-minute delayed.
- **Per sleeve:**
  - live/paper track record with confidence intervals;
  - an "evidence meter" showing the current track length versus MinTRL and the current PSR;
  - the current model version and when its weights last changed.
- **Rounding:** show weights to whole percentages and integer share counts so the output does not look more precise than it is. Show the cash residual.
- **Language:** use "Model suggests…" with a link to "How this is computed / track record". Avoid "buy now" wording. This also matters for the regulatory characterisation (Section 7).

### Gaps
- No practitioner survey or authoritative guidance specific to 5–20-stock retail portfolios was found. The recommendations rest on the 1/N evidence and on fee arithmetic.
- Bid-ask spreads and average daily turnover distributions for Oslo, Stockholm and First North small caps were not researched. These are needed to set liquidity caps empirically.
- Nordnet's FX conversion fee and any market-specific courtage differences for Norwegian customers trading Stockholm shares were not found.
- PyPortfolioOpt's Idzorek-confidence omega option and skfolio's exact Black-Litterman API were not verified this session. Only the README features listed above were verified.

---

## 3. Logging: what to capture at each "gather data" run and each recommendation, outcome tracking, benchmarks, implementation shortfall, adherence, schema and immutability

### Takeaway
Build the system as an **append-only, bitemporal event log**:
- raw source payloads with content hashes and both *published* and *first-seen* timestamps;
- point-in-time features with an explicit data cutoff;
- model and prompt versions;
- predictions per horizon and recommended weights per sleeve, including the quotes and estimated costs the user saw;
- the user's actual executions;
- outcomes appended when each horizon matures, measured against total-return benchmarks and an equal-weight universe.

DuckDB with Parquet is enough at personal scale. Keep Postgres for the app state if a multi-user web app is planned.

### Cited Findings
- Bitemporal modelling separates "valid time" (when something was true in the world) from "record/transaction time" (when the system learned it). This lets queries reconstruct exactly what was known at any past moment. — [Martin Fowler, "Bitemporal History" †](https://martinfowler.com/articles/bitemporal-history.html)
- DuckDB is an in-process analytical database that reads and writes CSV, Parquet and JSON locally or on S3. MIT licence; version 1.5.6 released 2026-09-28. — [DuckDB on PyPI](https://pypi.org/project/duckdb/)
- ArcticDB has "Time travel: travel back in time to see previous versions of your data and create customizable snapshots". Its licence is discussed in Section 5. — [ArcticDB on PyPI](https://pypi.org/project/arcticdb/)
- TimescaleDB (now branded Tiger Data) has a split licence: source outside the `tsl` directory is Apache 2.0, while code inside `tsl` and binaries with `-tsl` in their name fall under the Timescale License. — [timescaledb LICENSE](https://github.com/timescale/timescaledb/blob/main/LICENSE)
- Implementation shortfall measures the gap between the return of the "paper" (decision-price) portfolio and the return actually realised. It splits into explicit costs, execution and delay costs, and opportunity cost of unfilled orders. — [Perold (1988), "The Implementation Shortfall: Paper versus Reality", *JPM* †](https://doi.org/10.3905/jpm.1988.409150)
- Delayed-data rules (relevant for logging quote staleness):
  - Euronext must make delayed data (published ≥15 minutes after initial publication) available free of charge, and internal use of delayed data is free.
  - Nasdaq treats data delayed by less than 15 minutes as real-time.
  — [Euronext market-data fees and policies](https://www.euronext.com/en/data/market-data/market-data-pricing-policies); [Nasdaq European Data Policies (Jan 2026)](https://www.nasdaq.com/docs/Nasdaq_European_Data_Policies_January_2026_New)
- LLM-derived features can carry look-ahead bias: the model may "know" what happened after the text was published. — [Glasserman & Lin, arXiv:2309.17322](https://arxiv.org/pdf/2309.17322). This is why the LLM's model ID and call date must be logged alongside each extracted event (Section 6).

### Inferences
**What to capture.**
- **Each gather run:**
  - run id, code git SHA, config hash, start and end time;
  - for each fetched item: source, URL, HTTP status, `fetched_at` (transaction time), `published_at` claimed by the source (valid time), sha256 of the raw bytes, path to the raw payload, parser version.
- **Live signals:** availability time = max(published_at, first_seen_at).
- **Backfilled history:** tag rows `pit_quality = backfilled` and use published_at plus a conservative lag. Never assume the backfill was knowable at publication second.
- **Revisions:** corrected announcements and amended insider notifications become new rows that supersede old ones. Never overwrite.
- **Universe snapshots:** store the tradable universe each day, including later-delisted names, to avoid survivorship bias. Store corporate actions (dividends with ex-date and amount, splits) and daily FX rates (NOK/SEK and others) so total returns and base-currency returns can be recomputed.
- **Each recommendation:**
  - account value entered and base currency;
  - sleeve policy and cash buffer;
  - model version IDs (long and short) and the data cutoff;
  - per line: score, rank, predicted probabilities and expected returns per horizon, target weight, target value, integer shares;
  - **reference quote** (last, bid, ask, quote timestamp, delay in minutes);
  - estimated courtage, spread and FX cost;
  - a hash of the exact UI payload shown, and the disclaimer version shown.
- **Adherence:** for each recommended line, record followed / partial / ignored / override, plus executions (quantity, price, timestamp, courtage, FX rate and fee). Import these from the broker's transaction export where possible, otherwise enter them manually. This keeps "model skill" separate from "user behaviour".
- **Outcomes:** a nightly job appends outcome rows when horizons mature, using exchange trading calendars:
  - short-term horizons: same-day close (if recommended intraday), +1, +2 and +5 trading days;
  - long-term horizons: +20, +60, +120 and +250 trading days.
  - Measure each in local-currency total return, base-currency total return, and excess over (a) the primary index benchmark and (b) the **equal-weight tradable-universe total-return index** built from the app's own data with the same filters. (b) is the fairest test of stock-selection skill.
- **Benchmarks:**
  - Norway: OSEBX, after confirming it is a dividend-adjusted (total-return) index.
  - Sweden: use the gross/total-return variants (for example the OMXS "GI" indices or the SIX Return Index) rather than OMXSPI/OMXS30 price indices. This was not verified (see Gaps).
  - Compare total return to total return. Mixing a price index with a portfolio that includes dividends overstates alpha by about the dividend yield, which is material for high-yield Oslo stocks.
- **Implementation shortfall per line** (Perold decomposition):
  - IS = paper return from the decision-time mid minus realised return;
  - components: explicit (courtage plus FX fee), spread (fill vs mid at the reference quote), delay (mid at execution vs mid at reference), opportunity (unexecuted lines valued at the paper return).
  - If the app runs on free 15-minute-delayed data, the "decision price" is stale. Log the delay and treat delay cost as part of the system's cost.
- **Keep three books:**
  1. the **paper champion book** (every recommendation followed perfectly at the reference mid plus modelled costs);
  2. **shadow challenger books**;
  3. the **actual account book**.

  The gap between 1 and 3 is adherence plus implementation shortfall. Evaluating only executed trades creates selection bias.

**Proposed schema** (DuckDB-compatible SQL; Postgres works with minor type changes):

```sql
-- Provenance (append-only)
CREATE TABLE gather_run (run_id UUID PRIMARY KEY, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  code_git_sha TEXT, config_sha256 TEXT, status TEXT, error TEXT, prev_hash TEXT, row_hash TEXT);
CREATE TABLE source_snapshot (snapshot_id UUID PRIMARY KEY, run_id UUID NOT NULL, source TEXT NOT NULL,
  request_url TEXT, http_status INT, fetched_at TIMESTAMPTZ NOT NULL, published_at TIMESTAMPTZ,
  content_sha256 TEXT NOT NULL, raw_path TEXT NOT NULL, parser_version TEXT,
  pit_quality TEXT CHECK (pit_quality IN ('live','backfilled_published_ts','backfilled_estimated')));
CREATE TABLE event (event_id UUID PRIMARY KEY, event_key TEXT NOT NULL, revision INT NOT NULL,
  supersedes_event_id UUID, snapshot_id UUID NOT NULL, issuer_id TEXT, instrument_id TEXT,
  event_type TEXT, published_at TIMESTAMPTZ, first_seen_at TIMESTAMPTZ NOT NULL,
  available_at TIMESTAMPTZ NOT NULL, extractor TEXT, extractor_version TEXT, llm_call_id UUID, payload JSON);
CREATE TABLE llm_call (llm_call_id UUID PRIMARY KEY, model_requested TEXT, model_returned TEXT,
  prompt_id TEXT, prompt_version TEXT, prompt_sha256 TEXT, schema_version TEXT, input_sha256 TEXT,
  request_json JSON, response_json JSON, stop_reason TEXT, input_tokens INT, output_tokens INT,
  cache_read_tokens INT, cache_write_tokens INT, cost_usd DOUBLE, latency_ms INT, batch_id TEXT,
  created_at TIMESTAMPTZ);
-- Market data & universe
CREATE TABLE price_bar (instrument_id TEXT, bar_date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  volume BIGINT, turnover DOUBLE, currency TEXT, source TEXT, snapshot_id UUID);
CREATE TABLE corporate_action (instrument_id TEXT, ex_date DATE, pay_date DATE, kind TEXT, amount DOUBLE,
  currency TEXT, ratio DOUBLE, snapshot_id UUID);
CREATE TABLE fx_rate (rate_date DATE, pair TEXT, rate DOUBLE, source TEXT, snapshot_id UUID);
CREATE TABLE universe_member (asof_date DATE, instrument_id TEXT, isin TEXT, venue TEXT, segment TEXT,
  broker_tradable BOOLEAN, adv20 DOUBLE, median_spread_bps DOUBLE, delisted_at DATE);
-- Models, features, predictions
CREATE TABLE model_version (model_id TEXT PRIMARY KEY, sleeve TEXT, code_git_sha TEXT, params JSON,
  signal_weights JSON, created_at TIMESTAMPTZ, status TEXT /* champion|challenger|retired */);
CREATE TABLE feature_value (feature_run_id UUID, asof_ts TIMESTAMPTZ, data_cutoff_ts TIMESTAMPTZ,
  instrument_id TEXT, feature_name TEXT, feature_version TEXT, value DOUBLE);
CREATE TABLE prediction (pred_id UUID PRIMARY KEY, run_id UUID, model_id TEXT, is_shadow BOOLEAN,
  asof_ts TIMESTAMPTZ, data_cutoff_ts TIMESTAMPTZ, instrument_id TEXT, sleeve TEXT, horizon_td INT,
  score DOUBLE, rank_pct DOUBLE, exp_excess_ret DOUBLE, prob_outperform DOUBLE, pi_lo DOUBLE, pi_hi DOUBLE);
-- What the user saw
CREATE TABLE recommendation (rec_id UUID PRIMARY KEY, created_at TIMESTAMPTZ, account_value DOUBLE,
  base_ccy TEXT, policy JSON, cash_buffer_pct DOUBLE, model_id_long TEXT, model_id_short TEXT,
  data_cutoff_ts TIMESTAMPTZ, ui_payload_sha256 TEXT, disclaimer_version TEXT);
CREATE TABLE recommendation_line (rec_id UUID, instrument_id TEXT, sleeve TEXT, target_weight DOUBLE,
  target_value DOUBLE, target_shares INT, ref_last DOUBLE, ref_bid DOUBLE, ref_ask DOUBLE,
  quote_ts TIMESTAMPTZ, quote_delay_min INT, est_courtage DOUBLE, est_spread_cost DOUBLE,
  est_fx_cost DOUBLE, rationale JSON);
-- What actually happened
CREATE TABLE user_action (action_id UUID PRIMARY KEY, rec_id UUID, instrument_id TEXT,
  decision TEXT /* followed|partial|ignored|override */, side TEXT, qty INT, exec_price DOUBLE,
  exec_ts TIMESTAMPTZ, courtage_paid DOUBLE, fx_rate_used DOUBLE, fx_fee_paid DOUBLE,
  imported_from TEXT, created_at TIMESTAMPTZ);
CREATE TABLE outcome (pred_id UUID, horizon_td INT, start_ts TIMESTAMPTZ, end_ts TIMESTAMPTZ,
  ret_local_tr DOUBLE, ret_base_tr DOUBLE, bench_id TEXT, bench_ret_tr DOUBLE, ew_univ_ret_tr DOUBLE,
  excess_vs_bench DOUBLE, excess_vs_ew DOUBLE, calc_version TEXT, computed_at TIMESTAMPTZ);
CREATE TABLE nav_daily (nav_date DATE, book TEXT /* paper_champion|shadow_<id>|actual */, sleeve TEXT,
  nav_base DOUBLE, cash DOUBLE, fees_cum DOUBLE, turnover_cum DOUBLE);
-- Anti-self-deception: every experiment ever run (feeds DSR's N)
CREATE TABLE trial_registry (trial_id UUID PRIMARY KEY, created_at TIMESTAMPTZ, hypothesis TEXT,
  model_id TEXT, config JSON, data_window TEXT, is_oos BOOLEAN, metric_name TEXT, metric_value DOUBLE,
  sharpe DOUBLE, n_obs INT);
```

**Immutability practices.**
- **Insert-only:**
  - corrections arrive as new rows with `supersedes_*`;
  - "current" views select the latest revision with `available_at <= :cutoff`;
  - in Postgres, revoke UPDATE and DELETE from the app role and add a BEFORE UPDATE/DELETE trigger that raises.
- **Tamper-evidence:** a hash chain where `row_hash = sha256(prev_hash || canonical_json(row))` per run and recommendation. Commit the daily head hash to the git repo.
- **Content-addressed raw store:** Parquet or zstd blobs keyed by sha256 allow re-parsing with new parsers without re-fetching, which matters for sources that later change or delete content.
- **Point-in-time unit tests:** randomly re-compute features "as of" past cutoffs and assert that no input has `available_at` later than the cutoff. Fail the build on any violation.
- **UTC everywhere** plus Oslo and Stockholm exchange calendars for trading-day horizons.

### Gaps
- Whether OSEBX is a total-return index, and the exact tickers and providers of Swedish gross indices (OMXSGI/OMXS30GI/SIXRX), could not be verified because search was exhausted and exchange sites were not fetchable.
- The format of Nordnet's transaction export (for importing user actions) and whether Nordnet's API terms allow automated import were not researched.
- Dividend withholding-tax treatment for a Norwegian investor holding Swedish shares (and vice versa) was not researched. It affects "realised total return" in the actual book.
- DuckLake (DuckDB's lakehouse format with snapshots) could not be verified this session.

---

## 4. Evaluation and improvement: IC/ICIR, calibration, portfolio metrics, attribution, sample sizes, multiple testing, walk-forward and purged CV, champion–challenger, updating signal weights

### Takeaway
Score **signals** with rank IC/ICIR and IC decay by horizon, **probabilities** with Brier score and reliability diagrams, and **portfolios** with cost-adjusted excess return, Sharpe/Sortino, drawdown and turnover. Then defend against self-deception structurally:
- a **trial registry** feeding the Deflated Sharpe Ratio and PBO;
- purged and embargoed walk-forward or combinatorial CV;
- shadow challengers with pre-registered promotion rules;
- signal-weight updates that are slow, scheduled, versioned, and **shrunk toward equal weights**.

Expect live performance well below backtests.

### Cited Findings
- Alphalens-reloaded provides "Information Coefficient Analysis", "Turnover Analysis" and an IC tear sheet. — [alphalens-reloaded on PyPI](https://pypi.org/project/alphalens-reloaded/). Qlib's analysis module reports IC, monthly IC and rank/score IC. — [pyqlib on PyPI](https://pypi.org/project/pyqlib/)
- skfolio's `CombinatorialPurgedCV` docstring:
  - "Purging consists of removing from the training set all observations whose labels overlapped in time with those labels included in the testing set";
  - "Embargoing consists of removing from the training set all observations that immediately follow an observation in the testing set";
  - CPCV recombines *multiple* test paths, whereas K-fold gives a single path;
  - skfolio also ships Walk Forward.
  — [skfolio `_combinatorial.py` (GitHub)](https://github.com/skfolio/skfolio/blob/main/src/skfolio/model_selection/_combinatorial.py); [skfolio on PyPI](https://pypi.org/project/skfolio/)
- Paper references, listed by **pypbo** (which implements PBO, PSR, MinTRL and DSR):
  - PBO: Bailey, Borwein, López de Prado & Zhu, *J. Computational Finance*, SSRN 2326253;
  - PSR/MinTRL: *J. Risk* 15(2), SSRN 1821643;
  - DSR: *JPM* 40(5):94–107, SSRN 2460551;
  - "Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance", *Notices of the AMS* 61(5):458–471, SSRN 2308659.
  — [pypbo (GitHub)](https://github.com/esvhd/pypbo)
- **DSR formulas:**
  - DSR = PSR(SR₀), where PSR(SR*) = Φ[(SR̂ − SR*)·√(T − 1) / √(1 − γ̂₃·SR̂ + ((γ̂₄ − 1)/4)·SR̂²)];
  - SR₀ = √V[{SRₙ}] · ((1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e))), where N is the number of independent trials and γ ≈ 0.5772 is the Euler–Mascheroni constant.
  - The expected maximum Sharpe under the null therefore rises with the number of trials tried.
  — [Bailey & López de Prado (2014), SSRN 2460551 †](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
- **PBO via combinatorially symmetric cross-validation (CSCV)** †:
  - split the performance matrix of all tried configurations into S blocks and form all half/half train/test combinations;
  - in each combination, pick the in-sample best configuration and record its out-of-sample rank;
  - PBO = the share of combinations where the in-sample winner falls below the out-of-sample median.
  — [Bailey et al., SSRN 2326253 †](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
- Because of data-mining across hundreds of published factors, a new factor should clear a t-statistic hurdle of about **3.0**, not 2.0. — [Harvey, Liu & Zhu (2016), *Review of Financial Studies* †](https://doi.org/10.1093/rfs/hhv059)
- Return predictability decays: anomaly portfolio returns are about 26% lower out-of-sample and about 58% lower after publication. — [McLean & Pontiff (2016), *Journal of Finance* †](https://doi.org/10.1111/jofi.12365). Replicating 452 anomalies, about 65% fail |t| ≥ 1.96 once microcaps are controlled for. — [Hou, Xue & Zhang (2020), *Review of Financial Studies* †](https://doi.org/10.1093/rfs/hhy131)
- Calibration measures:
  - Brier score: mean squared error of probability forecasts. — [Brier (1950), *Monthly Weather Review* †](https://doi.org/10.1175/1520-0493(1950)078%3C0001:VOFEIT%3E2.0.CO;2)
  - Reliability diagrams and expected calibration error are standard calibration checks. — [Guo et al. (2017), arXiv:1706.04599 †](https://arxiv.org/abs/1706.04599)
  - scikit-learn provides `calibration_curve` plus isotonic and sigmoid calibrators. — [scikit-learn calibration guide †](https://scikit-learn.org/stable/modules/calibration.html)
- Model-risk guidance frames validation around conceptual soundness, ongoing monitoring and outcomes analysis, including back-testing. — [Federal Reserve SR 11-7 †](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- Monitoring and versioning tools:
  - Evidently offers data-drift presets (for example `DataDriftPreset(method="psi")`), data-quality checks and LLM evals. — [Evidently on PyPI](https://pypi.org/project/evidently/)
  - MLflow 3.x provides experiment tracking plus GenAI tracing, evaluation and a **prompt registry**. — [MLflow on PyPI](https://pypi.org/project/mlflow/)
- Forecast-combination puzzle: simple averages often beat "optimally" estimated combination weights out-of-sample, because weight estimation error dominates. — [Smith & Wallis (2009), *Oxford Bulletin of Economics and Statistics* †](https://doi.org/10.1111/j.1468-0084.2008.00541.x). This is the forecasting analogue of DeMiguel et al.'s 1/N result. — [DeMiguel et al. (2009)](https://academic.oup.com/rfs/article-abstract/22/5/1915/1592901)
- Anthropic's eval-hygiene guidance gives a noise floor for a pass/hit rate of roughly ±1/√(n·R): 25 cases × 2 reps ≈ ±14 points, 100 × 2 ≈ ±7. It also recommends random train/test splits, and warns that splits selected on poor baseline scores produce regression-to-the-mean "improvements". — [Anthropic claude-api skill, `shared/evals/eval-audit.md` (bundled reference; local file, no public URL)](file:///tmp/claude-0/bundled-skills/2.1.287/f5b1c635ee79464487d10d0a10cb272a/claude-api/shared/evals/eval-audit.md)

### Inferences
**Metric set per signal k and horizon h.** Compute these on non-overlapping samples, or use Newey-West/HAC errors when using overlapping daily-sampled multi-day returns.
- Rank IC_t = Spearman(score_{i,t}, fwd_ret_{i,t→t+h}) across the universe.
- Report mean IC, standard deviation of IC, ICIR = mean/sd, t ≈ ICIR·√T, an **IC decay curve** across h ∈ {1, 2, 5, 20, 60, 120, 250}, IC by year and by size bucket, and quantile-spread returns.
- Report signal **turnover**, meaning rank autocorrelation, which drives cost.
- Required sample sizes:
  - for t = 2, T ≈ (2 / ICIR)². Weekly ICIR 0.15 needs about 180 weeks (about 3.4 years); at the Harvey–Liu–Zhu t = 3 hurdle, about 400 weeks (about 7.7 years);
  - a hit rate of 53% versus 50% at 2 SE needs about 1,100 *independent* predictions. Daily 5-day predictions on the same stocks are not independent.

**Probabilities.**
- If the model outputs "P(beat EW universe over h)", log it and compute the Brier score with a reliability diagram (deciles), ECE, and per-bucket n.
- Recalibrate with isotonic regression on a rolling, purged window, and show the calibrated value in the UI (Section 2).

**Portfolio metrics, per book (paper, shadow, actual) and per sleeve:**
- excess return vs index and vs EW universe;
- Sharpe, Sortino, max drawdown and drawdown duration;
- hit rate per trade and average win/loss;
- turnover, **cost drag** (courtage + spread + FX as % of NAV per year), implementation shortfall, adherence rate, and "override alpha" (did the user's deviations add value?).

**Attribution.** Each period, run a cross-sectional regression of realised returns on signal z-scores (Fama–MacBeth-style) to get each signal's marginal return. Complement it with **leave-one-signal-out ablations** in walk-forward. Attribute long-term sleeve results to selection vs sector vs sizing with simple sector buckets.

**Validation protocol.**
1. Develop on history using **walk-forward** (expanding or rolling window) with **purge = label horizon** (for example 5 trading days for 5-day labels, 250 for 1-year labels) plus a small **embargo**. A common choice is about 1% of the sample, or the feature look-back for overlapping features (AFML guidance †).
2. When choosing among many configurations, use CPCV paths to estimate the *distribution* of out-of-sample Sharpe. Compute **PBO** over the full configuration set and **DSR** with N from the trial registry.
3. Freeze the version and run it in **shadow/paper** at least until MinTRL or the pre-registered minimum: for example ≥26 weeks for the short sleeve and ≥2 years for the long sleeve before any capital changes.
4. Log *every* backtest variant in `trial_registry`, including failures. Otherwise N is unknown and DSR is meaningless.

**Champion–challenger.**
- All challengers produce predictions at the same timestamps as the champion and are logged with `is_shadow = true`. Comparisons are therefore **paired**, which removes common market noise.
- Promote a challenger only if, over the pre-registered window, the paired difference in cost-adjusted excess return has PSR ≥ 0.95, DSR is computed across all challengers tried, and there is no material deterioration in drawdown, turnover or calibration.
- Retire the old champion to challenger status rather than deleting it.
- Use Evidently (PSI) to alert on feature drift, and alert on IC dropping below zero over a rolling window.

**Updating signal weights without overfitting.**
- Start with equal weights, or weights set from prior evidence, over a *small* number of signal families.
- Re-estimate **on a schedule** (quarterly), never ad hoc. Use w_new = λ·w_est + (1 − λ)·w_prior with λ = T/(T + T₀), where T₀ is about 2–3 years of observations.
  - w_est ∝ shrunk mean IC / sd(IC), or Σ_IC⁻¹·μ_IC (the ICIR-optimal combination †) with heavy covariance shrinkage.
  - Cap each update at ±5 percentage points per signal.
  - Floor negative-IC signals at 0 rather than shorting them.
- Add a new signal only if its out-of-sample t-statistic clears about 3 (multiple testing) *and* it improves the composite in purged walk-forward.
- Bayesian alternative: a normal prior on each signal's IC centred at 0 (or at the published-literature estimate cut by about 50% for decay, per McLean–Pontiff). The posterior mean then becomes the weight driver.
- Online learning (exponentiated-gradient or Hedge reweighting) adapts faster but chases noise in low-signal, non-stationary data. If used, apply a small learning rate and run it as a **challenger**, not as the champion.
- Every weight change creates a new `model_version`. Old predictions are never recomputed in place.

### Gaps
- Typical IC/ICIR magnitudes for Nordic insider-trade, news and LLM-sentiment signals were not researched here; they likely belong to the signal-source research stream. Without them, sample-size planning uses the illustrative ICIRs above.
- The exact AFML embargo recommendation and the "ICIR-optimal weights" derivation (Qian/Hua/Sorensen) could not be re-verified.
- No Nordic-market replication of anomaly decay was found.

---

## 5. Tooling (2026 maturity): what each open-source tool is good for here

### Takeaway
As of October 2026, the actively maintained core for this app is:
- **DuckDB + Parquet** for storage and analytics;
- **APScheduler** (simple) or **Prefect** (retries, caching, UI) for scheduled collection;
- **skfolio** or **Riskfolio-Lib**, plus **PyPortfolioOpt's DiscreteAllocation**, for allocation;
- **alphalens-reloaded**, **quantstats** and **pypbo** for evaluation;
- **vectorbt** for fast research backtests, keeping its Commons Clause in mind;
- **MLflow + Evidently** for versioning, prompt registry and monitoring.

Qlib and zipline-reloaded work but are heavier and slower-moving. **Backtrader is stale** (no PyPI release since April 2023).

### Cited Findings
Versions and dates are from PyPI JSON metadata fetched on 2026-10-02; licences are from PyPI classifiers or GitHub LICENSE files.

| Tool | Latest release (date) | Licence | Maturity signals | Fit for this app | Source |
|---|---|---|---|---|---|
| Microsoft Qlib (`pyqlib`) | 0.9.7 (2025-08-15) | MIT | PyPI dev status "3 – Alpha"; README highlights RD-Agent "LLM-driven Auto Quant Factory" (Aug 8 2024); IC/rank IC analysis | Full research platform (data, models, IC analysis). Heavy for a personal app | [PyPI](https://pypi.org/project/pyqlib/) |
| alphalens-reloaded | 0.4.6 (2025-06-02) | Apache-2.0 | Production/Stable; IC and turnover tear sheets | Quick factor diagnostics (IC by horizon, quantile returns) | [PyPI](https://pypi.org/project/alphalens-reloaded/) |
| vectorbt | 1.1.1 (2026-09-26) | **Apache 2.0 with Commons Clause** (no right to "Sell", incl. paid hosting/consulting) | "Open-source community edition of VectorBT PRO"; walk-forward optimisation; Python 3.11–3.14 | Fast vectorised parameter sweeps and walk-forward. Licence matters if monetising | [PyPI](https://pypi.org/project/vectorbt/); [LICENSE](https://github.com/polakowo/vectorbt/blob/master/LICENSE.md) |
| zipline-reloaded | 3.1.1 (2025-07-19) | Apache-2.0 | Beta; Python ≥3.10 | Event-driven daily backtests with data bundles. Nordic calendars and bundles need custom work | [PyPI](https://pypi.org/project/zipline-reloaded/) |
| backtrader | 1.9.78.123 (2023-04-19) | GPLv3+ | No PyPI release since Apr 2023 | Legacy; avoid for new work | [PyPI](https://pypi.org/project/backtrader/) |
| PyPortfolioOpt | 1.6.0 (2026-02-26) | MIT | Beta; LW shrinkage, BL, HRP, `DiscreteAllocation` | Simplest path from weights to integer share counts for a given account value | [PyPI](https://pypi.org/project/pyportfolioopt/) |
| Riskfolio-Lib | 7.3.0 (2026-05-31) | BSD-3 | Kelly (log mean-risk), HRP/HERC (37 risk measures), NCO, BL variants, entropy pooling, turnover/TE constraints; Python ≥3.10 | Richest risk-measure catalogue | [PyPI](https://pypi.org/project/riskfolio-lib/) |
| skfolio | 1.4.10 (2026-09-30) | BSD-3 | Production/Stable; scikit-learn API; risk budgeting, HRP, NCO, entropy pooling, LW, walk-forward, **CPCV with purge/embargo**, transaction costs, turnover constraints | Best fit for allocation *and* leakage-safe validation in one sklearn-style package | [PyPI](https://pypi.org/project/skfolio/); [GitHub](https://github.com/skfolio/skfolio) |
| MLflow | 3.16.1 (2026-09-16) | Apache-2.0 † | "AI engineering platform for agents, LLMs, and ML models": tracing, evaluation, **prompt registry**, AI gateway | Model and prompt versioning, experiment tracking, LLM-call tracing | [PyPI](https://pypi.org/project/mlflow/) |
| Evidently | 0.7.23 (2026-09-11) | Apache-2.0 | Beta; "100+ built-in metrics from data drift detection to LLM judges"; PSI drift preset | Feature-drift and data-quality monitoring; LLM-output evals | [PyPI](https://pypi.org/project/evidently/) |
| DuckDB | 1.5.6 (2026-09-28) | MIT | In-process; Parquet/CSV/JSON; Python ≥3.10 | Primary analytical store at personal scale | [PyPI](https://pypi.org/project/duckdb/) |
| TimescaleDB (Tiger Data) | version not retrieved | Apache-2.0 core + Timescale License for `tsl` code | Hypertables, columnstore (docs at docs.tigerdata.com) | Only if Postgres is already used for the web app | [LICENSE](https://github.com/timescale/timescaledb/blob/main/LICENSE); [README](https://github.com/timescale/timescaledb) |
| Prefect | 3.8.7 (2026-09-27) | Apache-2.0 † | Scheduling, caching, retries, event-based automations; cron deployments | Robust scheduled collectors with retries and observability | [PyPI](https://pypi.org/project/prefect/) |
| Dagster | 1.13.25 (2026-10-01) | Apache-2.0 † | Asset-based orchestration with lineage and observability | Good if modelling sources → features → predictions as assets; heavier | [PyPI](https://pypi.org/project/dagster/) |
| APScheduler | 3.11.3 (2026-06-28) | MIT | Production/Stable (3.x line) | Simplest in-process cron for a single-user app | [PyPI](https://pypi.org/project/apscheduler/) |
| ArcticDB | 6.26.0 (2026-09-14) | **BSL 1.1** → Apache-2.0 two years after each version's release | "Time travel… snapshots" | Versioned time-series store. **Licence ambiguity, see next bullet** | [PyPI](https://pypi.org/project/arcticdb/); [LICENSE](https://github.com/man-group/ArcticDB/blob/master/LICENSE.txt) |
| quantstats | 0.0.86 (2026-09-27) | Apache-2.0 | Production/Stable; `kelly_criterion` among stats | Tear sheets for paper and actual books | [PyPI](https://pypi.org/project/quantstats/) |
| pyfolio-reloaded / empyrical-reloaded | 0.9.9 / 0.5.12 (June 2025) | — | Slower cadence | Alternative performance analytics | [PyPI](https://pypi.org/project/pyfolio-reloaded/) |
| pypbo | GitHub repo | — | Implements PBO, PSR, MinTRL, DSR | Overfitting statistics | [GitHub](https://github.com/esvhd/pypbo) |
| nautilus_trader | 1.231.0 (2026-08-02) | — | Python ≥3.12 | Production-grade event-driven engine; overkill for a non-automated advisor | [PyPI](https://pypi.org/project/nautilus_trader/) |
| yfinance | 1.7.0 (2026-08-26) | Apache-2.0 (code) | "Yahoo! finance API is intended for personal use only" | Prototyping prices; not for redistribution | [PyPI](https://pypi.org/project/yfinance/) |

- ArcticDB's licence text conflicts with its README:
  - LICENSE.txt "Additional Use Grant" allows use "provided that you may not use the Licensed Work for a Database Service", meaning a commercial offering that lets third parties create tables with their own schemas;
  - the README states that users "may not use ArcticDB for production use or for a Database Service, without agreement with Man Group… Use of ArcticDB in production… requires a paid for license".
  — [ArcticDB LICENSE.txt](https://github.com/man-group/ArcticDB/blob/master/LICENSE.txt); [ArcticDB on PyPI](https://pypi.org/project/arcticdb/)

### Inferences
**Recommended minimal stack for this app:**
- **Language:** Python 3.12 satisfies every library above, including nautilus_trader's ≥3.12 and vectorbt's 3.11–3.14.
- **Storage:** DuckDB file plus a Parquet raw-payload store with the append-only schema from Section 3.
- **Scheduling:** APScheduler cron jobs inside the backend for v1. Move to Prefect when retries, run history and alerts become painful.
- **Research:** alphalens-reloaded for IC; vectorbt for sweeps, where the Commons Clause only matters if the tool is sold; skfolio for CPCV/walk-forward and allocation estimators.
- **Production allocation:** a hand-written top-N, inverse-vol and caps pipeline, plus PyPortfolioOpt `DiscreteAllocation` for share rounding.
- **Evaluation:** quantstats for book tear sheets and pypbo for DSR/PBO.
- **Versioning and monitoring:** MLflow for model and prompt registry and tracing; a scheduled Evidently report for drift.

**Avoid or defer:**
- backtrader (stale, GPL);
- ArcticDB if the app may ever be shared or commercial (licence ambiguity);
- Qlib unless the app grows into ML-heavy research (heavy, alpha-status);
- TimescaleDB unless already on Postgres.

**Licence hygiene if sharing later:**
- GPL obligations attach to *distributing* software. A hosted web app generally does not distribute backend code, but check before shipping desktop builds.
- The Commons Clause forbids selling vectorbt-based services.
- The Timescale License restricts some hosted uses of `tsl` features. Its terms were not reviewed here.

### Gaps
- GitHub API metrics (stars, open issues, last commit) could not be retrieved because GitHub API access was not enabled for this session. Maturity is judged from PyPI release cadence and status classifiers only.
- TimescaleDB's latest version number and the exact feature scope of the Timescale License were not retrieved.
- Licence classifiers for MLflow, Prefect, Dagster and nautilus_trader were not printed. The Apache-2.0 attributions are from prior knowledge (†).
- Whether Qlib supports Nordic data out of the box was not checked.

---

## 6. LLM components: reproducible structured extraction of events and sentiment from announcements

### Takeaway
Treat the LLM as a **versioned, cached feature extractor**:
- log the exact model ID returned, the prompt template version and hash, the JSON schema version, the input-document hash, the full request and response, and token usage;
- use **structured outputs** with enum-typed event schemas;
- cache by (model, prompt hash, schema, input hash) so replays never re-sample;
- evaluate against a hand-labelled Norwegian/Swedish sample before and after any model or prompt change;
- control cost with the Batch API (50% off), prompt caching and a small model for classification.

**Do not trust backtests of LLM-derived features over periods inside the model's training data**, because of look-ahead and memorisation bias.

### Cited Findings
- Glasserman & Lin:
  - LLM sentiment backtests suffer from **look-ahead bias** (the model may know what happened after the news) and a **distraction effect** (general knowledge of the company contaminates the sentiment read);
  - they debias by removing company identifiers from headlines; in-sample, anonymised headlines *outperformed*, suggesting the distraction effect can outweigh look-ahead bias;
  - memorisation of training data makes historical estimates of predictive ability "likely overly optimistic".
  — [Glasserman & Lin, arXiv:2309.17322](https://arxiv.org/pdf/2309.17322); [published in *J. Financial Data Science* 6(1)](https://www.pm-research.com/content/iijjfds/6/1/25)
- Follow-up work in late 2025 proposes detection and correction methods. — ["Detecting Lookahead Bias in LLM Forecasts", arXiv:2512.23847](https://arxiv.org/html/2512.23847); ["A Fast and Effective Solution to the Problem of Look-ahead Bias in LLMs", arXiv:2512.06607](https://arxiv.org/pdf/2512.06607); ["AI's predictable memory in financial analysis", *Economics Letters* (2025)](https://www.sciencedirect.com/science/article/pii/S0165176525004392). Titles are from search results; contents were not read.
- **Structured outputs** (Anthropic API):
  - `output_config.format` constrains responses to a JSON schema, and `strict: true` on tools guarantees schema-valid tool inputs.
  - Supported models include Claude Opus 5.5, Sonnet 5.5, Haiku 4.5 and others.
  - Not supported in schemas: numeric constraints (`minimum`/`maximum`), string length constraints, recursive schemas. The Python and TypeScript SDKs strip these and validate client-side.
  - New schemas incur a one-time compilation cost and are cached for 24 hours.
  - A `refusal` or `max_tokens` stop reason can produce non-conforming output.
  - Citations are incompatible with `output_config.format` (returns a 400).
  — [Anthropic docs: Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md)
- **Determinism:**
  - On Claude Opus 4.7/4.8/5/5.5 and Fable models, `temperature`, `top_p` and `top_k` are removed; sending them returns a 400. Claude Sonnet 5.5 rejects non-default values.
  - Anthropic notes that "if you were using temperature = 0 for determinism… it never guaranteed identical outputs on prior models".
  — [Anthropic docs: Migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide.md)
- **Model versioning and lifecycle:**
  - Current models are listed by ID (for example `claude-opus-5-5`, `claude-sonnet-5-5`) with no separate dated snapshot ID; only Haiku 4.5 also shows a dated ID, `claude-haiku-4-5-20251001`.
  - Models are deprecated and retired on published dates: Claude Sonnet 3.7 and Haiku 3.5 retired 19 Feb 2026, Opus 3 on 5 Jan 2026; Opus 4.1 was deprecated with retirement on 2026-08-05.
  - The Models API returns `id`, `display_name`, `created_at`, `max_input_tokens`, `max_tokens` and `capabilities`.
  — [Anthropic docs: Models overview](https://platform.claude.com/docs/en/about-claude/models/overview.md)
- **Behaviour changes that affect extraction pipelines:**
  - On Opus 5.5 thinking cannot be disabled (effort defaults to `medium`). On Sonnet 5.5, `{type:"disabled"}` returns 400; thinking is turned off with `{type:"between_tools"}`.
  - Opus 5.5 and Sonnet 5.5 reject forced `tool_choice` (`any`/`tool`). Use structured outputs to get JSON instead.
  — [Anthropic docs: Migration guide](https://platform.claude.com/docs/en/about-claude/models/migration-guide.md)
- **Cost levers:**
  - **Message Batches** process requests asynchronously at **50% of standard prices**; up to 100,000 requests or 256 MB per batch; most finish within 1 hour (maximum 24 hours); results available for 29 days; results come back in any order and must be keyed by `custom_id`. — [Anthropic docs: Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing.md)
  - **Prompt caching:**
    - cache reads cost about 0.1× the base input price (0.05× on Opus 5.5);
    - cache writes cost 1.25× for the 5-minute TTL and 2× for the 1-hour TTL;
    - caching is prefix-based, so any byte change (for example a timestamp in the system prompt, or unsorted JSON) invalidates it;
    - the minimum cacheable prefix is 512–4,096 tokens depending on the model;
    - verify caching via `usage.cache_read_input_tokens`.
    — [Anthropic docs: Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md)
  - Prices as of the 2026-09-25 cache, per million input/output tokens: Haiku 4.5 $1/$5, Sonnet 5.5 $2/$10, Opus 5.5 $4/$20, Fable 5.1 $10/$50. — [Anthropic docs: Pricing](https://platform.claude.com/docs/en/about-claude/pricing.md)
- **Eval hygiene** (Anthropic's bundled eval checklist):
  - take token and cost accounting from the API `usage` block, not estimates;
  - validate any LLM judge against a few dozen human-labelled cases; agreement well below about 90% on clear-cut cases means the judge needs another iteration;
  - spot-check failures, and if more than about 1 in 10 are grader errors, fix the grader;
  - treat candidate text as untrusted data, not instructions;
  - noise floor of about ±1/√(n·R).
  — [Anthropic claude-api skill, `shared/evals/eval-audit.md` (bundled reference; local file)](file:///tmp/claude-0/bundled-skills/2.1.287/f5b1c635ee79464487d10d0a10cb272a/claude-api/shared/evals/eval-audit.md)
- MLflow 3.x includes a **prompt registry**, LLM tracing and evaluation. — [MLflow on PyPI](https://pypi.org/project/mlflow/). Evidently includes LLM evals and text descriptors (sentiment, length, regex). — [Evidently on PyPI](https://pypi.org/project/evidently/)
- FI's 2025 consumer-protection report flags "unserious investment advice from AI or finfluencers" as an emerging consumer risk, which matters if the tool is shared. — [FI Konsumentskyddsrapport 2025](https://www.fi.se/sv/publicerat/rapporter/konsumentskyddsrapport/konsumentskyddsrapport-2025-digitalisering-och-virala-trender-skapar-risker-for-konsumenter-pa-finansmarknaden/)

### Inferences
**Pipeline:**
1. Fetch and hash the raw announcement (Section 3).
2. Apply cheap rules first: regex/keyword triage for event types such as insider trade, guidance change, buyback, dividend, contract award, profit warning, M&A, share issue, management change. Skip the LLM for unambiguous cases.
3. Call the LLM with a **frozen system prompt**, cached as a stable prefix, and a JSON schema whose fields are mostly enums:
   - `event_type`;
   - `direction` (positive/negative/neutral);
   - `materiality` (low/med/high);
   - `is_forward_looking`;
   - `quantities[]` (value, unit, currency, period);
   - `evidence_quote`, a verbatim span, checked client-side as a substring of the input because citations cannot be combined with structured output;
   - `confidence` (low/med/high);
   - `language`.
4. Validate the result with Pydantic or JSON Schema, including the numeric ranges the API does not enforce.
5. Store the result in `llm_call` and `event`.

**Reproducibility:**
- Use the cache key (model_returned, prompt_sha256, schema_version, input_sha256) and never re-call for an existing key. Backtests then read stored outputs, which makes them reproducible even though sampling is not deterministic.
- Re-extraction under a new model or prompt is a *new* feature version, evaluated as a challenger.

**Labelled evaluation set:**
- Hand-label about 300–500 Norwegian and Swedish announcements, stratified by event type and by language (NO/SE/EN). Double-label a subset to estimate human agreement.
- Report per-class precision/recall/F1, direction accuracy, and materiality agreement.
- Keep a frozen test split. Re-run the eval on every model or prompt change, and on any model deprecation notice.
- Add adversarial cases: prompt-injection text inside announcements, and English–Norwegian duplicates.

**Backtest contamination rule:**
- Mark LLM-derived features computed on documents dated *before* the model's training cutoff as `contaminated = true`. Treat their backtest IC as an **upper bound**.
- Rely on **post-deployment (forward) logging** for the real evaluation.
- Also try the anonymisation ablation (strip issuer names and tickers) to measure the distraction effect.

**Cost example** (illustrative, using the cached prices above): 200 announcements per trading day × about 1,500 input + 300 output tokens.

| Model | Standard cost per day | Batch cost per day | Per month (Batch) |
|---|---|---|---|
| Haiku 4.5 | ≈ $0.60 (0.3 MTok × $1 + 0.06 MTok × $5) | ≈ $0.30 | under $10 |
| Sonnet 5.5 | ≈ $1.20 | ≈ $0.60 | — |

Thinking tokens add to output cost on models where thinking is always on (Opus 5.5), so use Haiku 4.5 or Sonnet 5.5 with thinking off or low effort for bulk extraction. Escalate only low-confidence cases to a larger model. Set a monthly budget alarm based on logged usage.

**Latency vs cost:** use the Batch API for nightly backfills and re-extractions. Use direct calls only for intraday items that feed the short-term sleeve.

### Gaps
- No published accuracy benchmark for LLM event extraction on Norwegian or Swedish exchange announcements was found.
- No Nordic evidence was found that LLM sentiment adds out-of-sample alpha after costs. This belongs to the signal research stream.
- The exact training cutoffs of current Claude models were not retrieved. These are needed to set the `contaminated` flag.
- The contents of the 2025 look-ahead-bias papers (arXiv:2512.06607, 2512.23847) were not read.

---

## 7. Regulatory and legal: Norway and Sweden, personal use vs sharing (MiFID II investment advice, MAR art. 20 investment recommendations, GDPR for insider names, exchange-data licensing, market-abuse risks)

### Takeaway
**Personal use** carries little regulatory exposure beyond:
- the market-abuse prohibitions that apply to everyone;
- data-source terms (for example Yahoo data is personal-use only);
- GDPR's narrow household exemption.

**Sharing changes everything**, in three ways:
1. Allocations personalised to a user's inputs (such as account value) are likely **personal recommendations, i.e. investment advice requiring a licence** from Finanstilsynet or FI. The exception for recommendations "issued exclusively to the public" is narrow, and internet distribution can still be personal.
2. Any output distributed to the public or via distribution channels is an **"investment recommendation" under MAR art. 20**, which **also applies to private persons**. It requires identity, objective presentation (facts vs opinions) and disclosure of interests and positions.
3. Redistributing exchange prices and storing insider names for others brings in licensing and full GDPR obligations.

### Cited Findings
**MiFID II (applies in Norway via the EEA):**
- "Investment advice" means the provision of personal recommendations to a client, on request or at the firm's initiative, in respect of transactions in financial instruments. — [ESMA35-43-3861 Supervisory briefing on the definition of advice under MiFID II (July 2023)](https://www.esma.europa.eu/sites/default/files/2023-07/ESMA35-43-3861_Supervisory_briefing_on_understanding_the_definition_of_advice_under_MiFID_II.pdf). This briefing revised ESMA's 13-year-old guidance. — [Lexology summary](https://www.lexology.com/library/detail.aspx?g=842aa401-3d6a-4a0a-a13b-90ee8496d79c)
- Under Art. 9 of Delegated Regulation 2017/565, a recommendation is personal if it is presented as suitable for that person or based on a consideration of that person's circumstances. A recommendation "is not a personal recommendation if it is issued exclusively to the public". — [Delegated Regulation (EU) 2017/565 (EUR-Lex PDF)](https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:32017R0565)
- Under MiFID II, a recommendation issued, even exclusively, through distribution channels such as the internet *could* qualify as a personal recommendation. Recommendations to a large number of people, but not to the public at large, amount to personal recommendations. — [Hogan Lovells MiFID II briefing (PDF)](https://www.hoganlovells.com/~/media/hogan-lovells/pdf/mifid/subtopic-pdf/12mifid_ii_summary_-_investor_protection___investment_advice_and_the_use_of_distribution_channels-bzezw.pdf); [Hogan Lovells MiFID II investment advice update (PDF)](https://www.hoganlovells.com/~/media/hogan-lovells/pdf/mifid/new_mifid_update_31_dec_2016/mifid-ii-investment-advice-distribution-channels2.pdf)
- An "investment firm" is a legal person whose regular occupation or business is providing investment services to third parties and/or performing investment activities on a professional basis (MiFID II Art. 4(1)(1)). — [Directive 2014/65/EU †](https://eur-lex.europa.eu/eli/dir/2014/65/oj)

**Sweden (FI):**
- No education or permission is required to give general economic advice on social media. But giving **individually tailored advice about stocks or funds requires permission from FI**, which means applying for advisory business and meeting knowledge requirements. — [FI: "Fem saker en finfluencer måste veta"](https://www.fi.se/sv/for-konsumenter/spara/till-dig-som-ar-finfluencer/); [FI: finfluencers consumer page](https://www.fi.se/sv/for-konsumenter/spara/finfluencers/)
- FI warns that consumers increasingly seek investment advice via social media and **AI services**. More than one in five people aged 20–29 trust finfluencer tips, and international studies find that following finfluencers often underperforms an index. — [FI Konsumentskyddsrapport 2025](https://www.fi.se/sv/publicerat/rapporter/konsumentskyddsrapport/konsumentskyddsrapport-2025-digitalisering-och-virala-trender-skapar-risker-for-konsumenter-pa-finansmarknaden/); [TV4 report on FI campaign](https://www.tv4.se/artikel/2NC59bbmgijCBwm8lWlCvA/finansinspektionen-varnar-unga-foer-finfluencers-risk-foer-ekonomiska)
- Securities business, including investment advice, may be conducted only with FI authorisation (lag (2007:528) om värdepappersmarknaden, ch. 2 §1 †). — [SFS 2007:528 at Riksdagen †](https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/lag-2007528-om-vardepappersmarknaden_sfs-2007-528/)

**Norway (Finanstilsynet), MAR art. 20:**
- The investment-recommendation rules apply to anyone who recommends investments in financial instruments listed on a marketplace. Shares, derivatives, bonds and fund units are covered; crypto is largely excluded.
- **Both professional and non-professional actors** must follow the form and content rules.
- An investment recommendation is information intended for distribution channels or the public that recommends or suggests an investment strategy, explicitly or implicitly, about instruments or issuers. An assessment shared on social media of how a share price will develop can be one.
- Requirements: identify who made the recommendation; present it objectively, clearly separating facts from opinions; disclose own interests and conflicts.
- Breaches can be sanctioned with administrative fines (overtredelsesgebyr) under the Securities Trading Act. One search summary cites § 21-1(1); this was not verified against Lovdata.
— [Finanstilsynet (2021): "Regler for investeringsanbefalinger gjelder for finfluensere"](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2021/regler-for-investeringsanbefalinger-gjelder-for-finfluensere/); [Finanstilsynet: Investeringsanbefalinger](https://www.finanstilsynet.no/tilsyn/markedsatferd/investeringsanbefalinger/)
- In 2022 Finanstilsynet clarified that the rules **also apply to private persons**. It noted that many private persons do not realise that discussing financial instruments can be an investment recommendation, and urged everyone who disseminates recommendations, including private persons, to learn the MAR art. 20 and Delegated Regulation 2016/958 rules. — [Finanstilsynet (2022)](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2022/finanstilsynet-presiserer-at-reglene-for-investeringsanbefalinger-ogsa-gjelder-for-privatpersoner/)
- Finanstilsynet published further guidance in 2024 (relaying an ESMA warning) and in 2026 ("Råd til deg som deler informasjon om investeringer på sosiale medier"), plus a finfluencer fact sheet. — [Finanstilsynet 2024 news](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2024/investeringsanbefalinger-som-legges-ut-pa-sosiale-medier--advarsel-fra-esma/); [Finanstilsynet 2026 news](https://www.finanstilsynet.no/nyhetsarkiv/nyheter/2026/rad-til-deg-som-deler-informasjon-om-investeringer-pa-sosiale-medier/); [Finanstilsynet finfluencer fact sheet (PDF)](https://www.finanstilsynet.no/globalassets/investorinformasjon/finfluenser-faktaark2.pdf)
- Finanstilsynet licenses investment firms (verdipapirforetak). — [Finanstilsynet: Verdipapirforetak (konsesjon)](https://www.finanstilsynet.no/konsesjon/verdipapirforetak/). The licensing requirement is in verdipapirhandelloven ch. 9 (§ 9-1 †), and MAR has applied in Norway via verdipapirhandelloven ch. 3 since 1 March 2021 †. — [Finanstilsynet commentary on vphl ch. 3–4 (PDF)](https://www.finanstilsynet.no/globalassets/regelverk/markedsatferd/lov-om-verdipapirhandel---enkelte-kommentarer-til-kapittel-3-og-4.pdf)

**EU-level MAR art. 20 and ESMA statements:**
- Delegated Regulation 2016/958:
  - **all** producers and disseminators must have arrangements for objective presentation and disclosure;
  - producers must disclose all relationships and circumstances that may reasonably be expected to impair objectivity;
  - independent analysts, investment firms, credit institutions, persons whose main business is producing recommendations, and **"experts"** must *additionally* disclose net long or short positions above a threshold in the issuer's share capital.
  — [Delegated Regulation (EU) 2016/958 (EUR-Lex)](https://eur-lex.europa.eu/eli/reg_del/2016/958/oj/eng); [EEA-Lex factsheet 32016R0958](https://www.efta.int/eea-lex/32016r0958)
- Details of 2016/958 †:
  - an "expert" is a person who **repeatedly proposes investment decisions** and presents themselves as having financial expertise, or presents recommendations so that others would reasonably believe they have it;
  - the position-disclosure threshold is a net long or short position exceeding **0.5%** of total issued share capital.
  — [2016/958 †](https://eur-lex.europa.eu/eli/reg_del/2016/958/oj/eng)
- On 28 October 2021 ESMA issued a public statement on investment recommendations on social media:
  - recommendations must be objective and transparent so investors can tell facts from opinions;
  - investors must be able to identify the source and any conflicts of interest;
  - breaches can bring fines, and dissemination of false or misleading information may be referred to prosecutors as market manipulation.
  — [ESMA news (2021)](https://www.esma.europa.eu/press-news/esma-news/esma-addresses-investment-recommendations-made-social-media-platforms); [ESMA press release PDF](https://www.esma.europa.eu/sites/default/files/library/esma71-99-1752_press_release_-_esma_addresses_investment_recommendations_made_on_social_media_platforms.pdf)
- ESMA published a "Finfluencers: Tips for responsible promotion" factsheet in January 2026, with language versions including Swedish. Content was not read. — [ESMA finfluencers factsheet (EN, 2026-01)](https://www.esma.europa.eu/sites/default/files/2026-01/Finfluencers_factsheet_EN.pdf); [SV version](https://www.esma.europa.eu/sites/default/files/2026-01/SV_Sweden_sv_-_Finfluencers_factsheet.pdf)

**MAR market-abuse provisions (Regulation (EU) 596/2014) †:**
- Art. 8(4): insider dealing applies to anyone holding inside information who "knows or ought to know" it is inside information.
- Art. 12(1)(c): disseminating false or misleading information, including rumours, is market manipulation.
- Art. 12(2)(d): **"scalping"**, meaning voicing an opinion about an instrument via media after taking a position and profiting from the price impact without properly disclosing the conflict, is market manipulation.
- Arts. 14–15 prohibit insider dealing and market manipulation for **all persons**, not just professionals.
— [MAR on EUR-Lex †](https://eur-lex.europa.eu/eli/reg/2014/596/oj)

**GDPR household exemption:**
- The exemption (Art. 2(2)(c)) is narrow. In *Lindqvist* (C-101/01) the CJEU held that publishing personal data on the internet so it is accessible to an indefinite number of people is not a purely personal activity. *Ryneš* (C-212/13) confirmed the exemption's narrowness: home CCTV capturing public space is not covered. — [GDPRhub: Article 2 GDPR](https://gdprhub.eu/Article_2_GDPR); [JIPITEC article on the household exemption](https://www.jipitec.eu/jipitec/article/download/364/357/1890)
- Personal data stays personal data even when published in public registers. If the exemption does not apply, the controller needs a lawful basis such as legitimate interests (Art. 6(1)(f)) and must meet transparency duties for data not obtained from the data subject (Art. 14, with the disproportionate-effort exception in Art. 14(5)(b)). — [GDPR (Regulation (EU) 2016/679) †](https://eur-lex.europa.eu/eli/reg/2016/679/oj)

**Exchange-data licensing:**
- **Euronext (Oslo Børs):**
  - Euronext must provide delayed data (published ≥15 minutes after initial publication) free of charge under MiFID II;
  - internal, non-commercial use of delayed data is free and usually needs no licence;
  - redistribution of **real-time** data needs a licence and fees;
  - for **delayed** redistribution with no direct economic benefit and no charge to third parties, the Delayed Redistribution Licence / White Label Fee does not apply *provided this is indicated in the EMDA Order Form*.
  — [Euronext market-data fees and policies](https://www.euronext.com/en/data/market-data/market-data-pricing-policies); [Euronext Market Data Agreement (EMDA) Jan 2025 (PDF)](https://connect2.euronext.com/sites/default/files/documentation/data/EMDA%20General%20Terms%20and%20Conditions%20and%20Policies%20(effective%20January%202025)_0.pdf); [Euronext MiFID II data page](https://www.euronext.com/en/data/market-data/mifid-ii)
- **Nasdaq Nordic (Stockholm):**
  - use of delayed data is generally free, and non-commercial use is free;
  - commercial use may be fee-liable;
  - data delayed by less than 15 minutes counts as real-time;
  - commercial redistribution of 15-minute-delayed Nordic data uses a "Nordic Delayed Unbundled Data Redistributor" licence.
  — [Nasdaq European Data Policies v1.5.3 (Jan 2026)](https://www.nasdaq.com/docs/Nasdaq_European_Data_Policies_January_2026_New); [Nasdaq Nordic MiFID II delayed data](https://www.nasdaq.com/market-regulation/nordic/mifid-ii); [Nasdaq European exchange data price list (Jan 2025)](https://www.nasdaq.com/docs/exchange-data-price%20list-january-2025)
- **yfinance / Yahoo:** yfinance "is not affiliated, endorsed, or vetted by Yahoo", is "intended for research and educational purposes", users "should refer to Yahoo!'s terms of use", and "the Yahoo! finance API is intended for personal use only". — [yfinance on PyPI](https://pypi.org/project/yfinance/)

### Inferences
**Decision matrix.** This is not legal advice; confirm with a Norwegian or Swedish financial-regulatory lawyer before sharing.

| Scenario | MiFID licence (investment advice)? | MAR art. 20 duties? | Exchange data | GDPR (insider names) |
|---|---|---|---|---|
| **Personal use only** (own account, not published) | No: not a service to third parties | No: not intended for distribution channels or the public | Internal use of delayed data free (Euronext/Nasdaq); Yahoo personal use OK | Likely household exemption. Still minimise and secure |
| **Screenshots or posts of suggestions** on forums, Shareville, Discord, X | Generally no (not personalised), unless tailored to a person | **Yes**: identity, facts vs opinion, conflicts/positions; "expert" duties if repeated and presented as expert | Posting prices is usually fine at small scale but technically display/redistribution | Do not publish insider names unnecessarily |
| **Shared app where each user enters their account value and gets an allocation** | **Likely yes**: "based on consideration of the person's circumstances"; FI says tailored advice needs permission. Internet distribution does not save it | Yes, if also published | Redistribution: Euronext EMDA order form; Nasdaq licence if commercial; **no Yahoo-sourced prices** | Not household; full controller duties |
| **Public generic "model portfolio" page** (same for everyone, no inputs) | Arguably not personal if "exclusively to the public"; keep it non-interactive | **Yes** | Delayed-display licensing as above | Controller duties if names shown |
| **Paid subscription** | Licence (or operating under a licensed firm) very likely needed for any personalisation | Yes; "expert" status likely | Commercial redistribution fees; vectorbt Commons Clause conflicts | Full GDPR |

**If the app is shared later**, keep these design choices open from day one:
1. A strict **non-personalised mode**: identical output for all users, with no account-value input, or an account-value input used only for client-side share rounding *after* a generic weight list. Even the latter may count as tailoring; obtain advice.
2. Every published output carries producer identity, timestamp, model version, a facts-vs-model-opinion split, data sources, the risk of the strategy, and the **operator's own positions**.
3. A **personal trading blackout** around publication, for example no trading in recommended names from T−2 to T+2 trading days, to avoid scalping (art. 12(2)(d)).
4. An append-only publication log, which the Section 3 schema already provides, to show what was published and when.
5. A liquidity floor on anything published, so the app never promotes illiquid micro-caps that are prone to pump-and-dump dynamics.

**Market-abuse hygiene even for personal use:**
- Ingest only **officially published** information: exchange news services, issuer releases, regulators' insider registers.
- Tag every input with provenance and treat forum and chat content as sentiment only, never as a factual trigger.
- If a forum post appears to reveal precise, non-public, price-sensitive information (for example an unannounced contract or a bid), the app should **flag and block** trading in that name. Under art. 8(4) the test is whether one "knows or ought to know".
- Never post buy recommendations on stocks you hold without disclosure.

**GDPR for insider (PDMR) names:**
- Personal use: keep the data local and access-controlled. Data minimisation is still good practice.
- If shared:
  - store role (CEO/CFO/board/closely associated person), issuer, transaction type, size and dates;
  - key repeated filers by a **salted hash of the name** rather than displaying names;
  - set a retention period (for example 3–5 years for signal history);
  - document a legitimate-interest balancing test;
  - publish a privacy notice (relying on Art. 14(5)(b) where individual notice is disproportionate);
  - honour objection and erasure requests.
- The supervisory authorities are Datatilsynet (Norway) and IMY (Sweden).

**Data-source terms:** for a shared deployment, replace Yahoo-sourced prices with a licensed or exchange-sanctioned delayed feed, or display only derived outputs (weights, scores). Exchange "derived data" policies may still apply; see Gaps.

### Gaps
- The exact section numbers, current wording and penalty provisions of verdipapirhandelloven (Norway) and lagen om värdepappersmarknaden (Sweden) could not be verified because Lovdata and Riksdagen were blocked. In particular, the criminal penalties for unlicensed investment advice and the exact overtredelsesgebyr provision are unverified.
- Unresolved: whether a **free, non-commercial** shared tool meets MiFID's "regular occupation or business… on a professional basis" test. No Norwegian or Swedish authority statement on hobby or free advice tools was found. FI's statement on tailored advice does not mention payment.
- The ESMA 2023 advice briefing's specific treatment of online tools, robo-advice and disclaimers, and the content of the ESMA 2026 finfluencer factsheet, were not read (ESMA blocked).
- Not researched:
  - the status of the EU Retail Investment Strategy (finfluencer and marketing rules) as of October 2026;
  - Listing Act changes to MAR and their EEA incorporation timing for Norway;
  - Datatilsynet or IMY guidance specific to republishing PDMR/insider data;
  - Sweden's "utgivningsbevis" (publishing certificate) route that can take some databases outside GDPR.
- Exchange "derived data" and non-display licensing terms (for example computing signals from real-time feeds), Nordnet's API and website terms, and the terms of other sources (Newsweb, MFN, FI insider register) were not reviewed.
