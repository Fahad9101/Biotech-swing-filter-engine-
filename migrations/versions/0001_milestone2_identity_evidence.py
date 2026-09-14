"""Milestone 2 identity and evidence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_milestone2"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_payloads",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.String(40), nullable=False),
        sa.Column("available_at", sa.String(40), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_type", sa.String(), nullable=False),
        sa.Column("source_tier", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.String(40), nullable=True),
        sa.Column("available_at", sa.String(40), nullable=False),
        sa.Column("retrieved_at", sa.String(40), nullable=False),
        sa.Column("accession_or_external_id", sa.String(), nullable=True),
        sa.Column(
            "raw_blob_sha256", sa.String(64), sa.ForeignKey("raw_payloads.sha256"), nullable=False
        ),
        sa.Column("excerpt_locator", sa.Text(), nullable=True),
        sa.Column("supports_claim", sa.Text(), nullable=False),
        sa.Column("quality_flag", sa.String(), nullable=True),
        sa.Column(
            "supersedes_id", sa.String(36), sa.ForeignKey("evidence_items.id"), nullable=True
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_evidence_items_available_at", "evidence_items", ["available_at"])
    op.create_table(
        "claims",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subject_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("field_name", sa.String(), nullable=False),
        sa.Column("typed_value_json", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("evidence_items.id"), nullable=False),
        sa.Column("valid_from", sa.String(40), nullable=False),
        sa.Column("known_at", sa.String(40), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "field_name",
            "known_at",
            "evidence_id",
            name="uq_claim_observation",
        ),
    )
    op.create_index("ix_claims_known_at", "claims", ["known_at"])
    op.create_table(
        "issuers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cik", sa.String(10), nullable=False, unique=True),
        sa.Column("legal_name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("sic", sa.String(), nullable=True),
        sa.Column("filer_type", sa.String(), nullable=True),
        sa.Column("reporting_currency", sa.String(), nullable=True),
        sa.Column("business_class", sa.String(), nullable=True),
        sa.Column("universe_status", sa.String(), nullable=True),
        sa.Column("classification_rationale", sa.Text(), nullable=True),
        sa.Column("latest_periodic_filing_date", sa.String(), nullable=True),
        sa.Column("latest_periodic_form", sa.String(), nullable=True),
        sa.Column("reporting_current", sa.Boolean(), nullable=True),
        sa.Column(
            "source_raw_blob_sha256",
            sa.String(64),
            sa.ForeignKey("raw_payloads.sha256"),
            nullable=False,
        ),
        sa.Column("source_available_at", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_issuers_cik", "issuers", ["cik"])
    op.create_table(
        "securities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("ticker", sa.String(14), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("exchange_code", sa.String(), nullable=False),
        sa.Column("security_name", sa.String(), nullable=False),
        sa.Column("security_kind", sa.String(), nullable=False),
        sa.Column("adr_flag", sa.Boolean(), nullable=False),
        sa.Column("listing_status", sa.String(), nullable=False),
        sa.Column("first_trade_date", sa.String(), nullable=True),
        sa.Column("last_trade_date", sa.String(), nullable=True),
        sa.Column("test_issue", sa.Boolean(), nullable=False),
        sa.Column("etf", sa.Boolean(), nullable=False),
        sa.Column("next_shares", sa.Boolean(), nullable=False),
        sa.Column(
            "source_raw_blob_sha256",
            sa.String(64),
            sa.ForeignKey("raw_payloads.sha256"),
            nullable=False,
        ),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("ticker", "exchange_code", name="uq_security_symbol"),
    )
    op.create_index("ix_securities_issuer_id", "securities", ["issuer_id"])
    op.create_index("ix_securities_ticker", "securities", ["ticker"])
    op.create_table(
        "universe_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("investability_floor_status", sa.String(), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("supporting_claim_ids_json", sa.Text(), nullable=False),
        sa.Column("rules_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("as_of", "security_id", "rules_version", name="uq_universe_snapshot"),
    )
    op.create_index("ix_universe_snapshots_as_of", "universe_snapshots", ["as_of"])
    op.create_index("ix_universe_snapshots_security_id", "universe_snapshots", ["security_id"])


def downgrade() -> None:
    op.drop_table("universe_snapshots")
    op.drop_table("securities")
    op.drop_table("issuers")
    op.drop_table("claims")
    op.drop_table("evidence_items")
    op.drop_table("raw_payloads")
