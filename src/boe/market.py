"""Milestone 6 point-in-time market bars and corporate-action normalization."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from boe.models import ContractModel

MARKET_CALCULATION_VERSION = "BOE-M6-MARKET-1"


class MarketDataLicenseAudit(ContractModel):
    provider: str = Field(min_length=1)
    reviewed_at: datetime
    source_url: HttpUrl
    terms_url: HttpUrl | None = None
    api_key_required: bool
    automated_access_approved: bool
    commercial_use_approved: bool
    redistribution_approved: bool
    validation_path_approved: bool
    access_mode: Literal["LOCAL_BULK_SNAPSHOT", "HTTP_API", "FILE"]
    notes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timestamp(self) -> Self:
        _require_aware(self.reviewed_at, "reviewed_at")
        if self.validation_path_approved and self.access_mode == "HTTP_API":
            if not self.automated_access_approved:
                raise ValueError("HTTP validation adapter requires approved automated access")
        return self


class MarketBar(ContractModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    session_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    adjusted_close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        if self.high < max(self.open, self.close, self.adjusted_close, self.low):
            raise ValueError("bar high is below another price field")
        if self.low > min(self.open, self.close, self.adjusted_close, self.high):
            raise ValueError("bar low is above another price field")
        return self


class RawMarketBar(ContractModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    session_date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> Self:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("raw bar high is below another price field")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("raw bar low is above another price field")
        return self


class SplitEvent(ContractModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    effective_session: date
    ratio_new_for_old: Decimal = Field(gt=0)
    known_at: datetime
    evidence_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_known_at(self) -> Self:
        _require_aware(self.known_at, "known_at")
        return self


class MarketSeries(ContractModel):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    provider: str = Field(min_length=1)
    bars: tuple[MarketBar, ...] = Field(min_length=1)
    retrieved_at: datetime
    available_at: datetime
    provider_adjusted: bool
    adjustment_version: str = Field(min_length=1)
    adjustment_as_of: date
    raw_blob_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license_audit_provider: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_series(self) -> Self:
        _require_aware(self.retrieved_at, "retrieved_at")
        _require_aware(self.available_at, "available_at")
        if self.retrieved_at < self.available_at:
            raise ValueError("market series cannot be retrieved before it is available")
        if any(bar.symbol != self.symbol for bar in self.bars):
            raise ValueError("market series contains a different symbol")
        sessions = [bar.session_date for bar in self.bars]
        if sessions != sorted(sessions):
            raise ValueError("market bars must be sorted by session date")
        if len(set(sessions)) != len(sessions):
            raise ValueError("market series contains duplicate sessions")
        if self.adjustment_as_of > self.retrieved_at.date():
            raise ValueError("adjustment_as_of cannot be after retrieval date")
        return self


def normalize_provider_adjusted_bars(
    *,
    symbol: str,
    provider: str,
    bars: tuple[RawMarketBar, ...],
    retrieved_at: datetime,
    available_at: datetime,
    raw_blob_sha256: str,
    license_audit_provider: str,
    adjustment_version: str = MARKET_CALCULATION_VERSION,
) -> MarketSeries:
    """Normalize a provider-adjusted OHLCV snapshot.

    The provider snapshot's corporate-action state is conservatively treated as
    known only as of the retrieval date. Historical reconstruction before that
    date must therefore use an archived snapshot or raw bars plus point-in-time
    corporate actions.
    """
    canonical = tuple(
        MarketBar(
            symbol=bar.symbol,
            session_date=bar.session_date,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            adjusted_close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    )
    return MarketSeries(
        symbol=symbol,
        provider=provider,
        bars=canonical,
        retrieved_at=retrieved_at,
        available_at=available_at,
        provider_adjusted=True,
        adjustment_version=adjustment_version,
        adjustment_as_of=retrieved_at.date(),
        raw_blob_sha256=raw_blob_sha256,
        license_audit_provider=license_audit_provider,
    )


def adjust_raw_bars_for_splits(
    *,
    symbol: str,
    provider: str,
    bars: tuple[RawMarketBar, ...],
    splits: tuple[SplitEvent, ...],
    cutoff: datetime,
    retrieved_at: datetime,
    available_at: datetime,
    raw_blob_sha256: str,
    license_audit_provider: str,
    adjustment_version: str = MARKET_CALCULATION_VERSION,
) -> MarketSeries:
    """Apply only split events publicly known and effective by the cutoff."""
    _require_aware(cutoff, "cutoff")
    applicable = tuple(
        event
        for event in splits
        if event.symbol == symbol
        and event.known_at <= cutoff
        and event.effective_session <= cutoff.date()
    )
    canonical: list[MarketBar] = []
    for bar in bars:
        if bar.symbol != symbol:
            raise ValueError("raw bars contain a different symbol")
        factor = Decimal("1")
        for event in applicable:
            if bar.session_date < event.effective_session:
                factor *= event.ratio_new_for_old
        canonical.append(
            MarketBar(
                symbol=symbol,
                session_date=bar.session_date,
                open=bar.open / factor,
                high=bar.high / factor,
                low=bar.low / factor,
                close=bar.close / factor,
                adjusted_close=bar.close / factor,
                volume=int(Decimal(bar.volume) * factor),
            )
        )
    adjustment_as_of = max(
        (event.known_at.date() for event in applicable),
        default=min(cutoff.date(), retrieved_at.date()),
    )
    return MarketSeries(
        symbol=symbol,
        provider=provider,
        bars=tuple(sorted(canonical, key=lambda item: item.session_date)),
        retrieved_at=retrieved_at,
        available_at=available_at,
        provider_adjusted=False,
        adjustment_version=adjustment_version,
        adjustment_as_of=adjustment_as_of,
        raw_blob_sha256=raw_blob_sha256,
        license_audit_provider=license_audit_provider,
    )


def point_in_time_series(series: MarketSeries, cutoff_session: date) -> MarketSeries:
    """Return bars through a cutoff without silently importing future adjustments."""
    if series.provider_adjusted and series.adjustment_as_of > cutoff_session:
        raise ValueError(
            "provider-adjusted snapshot post-dates the historical cutoff; "
            "use an archived snapshot or point-in-time corporate actions"
        )
    selected = tuple(bar for bar in series.bars if bar.session_date <= cutoff_session)
    if not selected:
        raise ValueError("no complete market bars exist at or before cutoff")
    return series.model_copy(update={"bars": selected})


def series_manifest_sha256(series: MarketSeries) -> str:
    payload = {
        "symbol": series.symbol,
        "provider": series.provider,
        "retrieved_at": series.retrieved_at.isoformat(),
        "available_at": series.available_at.isoformat(),
        "provider_adjusted": series.provider_adjusted,
        "adjustment_version": series.adjustment_version,
        "adjustment_as_of": series.adjustment_as_of.isoformat(),
        "raw_blob_sha256": series.raw_blob_sha256,
        "bars": [
            {
                "session_date": bar.session_date.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "adjusted_close": str(bar.adjusted_close),
                "volume": bar.volume,
            }
            for bar in series.bars
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
