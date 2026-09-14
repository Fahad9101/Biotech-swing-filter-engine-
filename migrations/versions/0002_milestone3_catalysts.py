"""Milestone 3 catalyst, conflict, confirmation, and scientific-pack schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_milestone3"
down_revision: str | None = "0001_milestone2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalyst_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("indication", sa.String(), nullable=False),
        sa.Column("catalyst_type", sa.String(), nullable=False),
        sa.Column("clinical_phase", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("window_start", sa.String(10), nullable=False),
        sa.Column("window_end", sa.String(10), nullable=False),
        sa.Column("timing_confidence", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("evidence_items.id"), nullable=False),
        sa.Column("source_tier", sa.Integer(), nullable=False),
        sa.Column("known_at", sa.String(40), nullable=False),
        sa.Column("source_statement", sa.Text(), nullable=False),
        sa.Column("external_event_id", sa.String(), nullable=True),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "evidence_id", "canonical_key", "source_statement", name="uq_catalyst_observation"
        ),
    )
    op.create_index("ix_catalyst_observations_key", "catalyst_observations", ["canonical_key"])
    op.create_index("ix_catalyst_observations_known_at", "catalyst_observations", ["known_at"])

    op.create_table(
        "catalyst_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("version_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("asset", sa.String(), nullable=False),
        sa.Column("indication", sa.String(), nullable=False),
        sa.Column("catalyst_type", sa.String(), nullable=False),
        sa.Column("clinical_phase", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("window_start", sa.String(10), nullable=False),
        sa.Column("window_end", sa.String(10), nullable=False),
        sa.Column("timing_confidence", sa.String(), nullable=False),
        sa.Column(
            "primary_evidence_id",
            sa.String(36),
            sa.ForeignKey("evidence_items.id"),
            nullable=False,
        ),
        sa.Column("supporting_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("known_at", sa.String(40), nullable=False),
        sa.Column("resolved_at_cutoff", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("canonical_key", "version", name="uq_catalyst_version"),
    )
    op.create_index("ix_catalyst_versions_key", "catalyst_versions", ["canonical_key"])

    op.create_table(
        "catalyst_conflicts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("observation_ids_json", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("requires_human_resolution", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )

    op.create_table(
        "catalyst_confirmations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("evidence_ids_reviewed_json", sa.Text(), nullable=False),
        sa.Column("conflict_resolution_notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_catalyst_confirmations_version", "catalyst_confirmations", ["catalyst_version_id"]
    )

    op.create_table(
        "scientific_evidence_packs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalyst_version_id",
            sa.String(36),
            sa.ForeignKey("catalyst_versions.id"),
            nullable=False,
        ),
        sa.Column("pack_json", sa.Text(), nullable=False),
        sa.Column("evidence_cutoff", sa.String(40), nullable=False),
        sa.Column("generated_at", sa.String(40), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "catalyst_version_id", "evidence_cutoff", name="uq_scientific_pack_cutoff"
        ),
    )


def downgrade() -> None:
    op.drop_table("scientific_evidence_packs")
    op.drop_table("catalyst_confirmations")
    op.drop_table("catalyst_conflicts")
    op.drop_table("catalyst_versions")
    op.drop_table("catalyst_observations")
