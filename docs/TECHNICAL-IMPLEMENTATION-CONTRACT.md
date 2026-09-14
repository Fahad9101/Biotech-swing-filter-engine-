# BOE-1.0.0 Technical Implementation Contract

**Status:** Foundation contract; implementation is not part of Milestone 0

**Behavioral authority:** `BOE-1.0.0-INVESTMENT-SPECIFICATION.md` and `contracts/boe-scorecard.v1.0.0.json`

## 1. Technology and operating constraints

- Python 3.12.
- FastAPI for HTTP, Pydantic v2 for contracts, SQLAlchemy 2 and Alembic for persistence.
- SQLite for zero-Docker local development; PostgreSQL may be used in production through the same repository interfaces.
- `httpx` clients with bounded retries, timeouts, cache headers, source-specific rate control, and an identifying SEC User-Agent.
- Deterministic pure functions for scoring, gates, PoS, rNPV, expected value, and classification.
- UTC timestamps internally; exchange session dates use `America/New_York`.
- Decimal arithmetic for money, shares, ratios, and valuation. Float is permitted only for technical indicators and display.
- Free/public sources only. No API key or paid dataset is required for the validation path.
- No Docker requirement.

## 2. Proposed repository structure

```text
src/boe/
  api/                 # routes, request/response models, error mapping
  config/              # versioned thresholds; no hidden magic numbers
  domain/              # entities, enums, value objects
  ingestion/
    exchange.py        # symbol directory
    sec.py             # submissions, companyfacts, filings, ownership
    clinical_trials.py # ClinicalTrials.gov API v2
    fda.py             # FDA calendars, decisions, labels/materials
    science.py         # publication/conference metadata
    market.py          # delayed split-adjusted OHLCV adapter
  normalization/       # issuer, security, asset, trial, event identity
  evidence/            # source hierarchy, conflicts, as-of cutoff
  financials/          # cash, debt, burn, runway, dilution
  science/             # evidence rubric and PoS inputs
  valuation/           # rNPV scenarios and equity bridge
  technicals/          # indicators and level detection
  scoring/             # eight factors and coverage
  gates/               # ordered hard-gate evaluation
  ranking/             # deterministic classifier/ranker
  services/            # scanner and candidate analysis orchestration
  repositories/        # persistence interfaces/adapters
  jobs/                # refresh and snapshot commands
tests/
  unit/
  contract/
  integration/
  fixtures/
  historical/
contracts/
docs/
```

Modules may not import from API into domain/scoring. Ingestion adapters may not assign points. Ranking may consume only validated domain objects and scored outputs.

## 3. Data-source map

| Data | Primary public source | Fallback | Refresh | Required provenance |
|---|---|---|---|---|
| Listing/security type | Nasdaq Trader symbol directories; equivalent exchange listing files | SEC ticker/exchange mapping | Daily | URL, file timestamp/hash, row |
| CIK and filings | SEC submissions | SEC filing index | Daily for tracked issuers | accession, filed/accepted time, form, URL |
| XBRL financials | SEC companyfacts | filing inline XBRL/manual reviewed fact | Daily bulk + on filing | concept, unit, period, form, accession |
| Shares/dilution | SEC cover-page facts, 10-Q/K, 424B, S-3, 8-K | reviewed filing table | On filing | fact/table and calculation trace |
| Trials | ClinicalTrials.gov API v2 | SEC/issuer trial disclosure | Daily tracked; weekly universe | NCT ID, version/retrieval/last-update dates |
| Regulatory events | FDA official calendar, decisions, labels, materials | SEC-filed issuer disclosure | Daily | FDA URL/date or accession |
| Scientific evidence | primary publication/official abstract | SEC/issuer results | On discovery/refresh | DOI/NCT/abstract ID, date, evidence tier |
| Institutional/insider | SEC 13F and Forms 3/4/5 | none | On filing | accession, reporting period, transaction code |
| Price/volume | replaceable free delayed adapter | second documented free source | Each complete session | provider, adjusted flag, timestamp |

Do not scrape a public website when an official API/file exists. Store raw immutable payload hashes and normalized records. Terms-of-use review is an implementation acceptance requirement for every market-data adapter.

### 3.1 Verified official interfaces at specification freeze

