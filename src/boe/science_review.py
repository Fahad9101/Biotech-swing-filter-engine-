"""Milestone 5 manual scientific-review contract.

The review locks human rubric judgments to an evidence cutoff.  It intentionally
contains no market outcome data and cannot source evidence after the analysis
cutoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.enums import PosConfidence
from boe.models import ContractModel

SCIENCE_SUBFACTORS = (
    "BIOLOGICAL_RATIONALE",
    "PRIOR_HUMAN_EVIDENCE",
    "TRIAL_DESIGN",
    "EFFICACY_ROBUSTNESS",
    "SAFETY",
    "EXTERNAL_VALIDATION",
)


class ManualScienceReview(ContractModel):
    """Locked evidence review used by deterministic science scoring and PoS."""

    issuer_id: str = Field(min_length=1)
    catalyst_version_id: UUID
    evidence_cutoff: datetime
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    biological_rationale: int = Field(ge=0, le=3)
    prior_human_evidence: int = Field(ge=0, le=5)
    trial_design: int = Field(ge=0, le=5)
    efficacy_robustness: int = Field(ge=0, le=3)
    safety: int = Field(ge=0, le=2)
    external_validation: int = Field(ge=0, le=2)
    evidence_confidence: PosConfidence
    source_quality: Literal["PRIMARY_OR_REGULATOR", "MIXED", "COMPANY_ONLY"]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    rationales: dict[str, str]
    single_arm_when_comparator_required: bool = False
    multiplicity_or_endpoint_ambiguity: bool = False
    material_unresolved_safety_imbalance: bool = False
    unresolved_clinical_hold: bool = False
    unbounded_safety_risk: bool = False
    fatal_trial_interpretability_defect: bool = False

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        _require_aware(self.evidence_cutoff, "evidence_cutoff")
        _require_aware(self.reviewed_at, "reviewed_at")
        if self.reviewed_at < self.evidence_cutoff:
            raise ValueError("reviewed_at cannot precede the locked evidence cutoff")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("science-review evidence IDs must be unique")
        missing_rationales = [
            code for code in SCIENCE_SUBFACTORS if not self.rationales.get(code, "").strip()
        ]
        if missing_rationales:
            raise ValueError(f"science-review rationales missing: {missing_rationales}")
        if self.source_quality == "COMPANY_ONLY":
            if self.prior_human_evidence > 4:
                raise ValueError("company-only evidence cannot earn 5/5 prior-human evidence")
            if self.efficacy_robustness > 2:
                raise ValueError("company-only evidence cannot earn 3/3 efficacy robustness")
            if self.evidence_confidence is PosConfidence.HIGH:
                raise ValueError("company-only evidence cannot receive High confidence")
        return self

    def score_by_code(self) -> dict[str, int]:
        return {
            "BIOLOGICAL_RATIONALE": self.biological_rationale,
            "PRIOR_HUMAN_EVIDENCE": self.prior_human_evidence,
            "TRIAL_DESIGN": self.trial_design,
            "EFFICACY_ROBUSTNESS": self.efficacy_robustness,
            "SAFETY": self.safety,
            "EXTERNAL_VALIDATION": self.external_validation,
        }


def require_review_cutoff(review: ManualScienceReview, as_of: datetime) -> None:
    """Reject evidence leakage while permitting retrospective blinded review."""

    _require_aware(as_of, "as_of")
    if review.evidence_cutoff > as_of:
        raise ValueError("science review includes evidence after analysis as_of")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
