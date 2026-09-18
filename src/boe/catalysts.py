"""Milestone 3 catalyst normalization, versioning, conflicts, and human gates."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from typing import Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from boe.enums import CatalystType, EvidenceTier, TimingConfidence
from boe.models import ContractModel

CATALYST_NAMESPACE = UUID("2d1984b9-6834-45ce-b4e9-49f6d9402afe")


class CatalystConflictError(ValueError):
    """Raised when a catalyst cannot be safely ranked without manual adjudication."""


class HumanConfirmationRequired(ValueError):
    """Raised when a rankability decision lacks an in-cutoff human confirmation."""


class CatalystObservation(ContractModel):
    """One point-in-time catalyst assertion from one primary source."""

    issuer_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    catalyst_type: CatalystType
    clinical_phase: str = Field(min_length=1)
    title: str = Field(min_length=1)
    window_start: date
    window_end: date
    timing_confidence: TimingConfidence
    evidence_id: UUID
    source_tier: EvidenceTier
    known_at: datetime
    source_statement: str = Field(min_length=1)
    external_event_id: str | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        _require_aware(self.known_at, "known_at")
        if self.window_end < self.window_start:
            raise ValueError("catalyst observation window_end precedes window_start")
        return self

    @property
    def canonical_key(self) -> str:
        return "|".join(
            (
                self.issuer_id.strip().lower(),
                _canonical_text(self.asset),
                _canonical_text(self.indication),
                self.catalyst_type.value,
            )
        )

    @property
    def window_days(self) -> int:
        return (self.window_end - self.window_start).days + 1


class SourceConflict(ContractModel):
    code: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    observation_ids: tuple[UUID, ...] = Field(min_length=2)
    details: str = Field(min_length=1)
    requires_human_resolution: bool = True


class CatalystVersion(ContractModel):
    """Immutable resolved version of one canonical catalyst as known at a cutoff."""

    id: UUID
    canonical_key: str = Field(min_length=1)
    version: int = Field(ge=1)
    version_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    issuer_id: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    catalyst_type: CatalystType
    clinical_phase: str = Field(min_length=1)
    title: str = Field(min_length=1)
    window_start: date
    window_end: date
    timing_confidence: TimingConfidence
    primary_evidence_id: UUID
    supporting_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    conflicts: tuple[SourceConflict, ...]
    known_at: datetime
    resolved_at_cutoff: datetime

    @model_validator(mode="after")
    def validate_version(self) -> Self:
        _require_aware(self.known_at, "known_at")
        _require_aware(self.resolved_at_cutoff, "resolved_at_cutoff")
        if self.known_at > self.resolved_at_cutoff:
            raise ValueError("catalyst version cannot use post-cutoff knowledge")
        if self.window_end < self.window_start:
            raise ValueError("catalyst version window_end precedes window_start")
        if self.primary_evidence_id not in self.supporting_evidence_ids:
            raise ValueError("primary evidence must be present in supporting evidence")
        if len(set(self.supporting_evidence_ids)) != len(self.supporting_evidence_ids):
            raise ValueError("supporting evidence ids must be unique")
        return self

    @property
    def has_unresolved_conflict(self) -> bool:
        return any(conflict.requires_human_resolution for conflict in self.conflicts)


class HumanCatalystConfirmation(ContractModel):
    catalyst_version_id: UUID
    reviewer: str = Field(min_length=2)
    confirmed_at: datetime
    decision: str = Field(pattern=r"^(CONFIRMED|REJECTED|NEEDS_REVIEW)$")
    evidence_ids_reviewed: tuple[UUID, ...] = Field(min_length=1)
    conflict_resolution_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def aware_confirmation(self) -> Self:
        _require_aware(self.confirmed_at, "confirmed_at")
        if len(set(self.evidence_ids_reviewed)) != len(self.evidence_ids_reviewed):
            raise ValueError("reviewed evidence ids must be unique")
        return self


class HistoricalCatalystConfirmation(ContractModel):
    """Retrospective, outcome-blinded confirmation of a catalyst version for
    Milestone 7 historical reconstruction.

    Distinct from ``HumanCatalystConfirmation`` (live ranking): the live
    control rejects a ``confirmed_at`` that is in the future relative to a
    live decision cutoff, which is definitionally impossible for genuine
    retrospective review performed long after the historical event itself -
    a reviewer confirming 2019 evidence in 2026 is not "late," that is
    exactly what retrospective review means. This type instead binds the
    reviewer's evidence strictly to ``evidence_cutoff`` (the catalyst
    version's own frozen point-in-time boundary, ``resolved_at_cutoff``),
    while ``reviewed_at`` freely reflects the real wall-clock time of the
    actual human review. The record is itself immutable (``ContractModel``
    is frozen), so ``reviewed_at`` is also this confirmation's own lock
    moment - no separate "locked_at" field is needed, matching the
    established ``ManualScienceReview`` convention.
    """

    catalyst_version_id: UUID
    reviewer: str = Field(min_length=2)
    evidence_cutoff: datetime
    reviewed_at: datetime
    decision: str = Field(pattern=r"^(CONFIRMED|REJECTED|NEEDS_REVIEW)$")
    evidence_ids_reviewed: tuple[UUID, ...] = Field(min_length=1)
    conflict_resolution_notes: str = Field(min_length=1)
    outcome_data_shown: bool = False

    @model_validator(mode="after")
    def validate_confirmation(self) -> Self:
        _require_aware(self.evidence_cutoff, "evidence_cutoff")
        _require_aware(self.reviewed_at, "reviewed_at")
        if len(set(self.evidence_ids_reviewed)) != len(self.evidence_ids_reviewed):
            raise ValueError("reviewed evidence ids must be unique")
        if self.reviewed_at < self.evidence_cutoff:
            raise ValueError("historical review cannot occur before its own evidence cutoff")
        if self.outcome_data_shown:
            raise ValueError("historical catalyst confirmation must not have seen outcome data")
        return self


class RankabilityDecision(ContractModel):
    rankable: bool
    reason: str = Field(min_length=1)
    catalyst_version_id: UUID
    confirmation_required: bool = True


def normalize_catalyst(
    observations: tuple[CatalystObservation, ...],
    *,
    cutoff: datetime,
    prior_versions: tuple[CatalystVersion, ...] = (),
) -> CatalystVersion:
    """Resolve observations deterministically using only evidence known by ``cutoff``."""

    _require_aware(cutoff, "cutoff")
    eligible = tuple(item for item in observations if item.known_at <= cutoff)
    if not eligible:
        raise ValueError("no catalyst observations are available at cutoff")
    keys = {item.canonical_key for item in eligible}
    if len(keys) != 1:
        raise ValueError("observations must describe one canonical catalyst")

    ordered = tuple(sorted(eligible, key=_source_precedence_key))
    primary = ordered[0]
    conflicts = _detect_conflicts(ordered)
    supporting = tuple(dict.fromkeys(item.evidence_id for item in ordered))
    known_at = max(item.known_at for item in ordered)
    version_payload = {
        "canonical_key": primary.canonical_key,
        "issuer_id": primary.issuer_id,
        "asset": primary.asset,
        "indication": primary.indication,
        "catalyst_type": primary.catalyst_type.value,
        "clinical_phase": primary.clinical_phase,
        "title": primary.title,
        "window_start": primary.window_start.isoformat(),
        "window_end": primary.window_end.isoformat(),
        "timing_confidence": primary.timing_confidence.value,
        "primary_evidence_id": str(primary.evidence_id),
        "supporting_evidence_ids": [str(item) for item in supporting],
        "conflicts": [item.model_dump(mode="json") for item in conflicts],
        "known_at": known_at.astimezone(UTC).isoformat(),
        "cutoff": cutoff.astimezone(UTC).isoformat(),
    }
    digest = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    matching_prior = [
        item for item in prior_versions if item.canonical_key == primary.canonical_key
    ]
    for prior in matching_prior:
        if prior.version_sha256 == digest:
            return prior
    version = 1 + max((item.version for item in matching_prior), default=0)
    version_id = uuid5(CATALYST_NAMESPACE, f"{primary.canonical_key}|{version}|{digest}")
    return CatalystVersion(
        id=version_id,
        canonical_key=primary.canonical_key,
        version=version,
        version_sha256=digest,
        issuer_id=primary.issuer_id,
        asset=primary.asset,
        indication=primary.indication,
        catalyst_type=primary.catalyst_type,
        clinical_phase=primary.clinical_phase,
        title=primary.title,
        window_start=primary.window_start,
        window_end=primary.window_end,
        timing_confidence=primary.timing_confidence,
        primary_evidence_id=primary.evidence_id,
        supporting_evidence_ids=supporting,
        conflicts=conflicts,
        known_at=known_at,
        resolved_at_cutoff=cutoff,
    )


def require_human_confirmation(
    catalyst: CatalystVersion,
    confirmation: HumanCatalystConfirmation | None,
    *,
    cutoff: datetime,
) -> RankabilityDecision:
    """Enforce the Milestone 3 invariant that no event is rankable without a human lock."""

    _require_aware(cutoff, "cutoff")
    if confirmation is None:
        raise HumanConfirmationRequired("rankable catalyst requires explicit human confirmation")
    if confirmation.catalyst_version_id != catalyst.id:
        raise HumanConfirmationRequired("confirmation refers to a different catalyst version")
    if confirmation.confirmed_at > cutoff:
        raise HumanConfirmationRequired("confirmation was not available at the requested cutoff")
    if confirmation.confirmed_at < catalyst.known_at:
        raise HumanConfirmationRequired(
            "confirmation predates the evidence used by the catalyst version"
        )
    if not set(catalyst.supporting_evidence_ids).issubset(set(confirmation.evidence_ids_reviewed)):
        raise HumanConfirmationRequired(
            "reviewer did not confirm all evidence used by catalyst version"
        )
    if confirmation.decision != "CONFIRMED":
        return RankabilityDecision(
            rankable=False,
            reason=f"human confirmation decision is {confirmation.decision}",
            catalyst_version_id=catalyst.id,
        )
    if catalyst.has_unresolved_conflict and not confirmation.conflict_resolution_notes.strip():
        raise CatalystConflictError("source conflict requires explicit human resolution notes")
    return RankabilityDecision(
        rankable=True,
        reason="human-confirmed point-in-time catalyst",
        catalyst_version_id=catalyst.id,
    )


def require_historical_catalyst_confirmation(
    catalyst: CatalystVersion,
    confirmation: HistoricalCatalystConfirmation | None,
) -> RankabilityDecision:
    """Enforce the Milestone 7 historical-reconstruction invariant: a genuine,
    outcome-blind, evidence-cutoff-bound human review exists for this exact
    catalyst version, locked before any outcome data is attached.

    Deliberately does not weaken or reuse ``require_human_confirmation``'s
    "not in the future" check - that check is specific to live ranking. Here,
    the confirmation's stated ``evidence_cutoff`` must match the catalyst
    version's own frozen ``resolved_at_cutoff`` exactly, so a reviewer cannot
    claim to have judged a wider evidence window than the catalyst version
    actually used; ``reviewed_at`` (the real wall-clock review time) is not
    otherwise constrained relative to "now."
    """

    if confirmation is None:
        raise HumanConfirmationRequired(
            "rankable historical catalyst requires an explicit retrospective human confirmation"
        )
    if confirmation.catalyst_version_id != catalyst.id:
        raise HumanConfirmationRequired("confirmation refers to a different catalyst version")
    if confirmation.evidence_cutoff != catalyst.resolved_at_cutoff:
        raise HumanConfirmationRequired(
            "confirmation evidence_cutoff does not match this catalyst version's frozen cutoff"
        )
    if not set(catalyst.supporting_evidence_ids).issubset(set(confirmation.evidence_ids_reviewed)):
        raise HumanConfirmationRequired(
            "reviewer did not confirm all evidence used by catalyst version"
        )
    if confirmation.decision != "CONFIRMED":
        return RankabilityDecision(
            rankable=False,
            reason=f"historical human confirmation decision is {confirmation.decision}",
            catalyst_version_id=catalyst.id,
        )
    if catalyst.has_unresolved_conflict and not confirmation.conflict_resolution_notes.strip():
        raise CatalystConflictError("source conflict requires explicit human resolution notes")
    return RankabilityDecision(
        rankable=True,
        reason="retrospective outcome-blinded human-confirmed historical catalyst",
        catalyst_version_id=catalyst.id,
    )


def _source_precedence_key(item: CatalystObservation) -> tuple[int, int, float, str]:
    return (
        int(item.source_tier),
        item.window_days,
        -item.known_at.timestamp(),
        str(item.evidence_id),
    )


def _detect_conflicts(observations: tuple[CatalystObservation, ...]) -> tuple[SourceConflict, ...]:
    conflicts: list[SourceConflict] = []
    if len(observations) < 2:
        return ()
    phases = {_canonical_text(item.clinical_phase) for item in observations}
    if len(phases) > 1:
        conflicts.append(
            SourceConflict(
                code="CLINICAL_PHASE_DISAGREEMENT",
                field_name="clinical_phase",
                observation_ids=tuple(item.evidence_id for item in observations),
                details="primary sources disagree on clinical phase",
            )
        )
    for index, left in enumerate(observations):
        for right in observations[index + 1 :]:
            if left.window_end < right.window_start or right.window_end < left.window_start:
                conflicts.append(
                    SourceConflict(
                        code="DISJOINT_TIMING_WINDOWS",
                        field_name="window",
                        observation_ids=(left.evidence_id, right.evidence_id),
                        details=(
                            f"{left.window_start.isoformat()}..{left.window_end.isoformat()} vs "
                            f"{right.window_start.isoformat()}..{right.window_end.isoformat()}"
                        ),
                    )
                )
    return tuple(conflicts)


def _canonical_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
