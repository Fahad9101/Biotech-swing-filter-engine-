"""Deterministic BOE-1.0.0 event probability-of-success calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from boe.enums import CatalystType, PosConfidence
from boe.models import (
    ContractModel,
    OrderedRange,
    ProbabilityAdjustment,
    ProbabilityAssessment,
    ScorecardContract,
)
from boe.science_review import ManualScienceReview

CLINICAL_PHASE_TYPES = {
    CatalystType.CLIN_P1,
    CatalystType.CLIN_P1_2,
    CatalystType.CLIN_P2,
    CatalystType.CLIN_P2_3,
    CatalystType.CLIN_P3,
}
NON_SCIENTIFIC_EVENT_TYPES = {
    CatalystType.PARTNER,
    CatalystType.COMMERCIAL,
    CatalystType.FINANCING,
}


class PosInput(ContractModel):
    catalyst_type: CatalystType
    science_review: ManualScienceReview
    underlying_phase: CatalystType | None = None
    event_specific_prior_pct: Decimal | None = Field(default=None, ge=0, le=100)
    contractually_dated: bool = False

    @model_validator(mode="after")
    def validate_event_prior(self) -> Self:
        if self.catalyst_type in {CatalystType.CONF_DATA, CatalystType.PUBLICATION}:
            if self.underlying_phase not in CLINICAL_PHASE_TYPES:
                raise ValueError("conference/publication PoS requires an underlying clinical phase")
        if self.catalyst_type in NON_SCIENTIFIC_EVENT_TYPES:
            if self.event_specific_prior_pct is None:
                raise ValueError("non-scientific event PoS requires an event-specific prior")
        elif self.event_specific_prior_pct is not None:
            raise ValueError("event-specific prior is reserved for partner/commercial/financing")
        return self


class PosTrace(ContractModel):
    prior_pct: Decimal
    evidence_adjustments_pp: dict[str, Decimal]
    penalties_pp: dict[str, Decimal]
    midpoint_before_clamp_pct: Decimal
    midpoint_pct: Decimal
    confidence_half_width_pp: Decimal
    low_pct: Decimal
    high_pct: Decimal


class PosResult(ContractModel):
    assessment: ProbabilityAssessment
    trace: PosTrace


def estimate_event_pos(input_: PosInput, rules: ScorecardContract) -> PosResult:
    """Apply the frozen BOE-1.0.0 prior, evidence adjustments, penalties, and bands."""

    pos_rules = rules.pos
    confidence = input_.science_review.evidence_confidence
    prior = _prior_for(input_, pos_rules)
    adjustments: dict[str, Decimal] = {}
    penalties: dict[str, Decimal] = {}

    if input_.catalyst_type not in NON_SCIENTIFIC_EVENT_TYPES:
        scores = {
            "prior_human_evidence": input_.science_review.prior_human_evidence,
            "trial_design": input_.science_review.trial_design,
            "efficacy_robustness": input_.science_review.efficacy_robustness,
            "safety": input_.science_review.safety,
            "external_validation": input_.science_review.external_validation,
        }
        rule_adjustments = pos_rules["adjustment_pp"]
        for code, score in scores.items():
            rule = rule_adjustments[code]
            center = Decimal(str(rule["center"]))
            multiplier = Decimal(str(rule["multiplier"]))
            adjustments[code] = (Decimal(score) - center) * multiplier

        penalty_rules = pos_rules["penalty_pp"]
        penalty_flags = {
            "single_arm_when_comparator_required": (
                input_.science_review.single_arm_when_comparator_required
            ),
            "multiplicity_or_endpoint_ambiguity": (
                input_.science_review.multiplicity_or_endpoint_ambiguity
            ),
            "material_unresolved_safety_imbalance": (
                input_.science_review.material_unresolved_safety_imbalance
            ),
        }
        for code, active in penalty_flags.items():
            if active:
                penalties[code] = Decimal(str(penalty_rules[code]))

    midpoint_before = (
        prior + sum(adjustments.values(), Decimal("0")) + sum(penalties.values(), Decimal("0"))
    )
    midpoint_limits = pos_rules["clamp_midpoint_pct"]
    midpoint = _clamp(
        midpoint_before,
        Decimal(str(midpoint_limits[0])),
        Decimal(str(midpoint_limits[1])),
    )
    half_width = Decimal(str(pos_rules["confidence_half_width_pp"][confidence.value]))
    bounds = pos_rules["clamp_bounds_pct"]
    low = _clamp(
        midpoint - half_width,
        Decimal(str(bounds[0])),
        Decimal(str(bounds[1])),
    )
    high = _clamp(
        midpoint + half_width,
        Decimal(str(bounds[0])),
        Decimal(str(bounds[1])),
    )

    adjustment_records = [
        ProbabilityAdjustment(
            code=code,
            percentage_points=float(value),
            rationale=f"Frozen BOE evidence adjustment: {value:+}pp",
        )
        for code, value in adjustments.items()
    ]
    adjustment_records.extend(
        ProbabilityAdjustment(
            code=code,
            percentage_points=float(value),
            rationale=f"Frozen BOE penalty: {value:+}pp",
        )
        for code, value in penalties.items()
    )
    assessment = ProbabilityAssessment(
        event_success_pct=OrderedRange(
            low=float(low),
            mid=float(midpoint),
            high=float(high),
        ),
        confidence=confidence,
        prior_pct=float(prior),
        adjustments=tuple(adjustment_records),
    )
    return PosResult(
        assessment=assessment,
        trace=PosTrace(
            prior_pct=prior,
            evidence_adjustments_pp=adjustments,
            penalties_pp=penalties,
            midpoint_before_clamp_pct=midpoint_before,
            midpoint_pct=midpoint,
            confidence_half_width_pp=half_width,
            low_pct=low,
            high_pct=high,
        ),
    )


def _prior_for(input_: PosInput, pos_rules: dict[str, object]) -> Decimal:
    catalyst_type = input_.catalyst_type
    if catalyst_type in NON_SCIENTIFIC_EVENT_TYPES:
        assert input_.event_specific_prior_pct is not None
        prior = input_.event_specific_prior_pct
        if not input_.contractually_dated:
            prior = min(prior, Decimal("50"))
        return prior
    if catalyst_type in {CatalystType.CONF_DATA, CatalystType.PUBLICATION}:
        assert input_.underlying_phase is not None
        catalyst_type = input_.underlying_phase
    base_midpoints = pos_rules["base_midpoint_pct"]
    if not isinstance(base_midpoints, dict):
        raise TypeError("scorecard pos.base_midpoint_pct must be a mapping")
    raw = base_midpoints.get(catalyst_type.value)
    if raw is None:
        raise ValueError(f"no frozen PoS prior for catalyst type {catalyst_type.value}")
    return Decimal(str(raw))


def _clamp(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return min(max(value, lower), upper)
