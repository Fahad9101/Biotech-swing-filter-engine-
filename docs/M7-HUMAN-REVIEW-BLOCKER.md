# M7 external review dependency

Status: ACCEPTED AS MILESTONE 7'S FINAL REACHABLE STATE WITHOUT A REVIEWER,
NOT M7 COMPLETE. This is not a request to relax BOE-1.0.0 or substitute
hypothetical outcomes, and it is not a claim that the milestone's own
documented completion criteria (VALIDATION-AND-MILESTONES.md section 10) are
satisfied - they are not, and per the project owner's own decision below,
will not be without a reviewer this project does not have.

Update 2026-09-17 (final): the 120-event frozen cohort exists for real
(`validation/m7/cohort-manifest.json`), real snapshot cutoff timestamps for
all 120 events x 4 labels exist (`validation/m7/snapshot-cutoffs.json`, pure
NYSE-calendar math, no price data or review needed), and real price outcomes
for all 120 events exist (`validation/m7/historical-outcomes.json`, fetched
live via the Alpaca Market Data API adapter, `src/boe/ingestion/alpaca.py`,
120/120 succeeded with 0 failures - see `reference-alpaca-market-data` in
memory for how that source was verified). `scripts/m7_build_authoritative_status.py`
reports all of this from live-revalidated, real artifacts, never inferred
from file existence.

The project owner was asked directly whether they could serve as, or
arrange, a real human scientific/catalyst reviewer, and confirmed they have
no relevant background and will not fill that role. Asked what to do next,
the owner chose: treat the cohort freeze, snapshot cutoffs, and real outcomes
above as Milestone 7's final state without decision locks, rather than
attempt to formally redesign BOE-1.0.0's frozen scoring methodology to remove
the review requirement (the only legitimate alternative, and a major,
separately-versioned undertaking in its own right, not attempted here).
Consequently `HistoricalDecisionLock`, `ManualScienceReview`,
`HumanCatalystConfirmation`, calibration, and failure analysis will not exist
for this cohort unless a qualified reviewer is engaged later. The paragraphs
below, written before this was settled, describe that dependency in full;
they remain accurate as a description of what is missing and why it cannot
be fabricated, just no longer as a call to action expecting near-term
resolution.

The frozen roadmap requires human confirmation for rankable catalysts (M3),
manual scientific review (M5), and before-outcome judgment locks (M7). Current
M7 artifacts contain no HumanCatalystConfirmation or ManualScienceReview
records. The minimum 120-event cohort requires four historical snapshot states
per event (480 states). No real evidence packs or decision locks are
complete.

The specific external input is a designated human scientific/catalyst reviewer
and their actual evidence-bound review records. General authorization to build
the software does not attest to having reviewed a specific historical evidence
pack. Automated agents must not impersonate that reviewer.

There is also a concrete historical-time API incompatibility to resolve:
`require_human_confirmation` rejects `confirmed_at > cutoff`, whereas
`ManualScienceReview` explicitly permits retrospective review after an evidence
cutoff. The roadmap permits retrospective outcome-blinded reconstruction.
The live confirmation control must remain intact. A historical review workflow
must preserve the actual review timestamp separately from the evidence cutoff,
require a genuine human review, and lock decisions before outcomes. No record
may be backdated. This requires a proper historical reconstruction adapter and
real reviewer participation; changing timestamps or omitting the gate is not
an acceptable workaround.

Available alternatives checked: repository evidence and schemas, complete
local tests, connected GitHub, and public issuer/distributor sources. Public
sources can resolve facts (GPCR publication time was recovered in batch 07),
but cannot supply a present human's attestation. Existing M7 artifacts include
only generic duplicate review metadata, not the required per-catalyst or
scientific review records. A structured record fabricated by the assistant
would not resolve this dependency.

The worklist is `validation/m7/promotion/reconciled-candidate-status.json`,
resolved to the point that `validation/m7/cohort-manifest.json` (120 events,
hashed and self-validated), `validation/m7/snapshot-cutoffs.json` (480 real
cutoff timestamps), and `validation/m7/historical-outcomes.json` (120 real
price outcomes) all exist. None is a review-ready scientific pack, and none
can become one without a reviewer.

Minimum external action, as originally scoped, would have been to designate
an actual human reviewer and arrange review of outcome-blinded evidence
packs. That action was asked for directly and declined (see "Update
2026-09-17 (final)" above) - it is recorded here as a closed decision, not an
outstanding ask. If a qualified reviewer becomes available later,
`scripts/m7_build_authoritative_status.py` will pick up real decision-lock
work the moment it exists; nothing about accepting this final state prevents
resuming.

M8 adds a separate unavoidable elapsed-time dependency: at least 12 prospective
weeks plus 50 candidates and 20 completed catalysts after historical
acceptance. It remains unstarted and out of scope regardless of this decision.
