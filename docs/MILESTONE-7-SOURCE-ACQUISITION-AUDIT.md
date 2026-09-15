# Milestone 7 Historical-Source Acquisition Audit

**Reviewed:** 2026-09-14  
**BOE version:** BOE-1.0.0  
**Milestone:** 7 — End-to-end historical validation  
**M6 baseline:** `3060761a11f7bd85298f79efa8e262e5b8adedaf`  
**Decision:** the validation infrastructure is executable, but the authoritative 120-event cohort is **not yet freezeable**. Milestone 7 therefore must not be merged or represented as complete.

## 1. Frozen acceptance boundary

Milestone 7 requires a point-in-time, historically auditable U.S.-listed therapeutic-biotech cohort from 2018-01-01 through 2025-12-31 with at least 120 events and the frozen stratum, negative-event, financing, single-asset, issuer-concentration, blinding, and holdout requirements defined in `docs/VALIDATION-AND-MILESTONES.md`.

No BOE-1.0.0 rule, score, threshold, gate, classification, PoS assumption, rNPV formula, financial-survival rule, technical rule, investability threshold, or missing-data rule may be changed to make the validation easier to pass.

## 2. Infrastructure status

The Milestone 7 branch already contains deterministic infrastructure for:

- seeded cohort selection (`seed=100100`);
- cohort minimum and issuer-concentration gates;
- immutable registry/cohort hashing;
- 2018–2022 diagnostic, 2023–2024 temporal-validation, and 2025 holdout partitioning;
- T−60, T−30, T−10, and last-complete-session cutoffs;
- source-availability cutoff enforcement;
- outcome-blinded historical decision locks;
- regular-session alignment for pre-market/after-hours events;
- T+1/T+5/T+20 return calculation;
- XBI-relative return calculation;
- MFE/MAE and path-dependent severe-loss/swing-success logic;
- Brier scoring and validation summary calculations;
- failure-analysis and leakage-audit contracts;
- persistence for cohort manifests, historical events, decision locks, outcomes, failure analysis, leakage findings, and signed validation reports.

The normal BOE quality workflow passes on this infrastructure. This does **not** constitute historical validation because the tests use deterministic synthetic fixtures rather than a real frozen cohort.

## 3. Candidate-discovery probe

A temporary research probe inspected the public `chufangao/CTO` research dataset only to quantify candidate-discovery capacity. It must not be treated as the authoritative event registry or outcome source.

The probe joined ClinicalTrials.gov-style trial metadata to public ticker mappings and found:

- 962 unique candidate NCT records;
- 153 unique mapped tickers;
- 858 industry-sponsored records;
- 125 Phase I records;
- 46 Phase I/II records;
- 309 Phase II records;
- 29 Phase II/III records;
- 453 Phase III records.

Completion-year distribution in the joined discovery set was:

| Year | Candidate records |
|---:|---:|
| 2020 | 249 |
| 2021 | 256 |
| 2022 | 280 |
| 2023 | 176 |
| 2024 | 1 |

The probe therefore demonstrates that **candidate discovery volume is not the principal constraint** for 2020–2023 clinical events.

## 4. Why the discovery dataset cannot freeze the cohort

The research dataset includes trial-registry dates, phase, enrollment, sponsor, completion dates, result-posting dates, status, selected metadata, ticker mapping, and a research label. Those fields are useful for discovery but are insufficient to define a BOE historical material catalyst event.

Specifically:

1. **Trial completion is not the material public catalyst timestamp.** A trial may complete months or years before the issuer first releases material topline data.
2. **ClinicalTrials.gov result posting is not necessarily the first public disclosure.** An issuer press release, conference presentation, SEC filing, FDA action, or publication can precede or follow registry posting.
3. **The research `labels` field is not an admissible BOE outcome truth source.** It is a dataset annotation, not the frozen event/outcome definition in BOE-1.0.0.
4. The discovery set does not supply the historical catalyst window known at T−30, the first public material-result timestamp, SEC-derived capital structure, point-in-time valuation assumptions, or the historical BOE evidence pack.
5. The observed joined set does not provide the required full 2018–2025 calendar coverage: it yielded no 2018–2019 completion-year records, only one 2024 record, and no 2025 records under the probed filters.
6. It does not independently establish the required ≥30 regulatory-event stratum.
7. It cannot establish historical financing/dilution through T+30 or single-asset status without issuer/SEC review.

