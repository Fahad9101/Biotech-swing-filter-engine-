# M7 objective PoS substitute methodology

Status: a real, calibrated, honestly-reported substitute for the human
scientific/catalyst review BOE-1.0.0 requires and this project does not have
(see docs/M7-HUMAN-REVIEW-BLOCKER.md). Built at the project owner's explicit
request after they confirmed no qualified reviewer is available: "cancel the
constraints of the human reviewing however dont fabricate things up and
complete from here to finish this project."

## What this is not

It is not BOE-1.0.0, and BOE-1.0.0 is not changed by any of this - the
frozen rules, contracts, and scorecard are untouched. It is not a simulated
or fabricated human review: no code here scores "trial design quality" or
"biological rationale" the way `ManualScienceReview` does, because an
automated agent producing plausible-looking 0-5 clinical judgment scores
would be exactly the fabrication this project prohibits, just moved from
prose into numbers. It does not produce a `HistoricalDecisionLock`: there is
no score, classification, gate, or valuation for any event in this cohort,
because those require point-in-time financial, technical, and valuation
reconstruction that was never performed and is out of scope here.

## What this is

`src/boe/objective_pos_methodology.py` computes a probability-of-success
estimate from exactly one input per event: `catalyst_type` (resolved to an
underlying clinical phase for conference/publication events via a
documented, structural mapping - see
`scripts/m7_build_objective_pos.py:UNDERLYING_PHASE_BY_CLINICAL_PHASE`). The
prior it uses is not invented - it is BOE-1.0.0's own frozen
`base_midpoint_pct` table from `contracts/boe-scorecard.v1.0.0.json`,
reused verbatim and cross-checked by
`tests/test_objective_pos_methodology.py::test_base_midpoints_match_the_frozen_scorecard_exactly`.
That table was never review-dependent - only the adjustment/penalty layer on
top of it needed `ManualScienceReview`, and that layer is dropped entirely
here rather than approximated. Confidence is fixed at BOE-1.0.0's own
frozen LOW band (the widest one), honestly representing that no per-event
judgment informs the estimate.

Deliberately excluded as inputs: every other field this project has sourced
about these events (`negative_event`, `result_direction`, `swing_success`,
financing status) either IS the outcome or is entangled with it. Using any
of them to adjust the PoS estimate would leak the answer into the
prediction. Real, pre-event-knowable trial-design facts (randomized,
controlled, blinded) could in principle be sourced from public trial
registries, but doing so faithfully for all 120 events is a separate, much
larger undertaking not attempted here.

## Pipeline

1. `scripts/m7_build_objective_pos.py` - computes the PoS estimate for all
   120 frozen events. Pure function of the already-frozen manifest; no new
   evidence, no network calls.
2. `scripts/m7_build_objective_calibration.py` - compares those estimates to
   two independent kinds of real outcome: the frozen cohort's own
   `negative_event` label (inverted) as the scientific/regulatory ground
   truth, and the real, live-fetched price outcomes
   (`validation/m7/historical-outcomes.json`) for the return-based
   comparisons. Uses only `boe.historical_validation`'s existing,
   data-independent `brier_score`/`wilson_rate` helpers -
   `summarize_validation()` is deliberately not used, because it requires
   real `HistoricalDecisionLock` records this project does not have.
3. `scripts/m7_build_validation_report.py` - assembles the final report
   (`validation/m7/validation-report.json`) per
   VALIDATION-AND-MILESTONES.md section 9's shape, explicitly listing what
   is present (real) and what is not (BOE-1.0.0 scores/gates/classification),
   plus an objectively-computed failure register (see below) and a signed
   recommendation.

## Real result, not curated

The methodology's own calibration report shows it does **not** beat a naive
constant-rate baseline (Brier 0.2498 vs. 0.2299) and does **not** rank
correctly (top-PoS-quintile swing success 29.2% vs. bottom-quintile 37.5%).
The final report's recommendation is accordingly `PROPOSE RECALIBRATION IN A
NEW BOE VERSION`, with an explicit statement that it "is not a substitute
for a genuine human scientific review and should not inform live decisions
in its current form." This is the honest, expected cost of dropping an
entire scoring dimension rather than fabricating it - not a defect quietly
tuned away, and not evidence that BOE-1.0.0 itself (never actually scored)
does or doesn't work.

## Failure register, not failure analysis

`validation/m7/validation-report.json`'s `failure_register` objectively
identifies false positives (top PoS quintile, T+20 return <= -20%) and
false negatives (bottom PoS quintile, MFE >= 40%) using only fields already
present in committed artifacts. It does **not** attempt VALIDATION-AND-
MILESTONES.md section 7's full per-event categorization (source failure,
timing failure, unmodeled external event, etc.) for any specific event:
doing that honestly requires new per-event research, and guessing at a
specific real event's failure cause without evidence would be fabrication,
not analysis. Each entry lists this explicitly rather than filling the gap
with a plausible-sounding guess.

## One disclosed limitation that cannot be undone

The author of this methodology (an AI assistant, working in the same
session that built `validation/m7/historical-outcomes.json`) had already
seen this cohort's aggregate outcome rates - 27 severe losses and 31 swing
successes of 120 - before designing the methodology above. The prior table
used is BOE-1.0.0's own pre-existing, frozen values, not fitted to this
cohort's specific rates, and no per-event outcome was consulted while
writing `src/boe/objective_pos_methodology.py`. But a claim of perfect
blinding would be false, and this document says so rather than omitting it.

## Standing constraints, unchanged

Per project standing constraints: PR #5 remains unmerged, Milestone 8
remains unstarted, and `milestone_complete`/`merge_ready`/
`milestone_8_allowed` all stay `False` in
`scripts/m7_build_authoritative_status.py`'s output, because BOE-1.0.0's own
documented completion criteria were not met by any of the above and this
document does not claim otherwise.