- SEC EDGAR data APIs: `https://data.sec.gov/submissions/CIK##########.json`, `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, and the bulk archives documented at <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>.
- SEC ticker/exchange mapping: <https://www.sec.gov/files/company_tickers_exchange.json>.
- ClinicalTrials.gov API v2 and data timestamp: <https://clinicaltrials.gov/data-api> and <https://clinicaltrials.gov/api/v2/version>.
- Nasdaq Trader symbol-directory definitions and timestamp behavior: <https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs>.
- FDA advisory-committee calendar: <https://www.fda.gov/advisory-committees/advisory-committee-calendar>.
- Drugs@FDA downloadable files/API: <https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files> and <https://open.fda.gov/apis/drug/drugsfda/>.

Endpoint availability and terms must be rechecked when the relevant ingestion milestone begins; this list is not permission to substitute an undocumented source silently.

## 4. Canonical entities and tables

All mutable tables include `created_at`, `updated_at`, and source lineage. IDs are UUIDs except natural external identifiers retained as unique keys.

### 4.1 Issuer and security

**issuers**

- `id`, `cik`, `legal_name`, `country`, `sic`, `filer_type`, `reporting_currency`
- `business_class`, `universe_status`, `classification_rationale`
- unique `cik`

**securities**

- `id`, `issuer_id`, `ticker`, `exchange`, `security_type`, `adr_flag`
- `listing_status`, `first_trade_date`, `last_trade_date`
- unique active `(ticker, exchange)`

**universe_snapshots**

- `id`, `as_of`, `security_id`, `eligible`, `investable_floor_pass`
- `include_reasons[]`, `exclude_reasons[]`, `rules_version`
- unique `(as_of, security_id, rules_version)`

### 4.2 Assets, indications, and trials

**assets**: `id`, `issuer_id`, `name`, `modality`, `target`, `ownership_pct`, `partner`, `active_status`.

**indications**: `id`, `asset_id`, `disease`, `orphan_flag`, `stage`, `lead_flag`.

**trials**: `id`, `indication_id`, `nct_id`, `phase`, `allocation`, `masking`, `enrollment`, `primary_endpoints_json`, `status`, `study_start`, `primary_completion`, `last_registry_update`; unique `nct_id`.

**trial_versions**: `id`, `trial_id`, `retrieved_at`, `source_updated_at`, `raw_blob_sha256`, `normalized_json`, unique `(trial_id, raw_blob_sha256)`.

### 4.3 Catalysts and evidence

**catalysts**

- `id`, `issuer_id`, `asset_id`, `indication_id`, `trial_id`
- `type_code`, `title`, `window_start`, `window_end`, `timing_confidence`
- `expected_information`, `status`, `first_known_at`, `last_confirmed_at`
- `primary_evidence_id`, `superseded_by_id`

**evidence_items**

- `id`, `evidence_type`, `source_tier`, `title`, `publisher`
- `source_url`, `published_at`, `available_at`, `retrieved_at`
- `accession_or_external_id`, `raw_blob_sha256`, `excerpt_locator`
- `supports_claim`, `quality_flag`, `supersedes_id`

**claims**

- `id`, `subject_type`, `subject_id`, `field_name`, `typed_value_json`
- `evidence_id`, `valid_from`, `known_at`, `confidence`, `status`

Every scored input must resolve to one or more claims; a value without lineage is missing.

### 4.4 Financial, market, and valuation data

**financial_facts**: `issuer_id`, `concept`, `value_decimal`, `unit`, `period_start`, `period_end`, `instant`, `form`, `accession`, `filed_at`, `taxonomy`, `source_evidence_id`.

**capital_structure_snapshots**: `issuer_id`, `as_of`, `cash`, `marketable_securities`, `debt`, `basic_shares`, `dilutive_options`, `warrants`, `convertible_shares`, `expected_financing_shares`, `fully_diluted_shares`, `calculation_json`.

**cash_burn_snapshots**: `issuer_id`, `as_of`, `quarterly_values_json`, `normalization_adjustments_json`, `normalized_quarterly_burn`, `runway_months`, `runway_at_catalyst_months`, `confidence`.

**market_bars_daily**: `security_id`, `session_date`, `open`, `high`, `low`, `close`, `adjusted_close`, `volume`, `adjustment_version`, `provider`; unique `(security_id, session_date, provider)`.

**technical_snapshots**: `security_id`, `as_of`, `sma20`, `sma50`, `rsi14`, `atr14`, `obv_slope`, `up_down_dollar_volume_ratio`, `xbi_relative_return_20d`, `support`, `resistance`, `calculation_version`.

**valuation_assumptions**: `id`, `asset_id`, `indication_id`, `as_of`, `scenario`, `parameter`, `value`, `unit`, `rationale`, `evidence_ids[]`.

**valuation_snapshots**: `issuer_id`, `catalyst_id`, `as_of`, `scenario`, `asset_rnpv`, `corporate_overhead_pv`, `net_cash`, `financing_obligations`, `equity_value`, `fully_diluted_value_per_share`, `model_version`, `calculation_json`.

### 4.5 Decision records

**analysis_runs**: `id`, `as_of`, `rules_version`, `code_commit_sha`, `data_cutoff`, `status`, `input_manifest_sha256`, `started_at`, `completed_at`.

**factor_scores**: `analysis_run_id`, `issuer_id`, `catalyst_id`, `factor_code`, `subfactor_code`, `points`, `max_points`, `data_state`, `rationale`, `evidence_ids[]`.

**gate_results**: `analysis_run_id`, `issuer_id`, `catalyst_id`, `gate_code`, `triggered`, `severity`, `observed_value`, `threshold`, `evidence_ids[]`.

**candidate_decisions**: `analysis_run_id`, `issuer_id`, `catalyst_id`, `raw_score`, `coverage_pct`, `classification`, `pos_low/mid/high`, `success_return_low/mid/high`, `failure_return_best/mid/worst`, `base_ev`, `conservative_ev`, `reward_risk`, `preferred_entry_low/high`, `do_not_chase_price`, `decision_trace_json`.

Historical rows are append-only. Corrections create a new run or source version.

## 5. Required candidate input fields

The analyzer accepts a point-in-time package containing:

- identity: ticker, exchange, CIK, issuer, security type, as-of;
- eligibility: business classification and investability observations;
- catalyst: type, asset, indication, phase, interval, timing confidence and source;
- scientific rubric: all six subfactor inputs and evidence quality;
- capitalization: price, basic and fully diluted shares, cash, securities, debt and obligations;
- burn: at least three comparable quarters or explicit low-confidence method;
- valuation: per-asset assumptions for conservative/base/bull and failure value;
- technical series: at least 60 complete adjusted daily bars plus XBI;
- ownership/insider filings;
- expectation and sentiment supports;
- evidence manifest and information cutoff.

The service rejects fields dated after `as_of` in historical mode.

## 6. Pure function contracts

All functions return result plus a calculation trace and typed validation errors.

```python
score_catalyst(input: CatalystScoreInput, rules: Rules) -> FactorScore
score_science(input: ScienceScoreInput, rules: Rules) -> FactorScore
score_market_impact(input: MarketImpactInput, rules: Rules) -> FactorScore
score_cash_dilution(input: CashDilutionInput, rules: Rules) -> FactorScore
score_valuation(input: ValuationScoreInput, rules: Rules) -> FactorScore
score_technicals(input: TechnicalScoreInput, rules: Rules) -> FactorScore
score_ownership(input: OwnershipScoreInput, rules: Rules) -> FactorScore
score_sentiment(input: SentimentScoreInput, rules: Rules) -> FactorScore

