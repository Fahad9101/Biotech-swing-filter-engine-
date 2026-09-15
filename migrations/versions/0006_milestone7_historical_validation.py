"""Milestone 7 frozen cohort, decisions, outcomes, and validation artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_milestone7"
down_revision: str | None = "0005_milestone6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_cohort_manifests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("frozen_at", sa.String(40), nullable=False),
        sa.Column("registry_sha256", sa.String(64), nullable=False),
        sa.Column("cohort_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "historical_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "manifest_id",
            sa.String(36),
            sa.ForeignKey("historical_cohort_manifests.id"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("issuer_id", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("company", sa.Text(), nullable=False),
        sa.Column("asset", sa.Text(), nullable=False),
        sa.Column("indication", sa.Text(), nullable=False),
        sa.Column("catalyst_type", sa.String(), nullable=False),
        sa.Column("clinical_phase", sa.String(), nullable=False),
        sa.Column("primary_stratum", sa.String(), nullable=False),
        sa.Column("event_at", sa.String(40), nullable=False),
        sa.Column("negative_event", sa.Boolean(), nullable=False),
        sa.Column("financing_window", sa.Boolean(), nullable=False),
        sa.Column("single_asset_issuer", sa.Boolean(), nullable=False),
        sa.Column("source_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("manifest_id", "event_id", name="uq_historical_manifest_event"),
    )
    op.create_index("ix_historical_events_event_at", "historical_events", ["event_at"])
    op.create_index("ix_historical_events_ticker", "historical_events", ["ticker"])

    op.create_table(
        "historical_decision_locks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("snapshot_label", sa.String(), nullable=False),
        sa.Column("snapshot_cutoff", sa.String(40), nullable=False),
        sa.Column("locked_at", sa.String(40), nullable=False),
        sa.Column("code_sha", sa.String(40), nullable=False),
        sa.Column("rules_checksum", sa.String(64), nullable=False),
        sa.Column("input_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("raw_score", sa.Integer(), nullable=False),
        sa.Column("coverage_pct", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("gate_codes_json", sa.Text(), nullable=False),
        sa.Column("pos_json", sa.Text(), nullable=False),
        sa.Column("valuation_json", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("event_id", "snapshot_label", name="uq_historical_event_snapshot"),
    )

    op.create_table(
        "historical_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False, unique=True),
        sa.Column("t0_session", sa.String(10), nullable=False),
        sa.Column("outcome_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "historical_failure_analysis",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False, unique=True),
        sa.Column("failure_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "historical_leakage_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("detected", sa.Boolean(), nullable=False),
        sa.Column("repaired", sa.Boolean(), nullable=False),
        sa.Column("finding_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("event_id", "code", name="uq_historical_leakage_finding"),
    )

    op.create_table(
        "historical_validation_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cohort_sha256", sa.String(64), nullable=False),
        sa.Column("code_sha", sa.String(40), nullable=False),
        sa.Column("rules_checksum", sa.String(64), nullable=False),
        sa.Column("recommendation", sa.String(), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("cohort_sha256", "code_sha", name="uq_historical_validation_report"),
    )


def downgrade() -> None:
    op.drop_table("historical_validation_reports")
    op.drop_table("historical_leakage_audit")
    op.drop_table("historical_failure_analysis")
    op.drop_table("historical_outcomes")
    op.drop_table("historical_decision_locks")
    op.drop_table("historical_events")
    op.drop_table("historical_cohort_manifests")
