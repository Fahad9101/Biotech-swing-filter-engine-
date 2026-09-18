# M7 readiness reconciliation

Recovered from PR #5 head `64dd89e1106b86c4b846c0f08c05ebf2863c0f10`.
Main remains `3060761a11f7bd85298f79efa8e262e5b8adedaf`; no later automated
commit existed at recovery. BOE quality run 34992949337 succeeded.

Run `python scripts/m7_reconcile_readiness.py` to regenerate readiness and the
row-level status ledger. Run with `--check` to reject drift. Pytest compares both
committed artifacts with the generator, including input hashes. These are
pre-freeze status artifacts, not an eligible registry or a frozen manifest.

The source population comprises 165 broad acquisition rows, eight targeted
single-asset rows and six targeted negative rows: 179 distinct candidates.
ACTU's original event is replaced in this view by the canonical normalization;
its universe ledger uses a different ID, bound through the explicitly recorded
original ID and matching first-public timestamp. Source acquisition rows remain
unchanged. The older candidate-promotion-ledger is an acquisition-only snapshot
which omits the eight targeted single-asset rows; it is not the current combined
status view.

Recomputed universe counts: 50 determinations, 38 PASS, 12 FAIL, 129 pending.
Explicit negative labels: 50, including the documented HALO supplemental label;
nine PASS, eight FAIL, 33 pending. The maximum not-yet-excluded reserve is 42,
not 43. The historical negative-reserve-integration-01 omitted RAIN/MANTRA from
its list of broad failures even though that event is in the broad Phase III
batch. Integration-02 inherited the overcount. Those versioned historical
integration files are superseded for current totals by cohort-readiness.json;
they remain unmodified as evidence of the earlier calculation.

Single-asset universe-PASS reserve remains 20, with two additional qualifying
rows unevaluated. Financing universe-PASS reserve remains 20; the documented
contained-reporting-interval qualification is included. No final quota is met.

Existing historical-universe-ledger-19 contains an ACTU event-session liquidity
sensitivity after the pre-market disclosure. The generator uses only the stored
pre-event determination, never the sensitivity. This pre-existing observation
requires an unblinding/leakage review; zero known leakage is not certified.

No eligible registry, frozen manifest, historical four-snapshot reconstruction,
decision locks, outcome cohort or locked holdout exists. The tool refuses to
infer completion merely from a newly appearing manifest. Human catalyst
confirmations and manual scientific reviews remain required by the engine.
Neither general permission to implement nor automated evidence extraction is
a substitute for actual human review. The existing catalyst confirmation API
also requires confirmation time at or before the historical cutoff, while the
science-review API allows retrospective review. Do not backdate records to
bridge this distinction; historical review semantics must be resolved before
claiming an end-to-end historical reconstruction.

Validation: 129 tests passed; formatting, lint, strict typing, database migration
through 0006, dependency consistency passed. Frozen scorecard Git blob remains
`e9019ecb9975c21e62371c25dcd7d2b114de60e4`. No engine rules changed.

M7 remains incomplete; PR #5 must remain open. M8 cannot begin yet and requires
at least 12 actual prospective weeks, 50 candidates and 20 completed catalysts.