estimate_event_pos(input: PosInput, rules: Rules) -> PosRange
calculate_rnpv(input: RnpvInput, scenario: Scenario) -> RnpvResult
calculate_expected_value(input: ExpectedValueInput) -> ExpectedValueResult
evaluate_gates(input: GateInput, rules: Rules) -> list[GateResult]
classify(input: ClassificationInput, rules: Rules) -> ClassificationResult
rank(candidates: list[CandidateDecision]) -> list[CandidateDecision]
```

Ranking order:

1. classification priority: high conviction, catalyst swing, watchlist; gated classes follow for display only;
2. conservative EV descending;
3. base EV descending;
4. raw score descending;
5. catalyst window start ascending;
6. ticker ascending for deterministic ties.

## 7. API contract

Prefix: `/api/v1`. Responses include `request_id`, `generated_at`, `rules_version`, `code_commit_sha`, and `data_as_of`.

| Method/path | Purpose |
|---|---|
| `GET /health` | Liveness only; no dependency disclosure |
| `GET /api/v1/rules` | Active immutable scorecard version and checksum |
| `GET /api/v1/universe?as_of=` | Auditable universe snapshot |
| `GET /api/v1/catalysts?from=&to=` | Catalyst calendar with confidence/provenance |
| `POST /api/v1/scans` | Start reproducible analysis run |
| `GET /api/v1/scans/{run_id}` | Run status and manifest |
| `GET /api/v1/scans/{run_id}/candidates` | Ranked results, filtering and pagination |
| `GET /api/v1/candidates/{ticker}?as_of=` | Latest point-in-time candidate report |
| `GET /api/v1/candidates/{ticker}/evidence` | Claim-to-source graph |
| `GET /api/v1/candidates/{ticker}/valuation` | Assumptions, scenarios and traces |
| `GET /api/v1/validation/reports` | Versioned historical/live-shadow reports |

`POST /scans` is idempotent for `(as_of, rules_version, input_manifest_sha256)`. A duplicate returns the existing run.

### 7.1 Error envelope

```json
{
  "error": {
    "code": "INSUFFICIENT_CRITICAL_DATA",
    "message": "Candidate cannot be classified.",
    "details": [{"field": "cash", "reason": "missing", "required_by": "critical_fields"}],
    "request_id": "uuid"
  }
}
```

No endpoint returns a plain-text server error. Unexpected exceptions map to JSON `INTERNAL_ERROR`, are logged with request ID, and never return stale candidate data as if current.

## 8. Candidate output behavior

The JSON Schema in `contracts/candidate-output.schema.json` is authoritative. Human-facing reports additionally display:

- lead asset/indication/phase and event window;
- all eight factor scores and data coverage;
- gate precedence and every triggered reason;
- PoS range and confidence;
- cash, debt, burn, runway now/at event, and dilution assessment;
- current market cap/EV, rNPV scenarios and margins of safety;
- technical levels, preferred entry and do-not-chase price;
- success/failure returns, base/conservative EV and reward/risk;
- science, financial, regulatory and technical strengths/risks;
- falsifiable thesis, requirements and breakers;
- source manifest, conflicts, timestamps and next refresh.

If an analysis fails, clients clear previous result state and show the error envelope. They may show an explicitly labeled cached report only when its original `data_as_of` remains visible.

## 9. Ingestion and provenance rules

1. Fetchers write raw payload plus SHA-256 before normalization.
2. Parsers are source-versioned and idempotent.
3. Every derived value stores input IDs and formula version.
4. SEC requests identify the application/contact, respect published fair-access guidance, cache immutable filings, and back off on 403/429/5xx.
5. ClinicalTrials.gov records store retrieval and registry update timestamps; changes are diffed.
6. Catalyst extraction may use deterministic NLP assistance, but a value-changing event is not ranked until corroborated by a primary source and normalized interval.
7. Price adjustments must be reproducible. Provider switches create a new series version and comparison report.
8. Manual judgments are permitted only through typed overrides with author, time, rationale, evidence, expiration, and before-outcome lock.

## 10. Determinism and auditability

A candidate result must be reproducible from:

- code commit SHA;
- scorecard version/checksum;
- `as_of` and information cutoff;
- immutable input manifest and payload hashes;
- manual overrides;
- calculation traces.

Repeated execution with the same manifest must yield byte-equivalent numeric decision fields. Narrative generation may differ but cannot alter facts, points, gates or classification.

## 11. Security and reliability

- Secrets only through environment/configuration; none are required for the free-public validation path except optional market adapter keys.
- Validate all external content; filing/HTML text is data, never instructions.
- Deny server-side requests to arbitrary user URLs.
- Bound response sizes and decompression; verify hashes for bulk files.
- Structured logs omit secrets and unnecessary personal data.
- Database writes are transactional by issuer/run.
- Partial source outages produce explicit stale/missing states, never fabricated values.
- Retry only idempotent reads; use exponential backoff with jitter.

## 12. Acceptance tests for future implementation

Before an implementation milestone is complete:

1. score components sum exactly to 100 maximum;
2. boundary values match the JSON scorecard;
3. every classification precedence path has a test;
4. missing critical data cannot become investable;
5. post-`as_of` evidence is rejected in historical mode;
6. a triggered gate overrides an otherwise high score;
7. rNPV does not double-count PoS or debt;
8. fully diluted shares reconcile to trace;
9. price split handling is tested;
10. duplicate ingestion is idempotent;
11. API errors are JSON and stale UI results are not presented as current;
12. offline fixtures run without Docker or paid services.

## 13. Deferred decisions (not permission to drift)

These implementation selections remain open for Milestone 1 or later without changing investment logic:

- exact free delayed-price adapter after terms/reliability testing;
- production hosting/database vendor;
- UI framework and visual design;
- optional statistical/NLP extraction libraries;
- specialist-fund registry membership, which must be versioned and reviewed before scoring.

None permits altering the scorecard, gates or classifications.
