# M7 external review dependency

Status: BLOCKED FOR FINAL HUMAN-REVIEWED RECONSTRUCTION, NOT M7 COMPLETE.
This is not a request to relax BOE-1.0.0 or substitute hypothetical outcomes.

The frozen roadmap requires human confirmation for rankable catalysts (M3),
manual scientific review (M5), and before-outcome judgment locks (M7). Current
M7 artifacts contain no HumanCatalystConfirmation or ManualScienceReview
records. The minimum 120-event cohort requires four historical snapshot states
per event (480 states). No real states or decision locks are complete.

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

The worklist is `validation/m7/promotion/reconciled-candidate-status.json`.
It preserves 179 candidate IDs and links each known universe, financing,
single-asset and timestamp determination to its source ledger. It is not a
review-ready scientific pack and is not an eligible registry. Remaining work:
129 universe determinations, full historical evidence assembly, human reviews,
concentration/deduplication checks, registry/cohort freeze, 480 snapshot states,
decision locks and only then outcome attachment and acceptance analysis.
All 33 unevaluated negatives remain pending; none is treated as eligible.

Minimum external action: designate the actual human reviewer and arrange
review of the completed outcome-blinded evidence packs. No bulk sign-off on
unseen evidence is requested. The pipeline work and evidence acquisition
remain implementation work, not actions the owner must perform manually.

M8 adds a separate unavoidable elapsed-time dependency: at least 12 prospective
weeks plus 50 candidates and 20 completed catalysts after historical acceptance.