Accordingly, discovery rows may generate **candidate leads only**. Each included event must be promoted to the registry only after primary-source verification.

## 5. Required primary-source verification for each event

Before an event may enter the frozen registry, the acquisition workflow must establish and hash an auditable evidence chain including, as applicable:

### Event identity and first public timestamp

At least one authoritative source that establishes the first material public disclosure, such as:

- issuer investor-relations release or archived corporate release;
- SEC 8-K/6-K or other contemporaneous filing accepted at or before the event timestamp;
- FDA action/advisory-committee/approval/CRL source for regulatory events;
- conference abstract/presentation with verifiable public availability time;
- peer-reviewed publication only when publication itself is the defined catalyst.

The timestamp must represent first public availability rather than a later repost.

### Trial identity and design

- ClinicalTrials.gov historical record/version or another authoritative trial registry;
- asset, indication, phase, design, endpoints, enrollment, comparator, and historical version availability.

### Point-in-time issuer and capital structure

- SEC filing acceptance timestamps and historical filing facts;
- cash, debt, burn, runway, shares, shelf/ATM/424B evidence, and financing state using only information public by each snapshot cutoff.

### Historical market state and outcomes

- security and XBI daily bars suitable for the historical cutoff;
- reproducible corporate-action treatment;
- a provider/version manifest and hashes;
- T−1 through T+20 prices and T+30 financing window.

## 6. Critical market-data blocker inherited from Milestone 6

Milestone 6 deliberately treats the local/manual Stooq bulk adapter as validation-only and rejects a provider-adjusted snapshot retrieved after a historical cutoff because later split/adjustment state can leak backward.

Therefore a present-day provider-adjusted history file cannot simply be reused to reconstruct 2018–2025 BOE technical snapshots under the zero-leakage standard.

Historical validation requires one of the following:

1. archived provider snapshots captured no later than each historical cutoff; or
2. raw unadjusted bars plus corporate-action events with point-in-time `known_at` timestamps; or
3. another auditable historical-data source whose adjustment methodology and historical availability permit deterministic point-in-time reconstruction.

Until that evidence exists, real M7 technical reconstruction and leakage-free historical outcome calculation are incomplete.

This control must **not** be weakened to obtain a backtest.

## 7. Current quantitative readiness

As of this audit:

- required frozen cohort: **120 events minimum**;
- authoritative events frozen in repository: **0**;
- authoritative `cohort-manifest.json`: **not present**;
- completed four-snapshot BOE reconstructions on real events: **0**;
- real historical outcomes attached under the M7 contract: **0**;
- 2025 holdout events locked before outcome inspection: **0**;
- final real-cohort Brier/ranking/gate metrics: **not computable**;
- real-cohort failure-analysis register: **not computable**;
- signed M7 recommendation based on a completed cohort: **not yet permissible**.

This is an evidence-acquisition shortfall, not permission to reduce the 120-event requirement.

## 8. Cohort acquisition workflow to continue M7

The next M7 batch should:

1. build a broad candidate registry without outcome-driven filtering;
2. add 2018–2019 and 2025 discovery sources and an explicit regulatory-event source;
3. verify each candidate against primary historical sources;
4. record inclusion/exclusion reason before outcome analysis;
5. enforce issuer concentration and stratum requirements;
6. freeze registry hash;
7. run deterministic seeded sampling;
8. freeze `cohort-manifest.json` before BOE reconstruction or return inspection;
9. reconstruct all four historical BOE snapshots using M1–M6 logic;
10. attach outcomes only after decision locks are complete;
11. perform leakage, calibration, ranking/risk, failure, temporal-validation, and 2025-holdout analyses.

## 9. Milestone status

**M7 infrastructure:** implemented and testable.  
**M7 historical validation:** incomplete.  
**PR #5:** must remain open/unmerged while the frozen cohort requirement is unmet.  
**Milestone 8:** must not begin.

If authoritative source acquisition ultimately cannot satisfy the frozen cohort and point-in-time requirements, the correct M7 outcome is to document the shortfall and issue **REPAIR DATA PIPELINE AND REPEAT M7**, not to fabricate events, use hindsight, reduce the cohort requirement, or weaken leakage controls.
