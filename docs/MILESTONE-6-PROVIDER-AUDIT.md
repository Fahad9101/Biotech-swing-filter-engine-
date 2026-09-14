# Milestone 6 Market-Data Provider Audit

**Reviewed:** 2026-09-14  
**BOE version:** BOE-1.0.0  
**Milestone:** 6 — Market data and technical engine  
**Decision:** validation-path adapter approved with explicit production block.

## Requirement

The frozen technical implementation contract requires a replaceable free delayed
market-data adapter for the validation path, no paid-data or API-key requirement,
reproducible corporate-action adjustment, immutable provenance, and a terms review
when the ingestion milestone begins.

The market-data provider is infrastructure only. It cannot change BOE investment
rules, score weights, technical thresholds, gates, or classifications.

## Provider decision

Milestone 6 uses a **local/manual Stooq bulk historical snapshot adapter**.

BOE does **not**:

- call an undocumented single-symbol download endpoint;
- automate retrieval from Stooq;
- bypass access controls;
- require a Stooq account or API key;
- redistribute the supplied snapshot;
- treat the adapter as approved for commercial production.

The operator supplies the bulk snapshot after obtaining it under the terms that
apply to the operator. The adapter parses that immutable file locally and records
its SHA-256, retrieval timestamp, provider name, adjustment version, and series
manifest.

The public bulk-history landing page reviewed for this decision is:

- `https://stooq.com/db/h/`

Current commercial rights were **not established by an authoritative provider
grant during this milestone**. BOE therefore records
`commercial_use_approved=false` and blocks any inference that the validation
adapter is a production/commercial market-data license.

A future commercial BOE deployment must replace or separately license this source
before production use. A provider switch must create a new series version and a
comparison report; it cannot silently rewrite historical market records.

## Point-in-time corporate-action rule

A provider-adjusted snapshot retrieved after a historical analysis cutoff can
contain split adjustments that were not represented by an archived snapshot at
that cutoff. BOE therefore treats the provider's adjustment state as known only
as of the snapshot retrieval date.

Consequences:

1. A provider-adjusted snapshot may be used for a current/as-of-snapshot analysis.
2. It may **not** be reused for an earlier historical cutoff.
3. Historical validation requires either:
   - an archived provider snapshot captured no later than the cutoff, or
   - raw unadjusted bars plus corporate-action events whose `known_at` timestamps
     are at or before the cutoff.
4. A later split or revised adjustment cannot silently leak into an earlier BOE
   snapshot.

This control is deliberate even though it is conservative.

## Technical calculation policy

Milestone 6 implements only the frozen technical behavior:

- adjusted daily OHLCV;
- SMA20 and SMA50;
- 20-session total return and XBI-relative return;
- Wilder RSI14;
- Wilder ATR14;
- 20-session up/down dollar-volume ratio;
- 20-session OBV slope;
- validated support;
- stale-data detection;
- market liquidity/session-count inputs used by the investability floor.

The frozen specification does not define an automatic pivot-detection tolerance.
Milestone 6 therefore does **not** invent one. A pivot may be used only when an
explicit reviewed pivot level is supplied with at least two distinct test sessions
within the prior 60 sessions, and the engine verifies that the level traded inside
each declared session's high-low range.

Resistance is retained as a nullable technical field but is not algorithmically
invented because BOE-1.0.0 does not freeze a resistance-detection rule.

## Production status

| Capability | Status |
|---|---|
| Offline/no-key validation path | Approved |
| Automated Stooq retrieval | Not approved / not implemented |
| Historical point-in-time use of same-day archived snapshot | Supported |
| Historical use of a later provider-adjusted snapshot | Rejected |
| Commercial production use | Blocked pending explicit licensing |
| Data redistribution | Not approved |
| BOE-1.0.0 rule changes | None |

This provider decision is an implementation choice only and does not activate
BOE-1.1.
