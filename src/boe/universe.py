"""Deterministic Milestone 2 biotech-universe classification."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Self

from pydantic import Field, model_validator

from boe.enums import (
    Exchange,
    InvestabilityFloorStatus,
    LeadEconomicAssetType,
    SecurityKind,
    UniverseStatus,
)
from boe.models import ContractModel


class ListingRecord(ContractModel):
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,13}$")
    security_name: str = Field(min_length=1)
    exchange: Exchange | None
    exchange_code: str = Field(min_length=1, max_length=4)
    security_kind: SecurityKind
    test_issue: bool
    etf: bool
    next_shares: bool
    financial_status: str | None
    source_row: int = Field(gt=0)


class SecTickerMapping(ContractModel):
    cik: str = Field(pattern=r"^[0-9]{10}$")
    legal_name: str = Field(min_length=1)
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,13}$")
    exchange: str = Field(min_length=1)


class SecSubmissionProfile(ContractModel):
    cik: str = Field(pattern=r"^[0-9]{10}$")
    legal_name: str = Field(min_length=1)
    sic: str | None = Field(default=None, pattern=r"^[0-9]{4}$")
    sic_description: str | None
    entity_type: str | None
    filer_category: str | None
    country: str | None
    tickers: tuple[str, ...]
    exchanges: tuple[str, ...]
    latest_periodic_filing_date: date | None
    latest_periodic_form: str | None
    reporting_current: bool | None
    source_available_at: datetime

    @model_validator(mode="after")
    def aligned_tickers_and_exchanges(self) -> Self:
        if self.source_available_at.tzinfo is None:
            raise ValueError("source_available_at must be timezone-aware")
        if len(self.tickers) != len(self.exchanges):
            raise ValueError("SEC profile tickers and exchanges must align")
        return self


class BusinessEvidence(ContractModel):
    lead_economic_asset_type: LeadEconomicAssetType
    active_therapeutic_assets: int = Field(ge=0)
    therapeutic_focus_share_pct: float | None = Field(default=None, ge=0, le=100)
    mature_diversified_pharma: bool = False
    pure_exclusion_categories: tuple[LeadEconomicAssetType, ...] = ()
    supporting_claim_ids: tuple[str, ...] = ()
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_evidence(self) -> Self:
        if len(set(self.supporting_claim_ids)) != len(self.supporting_claim_ids):
            raise ValueError("supporting claim ids must be unique")
        if LeadEconomicAssetType.THERAPEUTIC in self.pure_exclusion_categories:
            raise ValueError("therapeutic cannot be a pure exclusion category")
        return self


class UniverseClassificationInput(ContractModel):
    listing: ListingRecord
    sec_profile: SecSubmissionProfile | None
    business_evidence: BusinessEvidence | None
    as_of: datetime

    @model_validator(mode="after")
    def point_in_time_profile(self) -> Self:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if self.sec_profile is not None and self.sec_profile.source_available_at > self.as_of:
            raise ValueError("SEC profile was unavailable at as_of")
        return self


class UniverseDecision(ContractModel):
    ticker: str
    as_of: datetime
    status: UniverseStatus
    eligible: bool
    investability_floor_status: InvestabilityFloorStatus
    reason_codes: tuple[str, ...]
    rationale: str
    supporting_claim_ids: tuple[str, ...]

    @model_validator(mode="after")
    def consistent_status(self) -> Self:
        if self.eligible != (self.status is UniverseStatus.INCLUDED):
            raise ValueError("eligible must be true only for INCLUDED")
        if not self.reason_codes:
            raise ValueError("every universe decision requires a reason code")
        return self


INELIGIBLE_ASSET_TYPES = {
    LeadEconomicAssetType.DIAGNOSTIC,
    LeadEconomicAssetType.DEVICE,
    LeadEconomicAssetType.CRO,
    LeadEconomicAssetType.HEALTHCARE_SERVICE,
    LeadEconomicAssetType.DISTRIBUTOR,
    LeadEconomicAssetType.RESEARCH_TOOL,
}

SEC_EXCHANGE_MAP = {
    "nasdaq": Exchange.NASDAQ,
    "nasdaq global select market": Exchange.NASDAQ,
    "nasdaq global market": Exchange.NASDAQ,
    "nasdaq capital market": Exchange.NASDAQ,
    "new york stock exchange": Exchange.NYSE,
    "nyse": Exchange.NYSE,
    "nyse american": Exchange.NYSE_AMERICAN,
    "nyse mkt": Exchange.NYSE_AMERICAN,
}


def resolve_sec_mapping(
    listing: ListingRecord,
    mappings: tuple[SecTickerMapping, ...],
) -> SecTickerMapping | None:
    """Resolve ticker identity conservatively, preferring exact exchange agreement."""

    candidates = [mapping for mapping in mappings if mapping.ticker == listing.ticker]
    exact = [
        mapping
        for mapping in candidates
        if normalize_sec_exchange(mapping.exchange) is listing.exchange
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"ambiguous SEC identity for {listing.ticker}")
    return None


def normalize_sec_exchange(value: str) -> Exchange | None:
    return SEC_EXCHANGE_MAP.get(value.strip().casefold())


def classify_universe(candidate: UniverseClassificationInput) -> UniverseDecision:
    """Apply BOE-1.0.0 universe rules without market-price investability data."""

    listing = candidate.listing
    profile = candidate.sec_profile
    evidence = candidate.business_evidence
    base = {
        "ticker": listing.ticker,
        "as_of": candidate.as_of,
        "investability_floor_status": InvestabilityFloorStatus.NOT_EVALUATED,
    }

    if listing.exchange is None:
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=("UNSUPPORTED_EXCHANGE",),
            rationale="Security is not listed on Nasdaq, NYSE, or NYSE American.",
            supporting_claim_ids=(),
        )
    if listing.test_issue or listing.etf or listing.next_shares:
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=("INELIGIBLE_LISTING_FLAG",),
            rationale="Test issues, ETFs, and NextShares are outside the BOE universe.",
            supporting_claim_ids=(),
        )
    if listing.security_kind is SecurityKind.EXCLUDED_INSTRUMENT:
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=("INELIGIBLE_SECURITY_TYPE",),
            rationale="Security is not operating-company common equity or an ADR.",
            supporting_claim_ids=(),
        )
    if listing.security_kind is SecurityKind.UNKNOWN:
        return _review(base, "UNKNOWN_SECURITY_TYPE", "Security type requires review.")
    if profile is None:
        return _review(base, "MISSING_SEC_IDENTITY", "No SEC issuer profile is available.")
    if listing.ticker not in profile.tickers:
        return _review(
            base,
            "TICKER_CIK_MISMATCH",
            "Listing ticker does not appear in the matched SEC profile.",
        )
    ticker_exchanges = {
        normalize_sec_exchange(profile.exchanges[index])
        for index, ticker in enumerate(profile.tickers)
        if ticker == listing.ticker
    }
    if listing.exchange not in ticker_exchanges:
        return _review(
            base,
            "TICKER_EXCHANGE_MISMATCH",
            "Listing exchange does not agree with the matched SEC profile.",
        )
    if profile.reporting_current is False:
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=("REPORTING_NOT_CURRENT",),
            rationale="Issuer does not satisfy the periodic-reporting recency rule.",
            supporting_claim_ids=(),
        )
    if profile.reporting_current is None:
        return _review(
            base,
            "REPORTING_STATUS_UNKNOWN",
            "Periodic-reporting status cannot be established at the cutoff.",
        )
    if evidence is None:
        return _review(
            base,
            "MISSING_BUSINESS_EVIDENCE",
            "Primary economic activity has not been evidenced from filings.",
        )

    claims = evidence.supporting_claim_ids
    if evidence.mature_diversified_pharma or (
        evidence.lead_economic_asset_type is LeadEconomicAssetType.DIVERSIFIED_PHARMA
    ):
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=("MATURE_DIVERSIFIED_PHARMA",),
            rationale=evidence.rationale,
            supporting_claim_ids=claims,
        )

    if evidence.active_therapeutic_assets == 0:
        if evidence.lead_economic_asset_type in INELIGIBLE_ASSET_TYPES:
            reason = f"PURE_{evidence.lead_economic_asset_type.value}"
        else:
            reason = "NO_ACTIVE_THERAPEUTIC_ASSET"
        return UniverseDecision(
            **base,
            status=UniverseStatus.EXCLUDED,
            eligible=False,
            reason_codes=(reason,),
            rationale=evidence.rationale,
            supporting_claim_ids=claims,
        )

    primary_therapeutic = (
        evidence.lead_economic_asset_type is LeadEconomicAssetType.THERAPEUTIC
        or (
            evidence.therapeutic_focus_share_pct is not None
            and evidence.therapeutic_focus_share_pct > 50
        )
    )
    if primary_therapeutic:
        if not claims:
            return _review(
                base,
                "UNSOURCED_THERAPEUTIC_CLASSIFICATION",
                "Therapeutic focus is asserted without a filing-backed claim.",
            )
        return UniverseDecision(
            **base,
            status=UniverseStatus.INCLUDED,
            eligible=True,
            reason_codes=("PRIMARY_THERAPEUTIC_BUSINESS",),
            rationale=evidence.rationale,
            supporting_claim_ids=claims,
        )

    if evidence.lead_economic_asset_type in INELIGIBLE_ASSET_TYPES or (
        evidence.therapeutic_focus_share_pct is not None
        and evidence.therapeutic_focus_share_pct <= 50
    ):
        return UniverseDecision(
            **base,
            status=UniverseStatus.SEPARATE_NON_RANKABLE,
            eligible=False,
            reason_codes=("THERAPEUTICS_NOT_PRIMARY_DRIVER",),
            rationale=evidence.rationale,
            supporting_claim_ids=claims,
        )

    return _review(
        base,
        "AMBIGUOUS_BUSINESS_CLASSIFICATION",
        "Therapeutic activity exists, but the primary economic driver is unresolved.",
        claims,
    )


def _review(
    base: dict[str, object],
    reason: str,
    rationale: str,
    claims: tuple[str, ...] = (),
) -> UniverseDecision:
    return UniverseDecision(
        **base,
        status=UniverseStatus.WATCHLIST_UNIVERSE_REVIEW,
        eligible=False,
        reason_codes=(reason,),
        rationale=rationale,
        supporting_claim_ids=claims,
    )


def utc_now() -> datetime:
    """Injectable clock default for orchestration; domain functions accept explicit as_of."""

    return datetime.now(UTC)
