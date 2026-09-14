"""Offline Milestone 3 extraction and point-in-time validation helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.catalysts import CatalystObservation, CatalystVersion
from boe.models import ContractModel


class AuditLabel(ContractModel):
    case_id: str = Field(min_length=1)
    expected_positive: bool
    predicted_positive: bool


class PrecisionRecallAudit(ContractModel):
    total: int = Field(ge=1)
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if (
            self.true_positive + self.false_positive + self.true_negative + self.false_negative
            != self.total
        ):
            raise ValueError("audit confusion matrix does not reconcile to total")
        return self


class LeakageFinding(ContractModel):
    object_type: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    available_at: datetime
    cutoff: datetime
    details: str = Field(min_length=1)


class PointInTimeAudit(ContractModel):
    inspected_objects: int = Field(ge=0)
    findings: tuple[LeakageFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


def precision_recall(labels: tuple[AuditLabel, ...]) -> PrecisionRecallAudit:
    if not labels:
        raise ValueError("audit labels cannot be empty")
    tp = sum(item.expected_positive and item.predicted_positive for item in labels)
    fp = sum(not item.expected_positive and item.predicted_positive for item in labels)
    tn = sum(not item.expected_positive and not item.predicted_positive for item in labels)
    fn = sum(item.expected_positive and not item.predicted_positive for item in labels)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return PrecisionRecallAudit(
        total=len(labels),
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=precision,
        recall=recall,
    )


def audit_point_in_time(
    *,
    cutoff: datetime,
    observations: tuple[CatalystObservation, ...] = (),
    versions: tuple[CatalystVersion, ...] = (),
    evidence_available_at: tuple[tuple[UUID, datetime], ...] = (),
) -> PointInTimeAudit:
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("cutoff must be timezone-aware")
    findings: list[LeakageFinding] = []
    inspected = 0
    for item in observations:
        inspected += 1
        if item.known_at > cutoff:
            findings.append(
                LeakageFinding(
                    object_type="catalyst_observation",
                    object_id=str(item.evidence_id),
                    available_at=item.known_at,
                    cutoff=cutoff,
                    details="observation was not public by cutoff",
                )
            )
    for item in versions:
        inspected += 1
        if item.known_at > cutoff or item.resolved_at_cutoff > cutoff:
            findings.append(
                LeakageFinding(
                    object_type="catalyst_version",
                    object_id=str(item.id),
                    available_at=max(item.known_at, item.resolved_at_cutoff),
                    cutoff=cutoff,
                    details="version contains or was resolved with post-cutoff information",
                )
            )
    for evidence_id, available_at in evidence_available_at:
        inspected += 1
        if available_at > cutoff:
            findings.append(
                LeakageFinding(
                    object_type="evidence",
                    object_id=str(evidence_id),
                    available_at=available_at,
                    cutoff=cutoff,
                    details="evidence item was unavailable by cutoff",
                )
            )
    return PointInTimeAudit(inspected_objects=inspected, findings=tuple(findings))
