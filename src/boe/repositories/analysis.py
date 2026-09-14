"""SQLAlchemy persistence for Milestone 5 science, valuation, and decisions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from boe.analysis import AnalysisRunRecord, CandidateDecisionSnapshot
from boe.gates import GateEvaluation
from boe.models import FactorScore
from boe.repositories.database import Base, Database
from boe.science_review import ManualScienceReview
from boe.valuation import RnpvInput, RnpvResult


class ScienceReviewRow(Base):
    __tablename__ = "science_reviews"
    __table_args__ = (
        UniqueConstraint(
            "catalyst_version_id",
            "evidence_cutoff",
            "reviewer",
            name="uq_science_review_cutoff_reviewer",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    evidence_cutoff: Mapped[str] = mapped_column(String(40), index=True)
    reviewer: Mapped[str]
    reviewed_at: Mapped[str] = mapped_column(String(40))
    scores_json: Mapped[str] = mapped_column(Text)
    evidence_confidence: Mapped[str]
    source_quality: Mapped[str]
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    rationales_json: Mapped[str] = mapped_column(Text)
    review_flags_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class ValuationAssumptionRow(Base):
    __tablename__ = "valuation_assumptions"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "catalyst_version_id",
            "as_of",
            "scenario",
            name="uq_valuation_assumption_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str]
    assumptions_json: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str]
    created_at: Mapped[str] = mapped_column(String(40))


class ValuationSnapshotRow(Base):
    __tablename__ = "valuation_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "catalyst_version_id",
            "as_of",
            "scenario",
            name="uq_valuation_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str]
    total_asset_rnpv: Mapped[str] = mapped_column(Text)
    equity_value: Mapped[str] = mapped_column(Text)
    fully_diluted_value_per_share: Mapped[str] = mapped_column(Text)
    calculation_json: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str]
    created_at: Mapped[str] = mapped_column(String(40))


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "as_of",
            "rules_version",
            "input_manifest_sha256",
            name="uq_analysis_run_manifest",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(40), index=True)
    rules_version: Mapped[str]
    rules_checksum: Mapped[str] = mapped_column(String(64))
    code_commit_sha: Mapped[str] = mapped_column(String(40))
    data_cutoff: Mapped[str] = mapped_column(String(40))
    status: Mapped[str]
    input_manifest_sha256: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[str] = mapped_column(String(40))
    completed_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))


class FactorScoreRow(Base):
    __tablename__ = "factor_scores"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "issuer_id",
            "catalyst_version_id",
            "factor_code",
            name="uq_factor_score_run_factor",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    factor_code: Mapped[str]
    points: Mapped[int]
    max_points: Mapped[int]
    factor_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class GateResultRow(Base):
    __tablename__ = "gate_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    gate_code: Mapped[str]
    classification: Mapped[str]
    precedence: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)
    observed_value: Mapped[str] = mapped_column(Text)
    threshold: Mapped[str] = mapped_column(Text)
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class CandidateDecisionRow(Base):
    __tablename__ = "candidate_decisions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id",
            "issuer_id",
            "catalyst_version_id",
            name="uq_candidate_decision_run",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"), index=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    catalyst_version_id: Mapped[str] = mapped_column(String(36), index=True)
    raw_score: Mapped[int]
    coverage_pct: Mapped[str] = mapped_column(Text)
    classification: Mapped[str]
    pos_low: Mapped[str] = mapped_column(Text)
    pos_mid: Mapped[str] = mapped_column(Text)
    pos_high: Mapped[str] = mapped_column(Text)
    success_return_low: Mapped[str] = mapped_column(Text)
    success_return_mid: Mapped[str] = mapped_column(Text)
    success_return_high: Mapped[str] = mapped_column(Text)
    failure_return_low: Mapped[str] = mapped_column(Text)
    failure_return_mid: Mapped[str] = mapped_column(Text)
    failure_return_high: Mapped[str] = mapped_column(Text)
    base_ev: Mapped[str] = mapped_column(Text)
    conservative_ev: Mapped[str] = mapped_column(Text)
    reward_risk: Mapped[str] = mapped_column(Text)
    decision_trace_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class Milestone5Repository:
    """Append-only persistence for locked Milestone 5 review and decision artifacts."""

    MODEL_VERSION = "BOE-M5-1"

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_science_review(self, review: ManualScienceReview) -> str:
        row_id = str(uuid4())
        flags = {
            "single_arm_when_comparator_required": review.single_arm_when_comparator_required,
            "multiplicity_or_endpoint_ambiguity": review.multiplicity_or_endpoint_ambiguity,
            "material_unresolved_safety_imbalance": review.material_unresolved_safety_imbalance,
            "unresolved_clinical_hold": review.unresolved_clinical_hold,
            "unbounded_safety_risk": review.unbounded_safety_risk,
            "fatal_trial_interpretability_defect": review.fatal_trial_interpretability_defect,
        }
        with self.database.session() as session:
            session.add(
                ScienceReviewRow(
                    id=row_id,
                    issuer_id=review.issuer_id,
                    catalyst_version_id=str(review.catalyst_version_id),
                    evidence_cutoff=review.evidence_cutoff.isoformat(),
                    reviewer=review.reviewer,
                    reviewed_at=review.reviewed_at.isoformat(),
                    scores_json=_json(review.score_by_code()),
                    evidence_confidence=review.evidence_confidence.value,
                    source_quality=review.source_quality,
                    evidence_ids_json=_json(review.evidence_ids),
                    rationales_json=_json(review.rationales),
                    review_flags_json=_json(flags),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_valuation_assumptions(self, input_: RnpvInput) -> str:
        row_id = str(uuid4())
        evidence_ids = list(input_.bridge.evidence_ids)
        for asset in input_.assets:
            for cash_flow in asset.annual_cash_flows:
                evidence_ids.extend(cash_flow.evidence_ids)
            evidence_ids.extend(asset.terminal_support_ids)
        with self.database.session() as session:
            session.add(
                ValuationAssumptionRow(
                    id=row_id,
                    issuer_id=input_.issuer_id,
                    catalyst_version_id=str(input_.catalyst_version_id),
                    as_of=input_.as_of.isoformat(),
                    scenario=input_.scenario,
                    assumptions_json=_json(input_),
                    evidence_ids_json=_json(tuple(dict.fromkeys(evidence_ids))),
                    model_version=self.MODEL_VERSION,
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_valuation_snapshot(self, result: RnpvResult) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                ValuationSnapshotRow(
                    id=row_id,
                    issuer_id=result.issuer_id,
                    catalyst_version_id=str(result.catalyst_version_id),
                    as_of=result.as_of.isoformat(),
                    scenario=result.scenario,
                    total_asset_rnpv=str(result.total_asset_rnpv),
                    equity_value=str(result.equity_value),
                    fully_diluted_value_per_share=str(result.fully_diluted_value_per_share),
                    calculation_json=_json(result),
                    model_version=self.MODEL_VERSION,
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_analysis_run(self, run: AnalysisRunRecord) -> None:
        with self.database.session() as session:
            session.add(
                AnalysisRunRow(
                    id=str(run.id),
                    as_of=run.as_of.isoformat(),
                    rules_version=run.rules_version,
                    rules_checksum=run.rules_checksum,
                    code_commit_sha=run.code_commit_sha,
                    data_cutoff=run.data_cutoff.isoformat(),
                    status=run.status,
                    input_manifest_sha256=run.input_manifest_sha256,
                    started_at=run.started_at.isoformat(),
                    completed_at=run.completed_at.isoformat() if run.completed_at else None,
                    created_at=_now_iso(),
                )
            )

    def add_factor_score(
        self,
        *,
        analysis_run_id: str,
        issuer_id: str,
        catalyst_version_id: str,
        factor: FactorScore,
    ) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                FactorScoreRow(
                    id=row_id,
                    analysis_run_id=analysis_run_id,
                    issuer_id=issuer_id,
                    catalyst_version_id=catalyst_version_id,
                    factor_code=factor.code.value,
                    points=factor.points,
                    max_points=factor.max_points,
                    factor_json=_json(factor),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_gate_results(
        self,
        *,
        analysis_run_id: str,
        issuer_id: str,
        catalyst_version_id: str,
        gates: GateEvaluation,
    ) -> tuple[str, ...]:
        row_ids: list[str] = []
        with self.database.session() as session:
            for gate in gates.triggered:
                row_id = str(uuid4())
                row_ids.append(row_id)
                session.add(
                    GateResultRow(
                        id=row_id,
                        analysis_run_id=analysis_run_id,
                        issuer_id=issuer_id,
                        catalyst_version_id=catalyst_version_id,
                        gate_code=gate.code,
                        classification=gate.classification.value,
                        precedence=gate.precedence,
                        reason=gate.reason,
                        observed_value=gate.observed_value,
                        threshold=gate.threshold,
                        evidence_ids_json=_json(gate.evidence_ids),
                        created_at=_now_iso(),
                    )
                )
        return tuple(row_ids)

    def add_candidate_decision(self, decision: CandidateDecisionSnapshot) -> str:
        row_id = str(uuid4())
        pos = decision.pos.assessment.event_success_pct
        valuation = decision.valuation
        with self.database.session() as session:
            session.add(
                CandidateDecisionRow(
                    id=row_id,
                    analysis_run_id=str(decision.analysis_run_id),
                    issuer_id=decision.issuer_id,
                    catalyst_version_id=str(decision.catalyst_version_id),
                    raw_score=decision.score.raw_total,
                    coverage_pct=str(decision.coverage_pct),
                    classification=decision.classification.classification.value,
                    pos_low=str(pos.low),
                    pos_mid=str(pos.mid),
                    pos_high=str(pos.high),
                    success_return_low=str(valuation.success_return_pct.low),
                    success_return_mid=str(valuation.success_return_pct.mid),
                    success_return_high=str(valuation.success_return_pct.high),
                    failure_return_low=str(valuation.failure_return_pct.low),
                    failure_return_mid=str(valuation.failure_return_pct.mid),
                    failure_return_high=str(valuation.failure_return_pct.high),
                    base_ev=str(decision.expected_value.base_ev_pct),
                    conservative_ev=str(decision.expected_value.conservative_ev_pct),
                    reward_risk=str(decision.expected_value.reward_risk),
                    decision_trace_json=_json(decision.decision_trace),
                    created_at=_now_iso(),
                )
            )
        return row_id


def _json(value: object) -> str:
    payload: object
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        payload = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else str(item)
            for item in value
        ]
    else:
        payload = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
