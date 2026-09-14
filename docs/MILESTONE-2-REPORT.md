# Milestone 2 — Universe and Evidence Foundation

## Outcome

Milestone 2 implements the approved BOE-1.0.0 universe and evidence boundary without adding catalyst, clinical, financial, scoring, valuation, market-price, or UI behavior. The frozen scorecard checksum remains `11cffb776ffd6bbd943b1d23dfcf6541ab02fcbfec753f13d00a7f4acee8b569`.

## Implemented

- Parsers for the official Nasdaq-listed and other-listed symbol directory formats, including source hashes, source row numbers, file creation timestamps, exchange flags, and conservative security-type inference.
- Parser for the SEC ticker/exchange mapping and point-in-time SEC submissions profiles.
- Exact exchange-aware ticker-to-CIK resolution. A mismatch or ambiguity remains unresolved instead of being guessed.
- A deterministic universe classifier with explicit included, separate/non-rankable, excluded, and manual-review outcomes.
- A content-addressed, immutable raw-payload store keyed by SHA-256.
- Typed evidence and claim contracts with source tier, timestamps, raw-blob lineage, claim status, and conflict detection.
- Point-in-time cutoff enforcement that rejects evidence unavailable at the requested cutoff.
- SQLite persistence behind SQLAlchemy repository interfaces and an Alembic baseline migration.
- A bounded HTTP client with an explicit host allowlist, timeouts, retries, SEC request pacing, and a required identifying User-Agent.

## Conservative implementation decisions

1. Only Nasdaq, NYSE, and NYSE American map to supported exchanges. Other symbol-directory exchange codes are retained but excluded.
2. Only an exact ticker and normalized exchange match resolves SEC identity. Unmatched or ambiguous identities go to review.
3. Security names that do not deterministically establish common stock, ADR, or an excluded instrument are classified `UNKNOWN` and go to review.
4. Domestic reporting is considered current only when the latest accepted 10-K/10-Q is no more than 140 days old. A latest 20-F/40-F uses 550 days. Amendments inherit the base form. Missing history produces unknown status.
5. SEC filing acceptance time, rather than the filing period or filing date alone, controls point-in-time availability.
6. Business classification requires filing-backed claim identifiers before inclusion. Missing support cannot create an eligible company.
7. Investability remains `NOT_EVALUATED`; price/liquidity inputs belong to Milestone 6 and cannot be inferred in Milestone 2.

## Validation

The offline audit contains 19 boundary cases and explains every classification with a deterministic reason code. It covers therapeutic inclusion, majority therapeutic focus, missing support, mature pharma, device/non-primary activity, ambiguous activity, missing SEC and business evidence, ticker and exchange mismatches, stale/unknown reporting, unknown security type, warrants, ETFs, test issues, unsupported exchanges, and no active therapeutic asset.

Result: **19/19 expected decisions matched, 0 unexplained classifications, 100% deterministic rerun agreement.** The machine-readable result is in `validation/milestone-2-universe-audit.json`.

Additional tests cover official-file fixture parsing, malformed input rejection, exact SEC resolution, reporting cutoffs, HTTP allowlisting/retry behavior, immutable raw storage, evidence look-ahead prevention, claim conflicts, repository referential integrity, Alembic schema creation, and the unchanged Milestone 1 contracts.

## Known limitations

- The audit uses synthetic, point-in-time offline fixtures. No claim is made that it measures coverage of the entire live market.
- Primary-business evidence is a typed, provenance-required input. Automated filing-text extraction is intentionally not introduced here because it would require a separately audited extraction policy.
- ADR English-language filing sufficiency still requires reviewed evidence; insufficient cases remain non-rankable.
- Investability, market capitalization, liquidity, active halts, and bankruptcy continuity are not evaluated in this milestone.
- SQLite is the validated development database. PostgreSQL compatibility is architectural, not yet integration-tested.

## Stop boundary

Milestone 3 would add ClinicalTrials.gov and FDA adapters, catalyst normalization/versioning, filing-guidance extraction, conflict resolution, and scientific evidence packs. It is not part of this change and requires explicit approval.
