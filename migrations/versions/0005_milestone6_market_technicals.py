"""Milestone 6 market bars, provider audits, and technical snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_milestone6"
down_revision: str | None = "0004_milestone5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_data_source_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.String(40), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("terms_url", sa.Text(), nullable=True),
        sa.Column("api_key_required", sa.Boolean(), nullable=False),
        sa.Column("automated_access_approved", sa.Boolean(), nullable=False),
        sa.Column("commercial_use_approved", sa.Boolean(), nullable=False),
        sa.Column("redistribution_approved", sa.Boolean(), nullable=False),
        sa.Column("validation_path_approved", sa.Boolean(), nullable=False),
        sa.Column("access_mode", sa.String(), nullable=False),
        sa.Column("notes_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("provider", "reviewed_at", name="uq_market_data_source_audit"),
    )

    op.create_table(
        "market_bar_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("retrieved_at", sa.String(40), nullable=False),
        sa.Column("available_at", sa.String(40), nullable=False),
        sa.Column("provider_adjusted", sa.Boolean(), nullable=False),
        sa.Column("adjustment_version", sa.String(), nullable=False),
        sa.Column("adjustment_as_of", sa.String(10), nullable=False),
        sa.Column("raw_blob_sha256", sa.String(64), nullable=False),
        sa.Column("series_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("license_audit_provider", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "security_id",
            "provider",
            "series_manifest_sha256",
            name="uq_market_bar_batch_manifest",
        ),
    )
    op.create_index("ix_market_bar_batches_security", "market_bar_batches", ["security_id"])
    op.create_index("ix_market_bar_batches_retrieved", "market_bar_batches", ["retrieved_at"])

    op.create_table(
        "market_bars_daily",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("market_bar_batches.id"), nullable=False),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("session_date", sa.String(10), nullable=False),
        sa.Column("open", sa.Text(), nullable=False),
        sa.Column("high", sa.Text(), nullable=False),
        sa.Column("low", sa.Text(), nullable=False),
        sa.Column("close", sa.Text(), nullable=False),
        sa.Column("adjusted_close", sa.Text(), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("adjustment_version", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("batch_id", "session_date", name="uq_market_bar_batch_session"),
    )
    op.create_index(
        "ix_market_bars_security_session",
        "market_bars_daily",
        ["security_id", "session_date"],
    )

    op.create_table(
        "technical_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("security_id", sa.String(36), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("benchmark_symbol", sa.String(), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("session_date", sa.String(10), nullable=False),
        sa.Column("close", sa.Text(), nullable=False),
        sa.Column("sma20", sa.Text(), nullable=False),
        sa.Column("sma50", sa.Text(), nullable=False),
        sa.Column("rsi14", sa.Text(), nullable=False),
        sa.Column("atr14", sa.Text(), nullable=False),
        sa.Column("security_return_20d_pct", sa.Text(), nullable=False),
        sa.Column("benchmark_return_20d_pct", sa.Text(), nullable=False),
        sa.Column("xbi_relative_return_20d_pct", sa.Text(), nullable=False),
        sa.Column("up_down_dollar_volume_ratio", sa.Text(), nullable=False),
        sa.Column("obv_slope", sa.Text(), nullable=False),
        sa.Column("support", sa.Text(), nullable=True),
        sa.Column("resistance", sa.Text(), nullable=True),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("calculation_version", sa.String(), nullable=False),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "security_id",
            "as_of",
            "calculation_version",
            name="uq_technical_snapshot",
        ),
    )
    op.create_index(
        "ix_technical_snapshots_security_as_of",
        "technical_snapshots",
        ["security_id", "as_of"],
    )


def downgrade() -> None:
    op.drop_table("technical_snapshots")
    op.drop_table("market_bars_daily")
    op.drop_table("market_bar_batches")
    op.drop_table("market_data_source_audits")
