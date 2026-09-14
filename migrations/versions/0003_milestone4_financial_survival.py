"""Milestone 4 financial survival and capital-structure schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_milestone4"
down_revision: str | None = "0002_milestone3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("taxonomy", sa.String(), nullable=False),
        sa.Column("concept", sa.String(), nullable=False),
        sa.Column("value_decimal", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("period_start", sa.String(10), nullable=True),
        sa.Column("period_end", sa.String(10), nullable=True),
        sa.Column("instant", sa.String(10), nullable=True),
        sa.Column("form", sa.String(), nullable=False),
        sa.Column("accession", sa.String(), nullable=False),
        sa.Column("filed_at", sa.String(40), nullable=False),
        sa.Column("source_available_at", sa.String(40), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("fiscal_period", sa.String(), nullable=True),
        sa.Column("frame", sa.String(), nullable=True),
        sa.Column(
            "source_evidence_id",
            sa.String(36),
            sa.ForeignKey("evidence_items.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "issuer_id",
            "taxonomy",
            "concept",
            "unit",
            "accession",
            "period_start",
            "period_end",
            "instant",
            "value_decimal",
            name="uq_financial_fact_observation",
        ),
    )
    op.create_index("ix_financial_facts_issuer_id", "financial_facts", ["issuer_id"])
    op.create_index("ix_financial_facts_accession", "financial_facts", ["accession"])
    op.create_index(
        "ix_financial_facts_available_at", "financial_facts", ["source_available_at"]
    )

    op.create_table(
        "capital_structure_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("basic_shares", sa.Text(), nullable=False),
        sa.Column("dilutive_options", sa.Text(), nullable=False),
        sa.Column("warrants", sa.Text(), nullable=False),
        sa.Column("rsus", sa.Text(), nullable=False),
        sa.Column("convertible_shares", sa.Text(), nullable=False),
        sa.Column("other_dilutive_shares", sa.Text(), nullable=False),
        sa.Column("expected_financing_shares", sa.Text(), nullable=False),
        sa.Column("fully_diluted_shares", sa.Text(), nullable=False),
        sa.Column("projected_fully_diluted_shares", sa.Text(), nullable=False),
        sa.Column(
            "basic_share_fact_id",
            sa.String(36),
            sa.ForeignKey("financial_facts.id"),
            nullable=False,
        ),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("issuer_id", "as_of", name="uq_capital_structure_snapshot"),
    )
    op.create_index(
        "ix_capital_structure_snapshots_issuer",
        "capital_structure_snapshots",
        ["issuer_id"],
    )

    op.create_table(
        "cash_burn_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("quarters_json", sa.Text(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("normalized_quarterly_burn", sa.Text(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("issuer_id", "as_of", name="uq_cash_burn_snapshot"),
    )
    op.create_index("ix_cash_burn_snapshots_issuer", "cash_burn_snapshots", ["issuer_id"])

    op.create_table(
        "survival_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("catalyst_latest_date", sa.String(10), nullable=False),
        sa.Column("liquidity", sa.Text(), nullable=False),
        sa.Column("normalized_quarterly_burn", sa.Text(), nullable=False),
        sa.Column("runway_months", sa.Text(), nullable=False),
        sa.Column("months_to_latest_catalyst", sa.Text(), nullable=False),
        sa.Column("runway_at_catalyst_months", sa.Text(), nullable=False),
        sa.Column("cash_position_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("burn_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "issuer_id",
            "as_of",
            "catalyst_latest_date",
            name="uq_survival_snapshot",
        ),
    )
    op.create_index("ix_survival_snapshots_issuer", "survival_snapshots", ["issuer_id"])

    op.create_table(
        "financing_filings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("cik", sa.String(10), nullable=False),
        sa.Column("accession", sa.String(), nullable=False),
        sa.Column("form", sa.String(), nullable=False),
        sa.Column("filing_date", sa.String(10), nullable=False),
        sa.Column("accepted_at", sa.String(40), nullable=False),
        sa.Column("primary_document", sa.String(), nullable=False),
        sa.Column("filing_url", sa.Text(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("issuer_id", "accession", name="uq_financing_filing_accession"),
    )
    op.create_index("ix_financing_filings_issuer", "financing_filings", ["issuer_id"])
    op.create_index("ix_financing_filings_accepted", "financing_filings", ["accepted_at"])

    op.create_table(
        "financing_facilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("opened_at", sa.String(10), nullable=False),
        sa.Column("capacity_usd", sa.Text(), nullable=True),
        sa.Column("used_usd", sa.Text(), nullable=True),
        sa.Column("remaining_usd", sa.Text(), nullable=True),
        sa.Column("observed_issuance_dependence", sa.Boolean(), nullable=False),
        sa.Column("management_guided_use_before_catalyst", sa.Boolean(), nullable=False),
        sa.Column("evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_financing_facilities_issuer", "financing_facilities", ["issuer_id"])
    op.create_index(
        "ix_financing_facilities_confirmed", "financing_facilities", ["confirmed_at"]
    )

    op.create_table(
        "financing_risk_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("issuer_id", sa.String(36), sa.ForeignKey("issuers.id"), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("issuer_id", "as_of", name="uq_financing_risk_snapshot"),
    )
    op.create_index(
        "ix_financing_risk_snapshots_issuer", "financing_risk_snapshots", ["issuer_id"]
    )


def downgrade() -> None:
    op.drop_table("financing_risk_snapshots")
    op.drop_table("financing_facilities")
    op.drop_table("financing_filings")
    op.drop_table("survival_snapshots")
    op.drop_table("cash_burn_snapshots")
    op.drop_table("capital_structure_snapshots")
    op.drop_table("financial_facts")
