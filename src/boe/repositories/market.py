"""Persistence for Milestone 6 market series and technical snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

from boe.market import MarketDataLicenseAudit, MarketSeries, series_manifest_sha256
from boe.repositories.database import Database, SecurityRow
from boe.technicals import TechnicalSnapshot


class MarketRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_source_audit(self, audit: MarketDataLicenseAudit) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id FROM market_data_source_audits
                    WHERE provider = :provider AND reviewed_at = :reviewed_at
                    """
                ),
                {"provider": audit.provider, "reviewed_at": audit.reviewed_at.isoformat()},
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO market_data_source_audits (
                        id, provider, reviewed_at, source_url, terms_url,
                        api_key_required, automated_access_approved,
                        commercial_use_approved, redistribution_approved,
                        validation_path_approved, access_mode, notes_json, created_at
                    ) VALUES (
                        :id, :provider, :reviewed_at, :source_url, :terms_url,
                        :api_key_required, :automated_access_approved,
                        :commercial_use_approved, :redistribution_approved,
                        :validation_path_approved, :access_mode, :notes_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "provider": audit.provider,
                    "reviewed_at": audit.reviewed_at.isoformat(),
                    "source_url": str(audit.source_url),
                    "terms_url": str(audit.terms_url) if audit.terms_url else None,
                    "api_key_required": audit.api_key_required,
                    "automated_access_approved": audit.automated_access_approved,
                    "commercial_use_approved": audit.commercial_use_approved,
                    "redistribution_approved": audit.redistribution_approved,
                    "validation_path_approved": audit.validation_path_approved,
                    "access_mode": audit.access_mode,
                    "notes_json": json.dumps(audit.notes),
                    "created_at": _now_iso(),
                },
            )
        return row_id

    def add_market_series(self, security_id: str, series: MarketSeries) -> str:
        manifest = series_manifest_sha256(series)
        batch_id = str(uuid4())
        with self.database.session() as session:
            if session.get(SecurityRow, security_id) is None:
                raise ValueError("market series references absent security")
            audit_exists = session.execute(
                text(
                    """
                    SELECT 1 FROM market_data_source_audits
                    WHERE provider = :provider AND validation_path_approved = 1
                    LIMIT 1
                    """
                ),
                {"provider": series.license_audit_provider},
            ).scalar_one_or_none()
            if audit_exists is None:
                raise ValueError("market series has no approved provider audit")
            existing = session.execute(
                text(
                    """
                    SELECT id FROM market_bar_batches
                    WHERE security_id = :security_id
                      AND provider = :provider
                      AND series_manifest_sha256 = :manifest
                    """
                ),
                {
                    "security_id": security_id,
                    "provider": series.provider,
                    "manifest": manifest,
                },
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO market_bar_batches (
                        id, security_id, provider, retrieved_at, available_at,
                        provider_adjusted, adjustment_version, adjustment_as_of,
                        raw_blob_sha256, series_manifest_sha256,
                        license_audit_provider, created_at
                    ) VALUES (
                        :id, :security_id, :provider, :retrieved_at, :available_at,
                        :provider_adjusted, :adjustment_version, :adjustment_as_of,
                        :raw_blob_sha256, :series_manifest_sha256,
                        :license_audit_provider, :created_at
                    )
                    """
                ),
                {
                    "id": batch_id,
                    "security_id": security_id,
                    "provider": series.provider,
                    "retrieved_at": series.retrieved_at.isoformat(),
                    "available_at": series.available_at.isoformat(),
                    "provider_adjusted": series.provider_adjusted,
                    "adjustment_version": series.adjustment_version,
                    "adjustment_as_of": series.adjustment_as_of.isoformat(),
                    "raw_blob_sha256": series.raw_blob_sha256,
                    "series_manifest_sha256": manifest,
                    "license_audit_provider": series.license_audit_provider,
                    "created_at": _now_iso(),
                },
            )
            for bar in series.bars:
                session.execute(
                    text(
                        """
                        INSERT INTO market_bars_daily (
                            id, batch_id, security_id, session_date, open, high, low,
                            close, adjusted_close, volume, provider, adjustment_version,
                            created_at
                        ) VALUES (
                            :id, :batch_id, :security_id, :session_date, :open, :high, :low,
                            :close, :adjusted_close, :volume, :provider, :adjustment_version,
                            :created_at
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "batch_id": batch_id,
                        "security_id": security_id,
                        "session_date": bar.session_date.isoformat(),
                        "open": str(bar.open),
                        "high": str(bar.high),
                        "low": str(bar.low),
                        "close": str(bar.close),
                        "adjusted_close": str(bar.adjusted_close),
                        "volume": bar.volume,
                        "provider": series.provider,
                        "adjustment_version": series.adjustment_version,
                        "created_at": _now_iso(),
                    },
                )
        return batch_id

    def add_technical_snapshot(
        self,
        security_id: str,
        snapshot: TechnicalSnapshot,
    ) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            if session.get(SecurityRow, security_id) is None:
                raise ValueError("technical snapshot references absent security")
            existing = session.execute(
                text(
                    """
                    SELECT id FROM technical_snapshots
                    WHERE security_id = :security_id
                      AND as_of = :as_of
                      AND calculation_version = :calculation_version
                    """
                ),
                {
                    "security_id": security_id,
                    "as_of": snapshot.as_of.isoformat(),
                    "calculation_version": snapshot.calculation_trace.calculation_version,
                },
            ).scalar_one_or_none()
            if existing is not None:
                return str(existing)
            session.execute(
                text(
                    """
                    INSERT INTO technical_snapshots (
                        id, security_id, benchmark_symbol, as_of, session_date, close,
                        sma20, sma50, rsi14, atr14, security_return_20d_pct,
                        benchmark_return_20d_pct, xbi_relative_return_20d_pct,
                        up_down_dollar_volume_ratio, obv_slope, support, resistance,
                        stale, calculation_version, calculation_json, created_at
                    ) VALUES (
                        :id, :security_id, :benchmark_symbol, :as_of, :session_date, :close,
                        :sma20, :sma50, :rsi14, :atr14, :security_return_20d_pct,
                        :benchmark_return_20d_pct, :xbi_relative_return_20d_pct,
                        :up_down_dollar_volume_ratio, :obv_slope, :support, :resistance,
                        :stale, :calculation_version, :calculation_json, :created_at
                    )
                    """
                ),
                {
                    "id": row_id,
                    "security_id": security_id,
                    "benchmark_symbol": snapshot.benchmark_symbol,
                    "as_of": snapshot.as_of.isoformat(),
                    "session_date": snapshot.session_date.isoformat(),
                    "close": str(snapshot.close),
                    "sma20": str(snapshot.sma20),
                    "sma50": str(snapshot.sma50),
                    "rsi14": str(snapshot.rsi14),
                    "atr14": str(snapshot.atr14),
                    "security_return_20d_pct": str(snapshot.security_return_20d_pct),
                    "benchmark_return_20d_pct": str(snapshot.benchmark_return_20d_pct),
                    "xbi_relative_return_20d_pct": str(snapshot.xbi_relative_return_20d_pct),
                    "up_down_dollar_volume_ratio": str(snapshot.up_down_dollar_volume_ratio),
                    "obv_slope": str(snapshot.obv_slope),
                    "support": str(snapshot.support) if snapshot.support is not None else None,
                    "resistance": (
                        str(snapshot.resistance) if snapshot.resistance is not None else None
                    ),
                    "stale": snapshot.stale,
                    "calculation_version": snapshot.calculation_trace.calculation_version,
                    "calculation_json": json.dumps(
                        snapshot.calculation_trace.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "created_at": _now_iso(),
                },
            )
        return row_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
