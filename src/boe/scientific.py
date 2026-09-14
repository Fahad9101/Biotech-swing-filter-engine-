"""Scientific evidence packs for human catalyst review."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from boe.models import ContractModel

PACK_NAMESPACE = UUID("7f7eff64-9b6f-4bfe-8de0-c7269e04f47a")


class ScientificEvidencePack(ContractModel):
    id: UUID
    catalyst_version_id: UUID
    asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    clinical_phase: str = Field(min_length=1)
    trial_ids: tuple[str, ...]
    study_design: str = Field(min_length=1)
    enrollment: int | None = Field(default=None, ge=1)
    randomized: bool | None = None
    blinded: bool | None = None
    comparator: str | None = None
    primary_endpoints: tuple[str, ...]
    secondary_endpoints: tuple[str, ...]
    primary_completion_date: date | None = None
    study_status: str | None = None
    safety_signals: tuple[str, ...]
    regulatory_context: tuple[str, ...]
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_cutoff: datetime
    generated_at: datetime
    manual_review_required: bool = True

    @model_validator(mode="after")
    def validate_pack(self) -> Self:
        if self.evidence_cutoff.tzinfo is None or self.evidence_cutoff.utcoffset() is None:
            raise ValueError("evidence_cutoff must be timezone-aware")
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.generated_at < self.evidence_cutoff:
            raise ValueError("scientific pack cannot be generated before its cutoff")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("scientific evidence ids must be unique")
        if len(set(self.trial_ids)) != len(self.trial_ids):
            raise ValueError("trial ids must be unique")
        return self


def build_scientific_evidence_pack(
    *,
    catalyst_version_id: UUID,
    asset: str,
    indication: str,
    clinical_phase: str,
    trial_ids: tuple[str, ...],
    study_design: str,
    enrollment: int | None,
    randomized: bool | None,
    blinded: bool | None,
    comparator: str | None,
    primary_endpoints: tuple[str, ...],
    secondary_endpoints: tuple[str, ...],
    primary_completion_date: date | None,
    study_status: str | None,
    safety_signals: tuple[str, ...],
    regulatory_context: tuple[str, ...],
    evidence_ids: tuple[UUID, ...],
    evidence_cutoff: datetime,
    generated_at: datetime,
) -> ScientificEvidencePack:
    identity = "|".join(
        (
            str(catalyst_version_id),
            evidence_cutoff.isoformat(),
            ",".join(sorted(str(item) for item in evidence_ids)),
        )
    )
    return ScientificEvidencePack(
        id=uuid5(PACK_NAMESPACE, identity),
        catalyst_version_id=catalyst_version_id,
        asset=asset,
        indication=indication,
        clinical_phase=clinical_phase,
        trial_ids=tuple(dict.fromkeys(trial_ids)),
        study_design=study_design,
        enrollment=enrollment,
        randomized=randomized,
        blinded=blinded,
        comparator=comparator,
        primary_endpoints=primary_endpoints,
        secondary_endpoints=secondary_endpoints,
        primary_completion_date=primary_completion_date,
        study_status=study_status,
        safety_signals=safety_signals,
        regulatory_context=regulatory_context,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        evidence_cutoff=evidence_cutoff,
        generated_at=generated_at,
    )
