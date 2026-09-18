"""Persistence for Milestone 7 historical-validation artifacts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from boe.historical_validation import (
    CohortManifest,
    FailureAnalysisRecord,
    HistoricalDecisionLock,
    HistoricalOutcome,
    LeakageFinding,
    ValidationSummary,
)
from boe.repositories.database import Database


class HistoricalValidationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_manifest(self, manifest: CohortManifest) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id FROM historical_cohort_manifests
                    WHERE cohort_sha256 = :cohort_sha256
                    """
                ),
                {"cohort_sha256": manifest.cohort_sha256},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO historical_cohort_manifests (
                        id, seed, rules_version, frozen_at, registry_sha256,
                        cohort_sha256, event_count, manifest_json, created_at
                    ) VALUES (
                        :id, :seed, :rules_version, :frozen_at, :registry_sha256,
                        :cohort_sha256, :event_count, :manifest_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "seed": manifest.seed,
                    "rules_version": manifest.rules_version,
                    "frozen_at": manifest.frozen_at.isoformat(),
                    "registry_sha256": manifest.registry_sha256,
                    "cohort_sha256": manifest.cohort_sha256,
                    "event_count": len(manifest.events),
                    "manifest_json": _json(manifest.model_dump(mode="json")),
                    "created_at": _now_iso(),
                },
            )
            for event in manifest.events:
                session.execute(
                    text(
                        """
                        INSERT INTO historical_events (
                            id, manifest_id, event_id, issuer_id, ticker, cik, company,
                            asset, indication, catalyst_type, clinical_phase,
                            primary_stratum, event_at, negative_event,
                            financing_window, single_asset_issuer, source_ids_json,
                            created_at
                        ) VALUES (
                            :id, :manifest_id, :event_id, :issuer_id, :ticker, :cik,
                            :company, :asset, :indication, :catalyst_type,
                            :clinical_phase, :primary_stratum, :event_at,
                            :negative_event, :financing_window, :single_asset_issuer,
                            :source_ids_json, :created_at
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "manifest_id": row_id,
                        "event_id": event.event_id,
                        "issuer_id": event.issuer_id,
                        "ticker": event.ticker,
                        "cik": event.cik,
                        "company": event.company,
                        "asset": event.asset,
                        "indication": event.indication,
                        "catalyst_type": event.catalyst_type.value,
                        "clinical_phase": event.clinical_phase,
                        "primary_stratum": event.primary_stratum.value,
                        "event_at": event.event_at.isoformat(),
                        "negative_event": event.negative_event,
                        "financing_window": event.financing_t_minus_90_to_t_plus_30,
                        "single_asset_issuer": event.single_asset_issuer,
                        "source_ids_json": _json(event.source_ids),
                        "created_at": _now_iso(),
                    },
                )
        return row_id

    def add_decision(self, decision: HistoricalDecisionLock) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id FROM historical_decision_locks
                    WHERE event_id = :event_id AND snapshot_label = :snapshot_label
                    """
                ),
                {"event_id": decision.event_id, "snapshot_label": decision.snapshot_label.value},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO historical_decision_locks (
                        id, event_id, snapshot_label, snapshot_cutoff, locked_at,
                        code_sha, rules_checksum, input_manifest_sha256,
                        raw_score, coverage_pct, classification, gate_codes_json,
                        pos_json, valuation_json, evidence_ids_json, created_at
                    ) VALUES (
                        :id, :event_id, :snapshot_label, :snapshot_cutoff, :locked_at,
                        :code_sha, :rules_checksum, :input_manifest_sha256,
                        :raw_score, :coverage_pct, :classification, :gate_codes_json,
                        :pos_json, :valuation_json, :evidence_ids_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "event_id": decision.event_id,
                    "snapshot_label": decision.snapshot_label.value,
                    "snapshot_cutoff": decision.snapshot_cutoff.isoformat(),
                    "locked_at": decision.locked_at.isoformat(),
                    "code_sha": decision.code_sha,
                    "rules_checksum": decision.rules_checksum,
                    "input_manifest_sha256": decision.input_manifest_sha256,
                    "raw_score": decision.raw_score,
                    "coverage_pct": str(decision.coverage_pct),
                    "classification": decision.classification.value,
                    "gate_codes_json": _json(decision.gate_codes),
                    "pos_json": _json(
                        {
                            "low": decision.pos_low_pct,
                            "mid": decision.pos_mid_pct,
                            "high": decision.pos_high_pct,
                        }
                    ),
                    "valuation_json": _json(
                        {
                            "conservative": str(decision.conservative_equity_value),
                            "base": str(decision.base_equity_value),
                            "bull": str(decision.bull_equity_value),
                            "base_ev_pct": str(decision.base_ev_pct),
                        }
                    ),
                    "evidence_ids_json": _json(decision.evidence_ids),
                    "created_at": _now_iso(),
                },
            )
        return row_id

    def add_outcome(self, outcome: HistoricalOutcome) -> str:
        return self._add_json_once(
            table="historical_outcomes",
            key_column="event_id",
            key=outcome.event_id,
            extra_columns={"t0_session": outcome.t0_session.isoformat()},
            json_column="outcome_json",
            payload=outcome.model_dump(mode="json"),
        )

    def add_failure(self, failure: FailureAnalysisRecord) -> str:
        return self._add_json_once(
            table="historical_failure_analysis",
            key_column="event_id",
            key=failure.event_id,
            extra_columns={},
            json_column="failure_json",
            payload=failure.model_dump(mode="json"),
        )

    def add_leakage_finding(self, finding: LeakageFinding) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id FROM historical_leakage_audit
                    WHERE event_id = :event_id AND code = :code
                    """
                ),
                {"event_id": finding.event_id, "code": finding.code},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO historical_leakage_audit (
                        id, event_id, code, detected, repaired, finding_json, created_at
                    ) VALUES (
                        :id, :event_id, :code, :detected, :repaired, :finding_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "event_id": finding.event_id,
                    "code": finding.code,
                    "detected": finding.detected,
                    "repaired": finding.repaired,
                    "finding_json": _json(finding.model_dump(mode="json")),
                    "created_at": _now_iso(),
                },
            )
        return row_id

    def add_report(
        self,
        *,
        cohort_sha256: str,
        code_sha: str,
        rules_checksum: str,
        summary: ValidationSummary,
    ) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id FROM historical_validation_reports
                    WHERE cohort_sha256 = :cohort_sha256 AND code_sha = :code_sha
                    """
                ),
                {"cohort_sha256": cohort_sha256, "code_sha": code_sha},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO historical_validation_reports (
                        id, cohort_sha256, code_sha, rules_checksum,
                        recommendation, summary_json, created_at
                    ) VALUES (
                        :id, :cohort_sha256, :code_sha, :rules_checksum,
                        :recommendation, :summary_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "cohort_sha256": cohort_sha256,
                    "code_sha": code_sha,
                    "rules_checksum": rules_checksum,
                    "recommendation": summary.recommendation.value,
                    "summary_json": _json(summary.model_dump(mode="json")),
                    "created_at": _now_iso(),
                },
            )
        return row_id

    def _add_json_once(
        self,
        *,
        table: str,
        key_column: str,
        key: str,
        extra_columns: dict[str, str],
        json_column: str,
        payload: object,
    ) -> str:
        allowed = {
            "historical_outcomes": ("event_id", "outcome_json"),
            "historical_failure_analysis": ("event_id", "failure_json"),
        }
        if allowed.get(table) != (key_column, json_column):
            raise ValueError("unsupported historical validation persistence target")
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(f"SELECT id FROM {table} WHERE {key_column} = :key"),
                {"key": key},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            columns = ["id", key_column, *extra_columns, json_column, "created_at"]
            binds = [f":{column}" for column in columns]
            values: dict[str, object] = {
                "id": row_id,
                key_column: key,
                **extra_columns,
                json_column: _json(payload),
                "created_at": _now_iso(),
            }
            session.execute(
                text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(binds)})"),
                values,
            )
        return row_id


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
