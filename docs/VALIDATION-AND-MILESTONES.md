# BOE-1.0.0 Validation, Governance, and Milestones

## 1. Validation objective

Validation must determine whether BOE separates favorable, survivable catalyst setups from dangerous speculation using only information available before each event. Demonstrating a list of winners is not validation.

Primary questions:

1. Are catalyst dates and data provenance reliable enough for point-in-time analysis?
2. Are event PoS ranges calibrated rather than merely plausible?
3. Do gates reduce severe losses and dilution traps?
4. Do higher BOE ranks correspond to better risk-adjusted post-event outcomes?
5. Can results be reproduced without paid data or Docker?

## 2. Frozen historical cohort protocol

### 2.1 Sampling frame

Create a registry of U.S.-listed therapeutic-biotech events from 2018-01-01 through 2025-12-31 using sources that can be audited historically. Freeze event identity before scoring.

Minimum cohort: 120 events, stratified as follows:

- at least 30 Phase II or proof-of-concept readouts;
- at least 30 Phase III/pivotal readouts;
- at least 30 regulatory events (AdCom, PDUFA, approval/CRL);
- at least 15 early clinical events;
- at least 15 material conference/other events tied to an underlying clinical phase;
- at least 40 negative events overall, including trial failure, CRL, material safety issue, or clinically disappointing data;
- at least 20 events where financing/dilution occurred from 90 days before through 30 days after the event;
- at least 20 single-asset issuers;
- no issuer contributes more than five events or 10% of a stratum.

If an event satisfies multiple strata, assign its primary stratum before outcome inspection. Preserve all inclusion/exclusion reasons.

### 2.2 Sampling method

1. Assemble the candidate registry from dated FDA calendars/archives, SEC filings, trial registries, and official issuer disclosures.
2. Deduplicate by issuer, asset, indication, event type, and event date.
3. Apply universe rules using the pre-event issuer state.
4. Stratify by event type and calendar year.
5. Select events through seeded random sampling (`seed=100100`) within strata.
6. Freeze `cohort-manifest.json` with hashes before reconstructing scores or returns.

Convenience sampling of memorable winners such as ARWR-like moves is permitted only as a separate case-study set, never as the primary validation cohort.

## 3. Point-in-time reconstruction

For each event define observation snapshots at:

- `T-60` calendar days;
- `T-30` calendar days;
- `T-10` calendar days;
- the last complete session before the event.

The primary validation snapshot is `T-30`; others test timing sensitivity. If the catalyst window was not knowable at T-30, the candidate must reflect Low timing confidence rather than using hindsight.

Reconstruction rules:

- only sources with `available_at <= snapshot cutoff`;
- filing acceptance time, not period end, determines availability;
- later trial-registry edits cannot overwrite historical versions;
- price and index data end at the previous complete session;
- 13F and Form 4 data use actual public filing dates;
- analyst/secondary context must be archived and publicly accessible or omitted;
- all manual judgments are locked before outcome returns are revealed to the scorer.

Recommended review flow separates the evidence pack from outcome data until the decision record is locked. Any unavoidable unblinding is recorded.

## 4. Outcome definitions

Event date `T0` is the first public timestamp of the material result. If released outside market hours, session zero is the next regular session.

Calculate split-adjusted total returns and XBI-relative abnormal returns:

- close-to-close `T-1` to `T+1`;
- `T-1` to `T+5`;
- `T-1` to `T+20`;
- maximum favorable excursion and maximum adverse excursion through 20 sessions;
- dilution from fully diluted shares and financing proceeds through `T+30`.

Primary return outcome: XBI-relative `T-1` to `T+20`.

Severe loss: absolute return ≤−40% at `T+5` or any close through `T+20`.

Swing success: maximum close through `T+20` is ≥20% above `T-1` and no earlier close reaches −25%.

The path definition prevents a later rebound from hiding an initially ruinous event.

## 5. Metrics and acceptance criteria

### 5.1 Data integrity

| Metric | Acceptance |
|---|---:|
| Critical-field completeness among analyzed events | ≥95% |
| Source-lineage coverage for scored inputs | 100% |
| Historical post-cutoff leakage | 0 known instances |
| Deterministic rerun agreement | 100% numeric/classification fields |
| Catalyst interval precision at T-30 | ≥85% event occurs within stored interval or documented slippage update |

### 5.2 Probability calibration

- Report Brier score overall and by event stratum.
- Report calibration by PoS decile/band; no band with at least 15 events should deviate by more than 20 percentage points from observed success rate.
- Compare against event-type base-prior benchmark; BOE adjustments should improve or equal Brier score without post-hoc refitting.
- Confidence intervals are mandatory; small strata are descriptive only.

### 5.3 Ranking and risk

| Metric | Initial acceptance—not a profitability guarantee |
|---|---:|
| Median T+20 XBI-relative return: investable vs rejected/gated | investable higher by ≥10pp |
| Swing-success rate: top BOE quintile | ≥1.5× bottom quintile |
| Severe-loss rate among `HIGH_CONVICTION` | ≤15% and lower than ungated score-only comparator |
| Financing gate | ≥60% precision for pre-event or T+30 dilutive financing in the defined financing-risk subset |
| Overextension gate | lower median T+20 return or higher drawdown than comparable ungated candidates |
| Coverage of both positive and negative events | cohort requirements satisfied |

These thresholds are go/no-go criteria for further validation, not permission to tune BOE-1.0.0 on the holdout.

## 6. Train/calibration/holdout discipline

The BOE-1.0.0 rules are specified before outcome inspection. Use:

