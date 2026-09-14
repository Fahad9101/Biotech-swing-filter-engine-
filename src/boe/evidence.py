"""Immutable evidence and point-in-time claim contracts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from boe.enums import ClaimConfidence, ClaimStatus, EvidenceTier
from boe.models import ContractModel


class LookAheadViolation(ValueError):
    """Raised when evidence was unavailable at the requested cutoff."""


class EvidenceConflict(ValueError):
    """Raised when equally current claims disagree without supersession."""


class RawPayloadRecord(ContractModel):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str | None
    source_url: HttpUrl
    retrieved_at: datetime
    available_at: datetime
    relative_path: str = Field(pattern=r"^[a-f0-9]{2}/[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_timestamps(self) -> Self:
        _require_aware(self.retrieved_at, "retrieved_at")
        _require_aware(self.available_at, "available_at")
        if self.available_at > self.retrieved_at:
            raise ValueError("raw payload available_at cannot follow retrieved_at")
        return self


class EvidenceItem(ContractModel):
    id: UUID
    evidence_type: str = Field(min_length=1)
    source_tier: EvidenceTier
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    source_url: HttpUrl
    published_at: datetime | None
    available_at: datetime
    retrieved_at: datetime
    accession_or_external_id: str | None
    raw_blob_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    excerpt_locator: str | None
    supports_claim: str = Field(min_length=1)
    quality_flag: str | None
    supersedes_id: UUID | None = None

    @model_validator(mode="after")
    def valid_timestamps(self) -> Self:
        _require_aware(self.retrieved_at, "retrieved_at")
        _require_aware(self.available_at, "available_at")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        if self.available_at > self.retrieved_at:
            raise ValueError("evidence cannot be retrieved before availability")
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("published_at cannot follow available_at")
        if self.supersedes_id == self.id:
            raise ValueError("evidence cannot supersede itself")
        return self


class Claim(ContractModel):
    id: UUID
    subject_type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    typed_value: Any
    evidence_id: UUID
    valid_from: datetime
    known_at: datetime
    confidence: ClaimConfidence
    status: ClaimStatus = ClaimStatus.ACTIVE

    @model_validator(mode="after")
    def aware_timestamps(self) -> Self:
        _require_aware(self.valid_from, "valid_from")
        _require_aware(self.known_at, "known_at")
        return self

    @property
    def key(self) -> tuple[str, str, str]:
        return self.subject_type, self.subject_id, self.field_name


def enforce_evidence_cutoff(
    evidence_items: tuple[EvidenceItem, ...],
    cutoff: datetime,
) -> None:
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    future = [item.id for item in evidence_items if item.available_at > cutoff]
    if future:
        raise LookAheadViolation(f"evidence unavailable at cutoff: {future}")


def claims_as_of(
    claims: tuple[Claim, ...],
    evidence_items: tuple[EvidenceItem, ...],
    cutoff: datetime,
) -> tuple[Claim, ...]:
    """Resolve the latest non-superseded claim per field at an information cutoff."""

    enforce_evidence_cutoff(evidence_items, cutoff)
    evidence_ids = {item.id for item in evidence_items}
    eligible = [
        claim
        for claim in claims
        if claim.known_at <= cutoff
        and claim.valid_from <= cutoff
        and claim.status is ClaimStatus.ACTIVE
    ]
    unknown = [claim.id for claim in eligible if claim.evidence_id not in evidence_ids]
    if unknown:
        raise ValueError(f"claims reference absent evidence: {unknown}")

    grouped: dict[tuple[str, str, str], list[Claim]] = {}
    for claim in eligible:
        grouped.setdefault(claim.key, []).append(claim)

    selected: list[Claim] = []
    for key, group in grouped.items():
        latest_time = max(item.known_at for item in group)
        latest = [item for item in group if item.known_at == latest_time]
        values = {_stable_value(item.typed_value) for item in latest}
        if len(values) > 1:
            raise EvidenceConflict(f"equally current claims conflict for {key}")
        selected.append(sorted(latest, key=lambda item: str(item.id))[0])
    return tuple(sorted(selected, key=lambda item: item.key))


def _stable_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
