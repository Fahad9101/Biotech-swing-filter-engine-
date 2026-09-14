"""Milestone 5 science review, valuation, scoring, gates, and decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_milestone5"
down_revision: str | None = "0003_milestone4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "science_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("evidence_cutoff", sa.String(40), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.String(40), nullable=False),
        sa.Column("scores_json", sa.Text(), nullable=False),
        sa.Column("evidence_confidence", sa.String(), nullable=False),
        sa.Column("source_quality", sa.String(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("rationales_json", sa.Text(), nullable=False),
        sa.Column("review_flags_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "catalyst_version_id",
            "evidence_cutoff",
            "reviewer",
            name="uq_science_review_cutoff_reviewer",
        ),
    )
    op.create_index("ix_science_reviews_issuer", "science_reviews", ["issuer_id"])
    op.create_index("ix_science_reviews_cutoff", "science_reviews", ["evidence_cutoff"])

    op.create_table(
        "valuation_assumptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("scenario", sa.String(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "issuer_id",
            "catalyst_version_id",
            "as_of",
            "scenario",
            name="uq_valuation_assumption_snapshot",
        ),
    )

    op.create_table(
        "valuation_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("scenario", sa.String(), nullable=False),
        sa.Column("total_asset_rnpv", sa.Text(), nullable=False),
        sa.Column("equity_value", sa.Text(), nullable=False),
        sa.Column("fully_diluted_value_per_share", sa.Text(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "issuer_id",
            "catalyst_version_id",
            "as_of",
            "scenario",
            name="uq_valuation_snapshot",
        ),
    )

    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("rules_checksum", sa.String(64), nullable=False),
        sa.Column("code_commit_sha", sa.String(40), nullable=False),
        sa.Column("data_cutoff", sa.String(40), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("input_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("started_at", sa.String(40), nullable=False),
        sa.Column("completed_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "as_of",
            "rules_version",
            "input_manifest_sha256",
            name="uq_analysis_run_manifest",
        ),
    )
    op.create_index("ix_analysis_runs_as_of", "analysis_runs", ["as_of"])

    op.create_table(
        "factor_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_run_id",
            sa.String(36),
            sa.ForeignKey("analysis_runs.id"),
            nullable=False,
        ),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("factor_code", sa.String(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.Column("factor_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "analysis_run_id",
            "issuer_id",
            "catalyst_version_id",
            "factor_code",
            name="uq_factor_score_run_factor",
        ),
    )

    op.create_table(
        "gate_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_run_id",
            sa.String(36),
            sa.ForeignKey("analysis_runs.id"),
            nullable=False,
        ),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("gate_code", sa.String(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("precedence", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("observed_value", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Text(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_gate_results_run", "gate_results", ["analysis_run_id"])

    op.create_table(
        "candidate_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "analysis_run_id",
            sa.String(36),
            sa.ForeignKey("analysis_runs.id"),
            nullable=False,
        ),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("raw_score", sa.Integer(), nullable=False),
        sa.Column("coverage_pct", sa.Text(), nullable=False),
        sa.Column("classification", sa.String(), nullable=False),
        sa.Column("pos_low", sa.Text(), nullable=False),
        sa.Column("pos_mid", sa.Text(), nullable=False),
        sa.Column("pos_high", sa.Text(), nullable=False),
        sa.Column("success_return_low", sa.Text(), nullable=False),
        sa.Column("success_return_mid", sa.Text(), nullable=False),
        sa.Column("success_return_high", sa.Text(), nullable=False),
        sa.Column("failure_return_low", sa.Text(), nullable=False),
        sa.Column("failure_return_mid", sa.Text(), nullable=False),
        sa.Column("failure_return_high", sa.Text(), nullable=False),
        sa.Column("base_ev", sa.Text(), nullable=False),
        sa.Column("conservative_ev", sa.Text(), nullable=False),
        sa.Column("reward_risk", sa.Text(), nullable=False),
        sa.Column("decision_trace_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "analysis_run_id",
            "issuer_id",
            "catalyst_version_id",
            name="uq_candidate_decision_run",
        ),
    )


def downgrade() -> None:
    op.drop_table("candidate_decisions")
    op.drop_table("gate_results")
    op.drop_table("factor_scores")
    op.drop_table("analysis_runs")
    op.drop_table("valuation_snapshots")
    op.drop_table("valuation_assumptions")
    op.drop_table("science_reviews")
