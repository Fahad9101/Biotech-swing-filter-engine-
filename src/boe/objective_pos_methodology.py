"""An objective, review-free substitute PoS methodology for Milestone 7 only.

This is NOT BOE-1.0.0 and NOT a change to it. BOE-1.0.0's frozen PoS
calculation (boe.pos.estimate_event_pos) requires a ManualScienceReview: six
subjective 0-5 clinical-judgment scores that only a qualified human reviewer
can honestly produce (see docs/M7-HUMAN-REVIEW-BLOCKER.md). This project has
no such reviewer and an automated agent must never simulate or impersonate
one - fabricating plausible-looking 0-5 "trial design" or "efficacy
robustness" scores would be exactly the fabrication this project prohibits,
just moved from prose into numbers.

What follows is a genuinely different, much simpler methodology, built to
answer a narrower question: using ONLY facts that are (a) structural, not a
judgment call, and (b) knowable before the event's own readout - can a
review-free probability estimate be usefully calibrated against real
outcomes? It uses exactly one input per event: catalyst_type. Its prior
table is not invented here - it is BOE-1.0.0's own frozen, already-vetted
base_midpoint_pct table (contracts/boe-scorecard.v1.0.0.json), which was
never review-dependent in the first place (only the ADJUSTMENT layer on top
of it required ManualScienceReview). That adjustment layer is dropped
entirely rather than approximated, and confidence is fixed at LOW (the
widest frozen band) to honestly represent that no per-event scientific
judgment informs this estimate.

Deliberately excluded as inputs, and why: every other field this project has
sourced about these events (negative_event, result_direction, swing_success,
financing status) either IS the outcome or is entangled with it, and using
any of them here would leak the answer into the prediction. Trial-design
facts (randomized/controlled/blinded) could in principle be sourced
pre-event from public trial registries, but doing so faithfully for 120
events is a separate, much larger undertaking not attempted here; this
methodology does not claim to use them.

Because this drops an entire scoring dimension rather than fabricate it,
expect this to calibrate worse than a genuine human-reviewed BOE-1.0.0 score
would. That is the honest, expected cost of having no reviewer - not a
defect to silently tune away.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from boe.enums import CatalystType
from boe.models import ContractModel

METHODOLOGY_VERSION = "M7-OBJECTIVE-POS-1"

# BOE-1.0.0's own frozen catalyst-type prior (contracts/boe-scorecard.v1.0.0.json
# pos.base_midpoint_pct) - reused unmodified. This table was never
# review-dependent: only the adjustment/penalty layer on top of it needed a
# ManualScienceReview, and that layer is what this methodology omits.
BASE_MIDPOINT_PCT: dict[str, Decimal] = {
    "CLIN_P1": Decimal("70"),
    "CLIN_P1_2": Decimal("45"),
    "CLIN_P2": Decimal("40"),
    "CLIN_P2_3": Decimal("50"),
    "CLIN_P3": Decimal("55"),
    "REG_SUBMIT": Decimal("85"),
    "REG_ADCOM": Decimal("60"),
    "REG_DECISION": Decimal("75"),
    "REG_OTHER": Decimal("50"),
}
# Conference/publication events carry no catalyst-type-specific prior of
# their own in the frozen table; BOE-1.0.0 resolves them via an underlying
# clinical phase (see boe.pos._prior_for), passed in by the caller below.
# The frozen clamp and LOW-confidence half-width - reused unmodified from
# contracts/boe-scorecard.v1.0.0.json pos.{clamp_midpoint_pct,clamp_bounds_pct,
# confidence_half_width_pp.LOW}.
CLAMP_MIDPOINT_PCT = (Decimal("10"), Decimal("90"))
CLAMP_BOUNDS_PCT = (Decimal("5"), Decimal("95"))
LOW_CONFIDENCE_HALF_WIDTH_PP = Decimal("15")


class ObjectivePosAssessment(ContractModel):
    """A review-free PoS estimate. Not a HistoricalDecisionLock: it carries no
    score, classification, valuation, or gate - only a PoS band - and must
    never be presented as a BOE-1.0.0 decision."""

    event_id: str = Field(min_length=1)
    methodology_version: str = METHODOLOGY_VERSION
    catalyst_type: CatalystType
    prior_pct: Decimal
    low_pct: Decimal
    mid_pct: Decimal
    high_pct: Decimal

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.low_pct <= self.mid_pct <= self.high_pct:
            raise ValueError("PoS range must be ordered")
        return self


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return min(max(value, lower), upper)


def estimate_objective_pos(
    *, event_id: str, catalyst_type: CatalystType, underlying_phase: CatalystType | None = None
) -> ObjectivePosAssessment:
    """Review-free PoS: BOE-1.0.0's own frozen catalyst-type prior, LOW
    confidence band, zero adjustments. See module docstring for why."""
    lookup_type = catalyst_type
    if catalyst_type in {CatalystType.CONF_DATA, CatalystType.PUBLICATION}:
        if underlying_phase is None:
            raise ValueError(
                f"{event_id}: conference/publication events require an underlying clinical phase"
            )
        lookup_type = underlying_phase
    raw = BASE_MIDPOINT_PCT.get(lookup_type.value)
    if raw is None:
        raise ValueError(f"{event_id}: no frozen prior for catalyst type {lookup_type.value}")
    midpoint = _clamp(raw, *CLAMP_MIDPOINT_PCT)
    low = _clamp(midpoint - LOW_CONFIDENCE_HALF_WIDTH_PP, *CLAMP_BOUNDS_PCT)
    high = _clamp(midpoint + LOW_CONFIDENCE_HALF_WIDTH_PP, *CLAMP_BOUNDS_PCT)
    return ObjectivePosAssessment(
        event_id=event_id,
        catalyst_type=catalyst_type,
        prior_pct=raw,
        low_pct=low,
        mid_pct=midpoint,
        high_pct=high,
    )