- 2018–2022: diagnostic/calibration report only;
- 2023–2024: temporal validation;
- 2025: untouched final holdout until all pipeline bugs are resolved.

Bug fixes may be applied across periods if they restore the written contract. Investment-rule changes require a new version and must not be justified solely by holdout performance. Report both original and changed rules on the same frozen cohort.

## 7. Required failure analysis

For every false positive with T+20 return ≤−20% and every false negative with T+20 maximum favorable excursion ≥40%, record:

- source/data failure;
- catalyst timing failure;
- scientific reasoning failure;
- PoS calibration failure;
- valuation/expectation failure;
- dilution/capital-structure failure;
- technical/entry failure;
- unmodeled external event;
- classification/gate interaction;
- whether information was knowable before the event.

Investigate the entire error cohort before proposing a coherent repair batch. Do not alter rules after the first anecdote.

## 8. Live shadow validation

After historical acceptance, run at least 12 weeks without executing trades:

- weekly full-universe refresh;
- daily tracked-catalyst refresh;
- point-in-time candidate snapshots that cannot be edited after event publication;
- delayed outcome capture and weekly data-quality audit;
- report slippage, stale sources, provider outages, analyst overrides, score/classification changes, and paper outcomes.

Minimum go-live evidence is 50 prospective candidates and 20 completed material catalysts; otherwise extend shadowing.

## 9. Validation artifacts

Each report contains:

- code SHA, rules checksum, cohort/input manifest hashes;
- data cutoff and provider versions;
- cohort flow and exclusions;
- missingness and source conflicts;
- score/gate distributions;
- calibration and return metrics with uncertainty;
- case-level locked predictions and outcomes;
- failure-analysis register;
- deviations and known limitations;
- signed recommendation: proceed, repair data pipeline, recalibrate in a new version, or stop.

## 10. Controlled milestone sequence

### Milestone 0 — Foundation specification (current)

Deliver investment rules, exact scorecard, gates, classifications, source hierarchy, missing-data policy, technical architecture, database/API/output contracts, validation protocol, and milestone plan. Commit, push, verify, and stop.

### Milestone 1 — Repository scaffold and executable contracts

Create Python package, formatting/type/test configuration, Pydantic domain models, scorecard loader/checksum, JSON contract tests, CI, and offline fixtures. No live ingestion and no investment logic beyond contract-boundary tests.

Acceptance: clean install without Docker; lint, types, unit/contract tests pass locally and in GitHub Actions.

### Milestone 2 — Universe and evidence foundation

Implement exchange/SEC identity ingestion, deterministic universe classifier, raw payload store, evidence/claim provenance, and point-in-time cutoff enforcement.

Acceptance: reproducible audited universe sample; zero unexplained classifications in audit set.

### Milestone 3 — Catalyst and clinical data

Implement ClinicalTrials.gov and FDA adapters, filing-guidance extraction, catalyst normalization/versioning, conflict resolution, and scientific evidence packs. Human confirmation remains mandatory for rankable events.

Acceptance: precision/recall audit on a preselected event sample and no hindsight leakage.

### Milestone 4 — Financial survival and capital structure

Implement SEC XBRL/filing facts, normalized burn, runway, debt, shelf/ATM/424B tracking, fully diluted shares, and financing gate inputs.

Acceptance: reconcile audited sample to filings within documented tolerances; full calculation traces.

### Milestone 5 — Science, PoS, rNPV, scoring, and gates

Implement deterministic rubrics, manual evidence review form, PoS calculation, three-scenario rNPV, expected value, factor scores, coverage, gate precedence, and classification.

Acceptance: boundary/golden tests cover every rule; independent recomputation agrees.

### Milestone 6 — Market data and technical engine

Select terms-compatible free adapter, implement adjusted bars, XBI relative strength, indicators, support/extension rules, and stale-data handling.

Acceptance: indicator comparison against an independent implementation; corporate-action audit.

### Milestone 7 — End-to-end historical validation

Freeze cohort, reconstruct snapshots, run diagnostics/temporal validation/holdout, complete failure analysis, and publish signed report. No threshold change without owner approval and versioning.

### Milestone 8 — Prospective live-shadow validation

Run the minimum 12-week/50-candidate/20-event shadow protocol. Repair data defects as batches; investment-rule changes require approval.

### Milestone 9 — Decision-first dashboard

Build ranked dashboard, catalyst calendar, company evidence/valuation/risk/technical pages, validation view, and explicit stale/error states. The UI consumes the existing API and cannot alter decisions.

### Milestone 10 — Production decision and optional handoff

Security/reliability review, operating controls, disclaimers, monitoring, and owner go/no-go. IEE handoff is a separate explicitly approved scope; no automatic trading.

## 11. Approval gates

- Do not begin a milestone merely because the previous one passed.
- Each milestone ends with commit SHA, file list, tests, validation findings, unresolved issues, and recommended next milestone.
- Advancing requires explicit owner approval.
- BOE-1.1 is not activated by experimentation; proposed rule changes remain on a separate branch/report until approved.

## 12. Current unresolved implementation choices

These do not block Milestone 0 and cannot change frozen investment behavior:

1. Which free delayed-price adapter has acceptable terms, corporate-action handling, and reliability.
2. Which versioned funds qualify for the specialist-biotech registry.
3. Whether manual scientific review uses a repository form or an authenticated internal UI.
4. Final production database/hosting provider.
5. The historical event-registry acquisition workflow needed to achieve the 120-event minimum without paid data.

Each must be resolved in its assigned milestone with an audit report, not an undocumented code choice.
