"""Auditable Milestone 5 analysis-run and candidate-decision records."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.decisioning import ClassificationResult
from boe.gates import GateEvaluation
from boe.models import ContractModel, ScoreBreakdown, Valuation
from boe.pos import PosResult
from boe.valuation import ExpectedValueResult


class AnalysisRunRecord(ContractModel):
    id: UUID
    as_of: datetime
    rules_version: Literal["BOE-1.0.0"] = "BOE-1.0.0"
    rules_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    data_cutoff: datetime
    input_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["STARTED", "COMPLETED", "FAILED"]
    started_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        for field_name, value in (
            ("as_of", self.as_of),
            ("data_cutoff", self.data_cutoff),
            ("started_at", self.started_at),
        ):
            _require_aware(value, field_name)
        if self.completed_at is not None:
            _require_aware(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
        if self.data_cutoff > self.as_of:
            raise ValueError("analysis data cutoff cannot exceed as_of")
        if self.status == "COMPLETED" and self.completed_at is None:
            raise ValueError("completed analysis run requires completed_at")
        return self


class CandidateDecisionSnapshot(ContractModel):
    analysis_run_id: UUID
    issuer_id: str = Field(min_length=1)
    catalyst_version_id: UUID
    score: ScoreBreakdown
    coverage_pct: Decimal = Field(ge=0, le=100)
    classification: ClassificationResult
    pos: PosResult
    valuation: Valuation
    expected_value: ExpectedValueResult
    gates: GateEvaluation
    decision_trace: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reconcile_decision(self) -> Self:
        if self.classification.raw_score != self.score.raw_total:
            raise ValueError("classification raw score does not match score breakdown")
        if self.classification.coverage_pct != self.coverage_pct:
            raise ValueError("classification coverage does not match decision coverage")
        if Decimal(str(self.valuation.base_expected_return_pct)) != self.expected_value.base_ev_pct:
            raise ValueError("valuation base EV does not match expected-value result")
        if (
            Decimal(str(self.valuation.conservative_expected_return_pct))
            != self.expected_value.conservative_ev_pct
        ):
            raise ValueError("valuation conservative EV does not match expected-value result")
        return self


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
