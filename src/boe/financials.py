"""Milestone 4 financial-survival and capital-structure domain logic.

This module derives auditable financial inputs only. It deliberately does not
score, classify, value, or rank BOE candidates.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from statistics import median
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.models import ContractModel

MONEY = Decimal("0.01")
SHARES = Decimal("0.000001")
MONTH_DAYS = Decimal("30.4375")

CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
MARKETABLE_SECURITIES_CONCEPTS = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "MarketableSecurities",
)
DEBT_AGGREGATE_CONCEPTS = (
    "LongTermDebtAndFinanceLeaseObligationsCurrentAndNoncurrent",
    "LongTermDebtCurrentAndNoncurrent",
)
DEBT_CURRENT_CONCEPTS = (
    "LongTermDebtCurrent",
    "ShortTermBorrowings",
)
DEBT_NONCURRENT_CONCEPTS = (
    "LongTermDebtNoncurrent",
    "LongTermDebt",
)
BASIC_SHARES_CONCEPTS = (
    "EntityCommonStockSharesOutstanding",
    "CommonStocksIncludingAdditionalPaidInCapitalMember",
)
OPERATING_CASH_FLOW_CONCEPTS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)


class FinancialDataError(ValueError):
    """Raised when a critical Milestone 4 value cannot be bounded safely."""


class FinancialFact(ContractModel):
    id: UUID
    issuer_id: str = Field(min_length=1)
    taxonomy: str = Field(min_length=1)
    concept: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(min_length=1)
    period_start: date | None = None
    period_end: date | None = None
    instant: date | None = None
    form: str = Field(min_length=1)
    accession: str = Field(min_length=1)
    filed_at: datetime
    source_available_at: datetime
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    frame: str | None = None
    source_evidence_id: UUID

    @model_validator(mode="after")
    def valid_fact(self) -> Self:
        _require_aware(self.filed_at, "filed_at")
        _require_aware(self.source_available_at, "source_available_at")
        if self.source_available_at < self.filed_at:
            raise ValueError("source_available_at cannot precede filed_at")
        if self.instant is None and self.period_end is None:
            raise ValueError("financial fact requires instant or period_end")
        if self.period_start is not None and self.period_end is None:
            raise ValueError("duration fact with period_start requires period_end")
        if self.period_start is not None and self.period_end is not None:
            if self.period_end < self.period_start:
                raise ValueError("financial fact period_end precedes period_start")
        return self


class SelectedFact(ContractModel):
    role: str = Field(min_length=1)
    fact_id: UUID
    concept: str = Field(min_length=1)
    value: Decimal
    evidence_id: UUID
    statement_date: date
    available_at: datetime


class CalculationTrace(ContractModel):
    formula_version: Literal["BOE-M4-1"] = "BOE-M4-1"
    formula: str = Field(min_length=1)
    inputs: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...]
    result: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("calculation trace evidence_ids must be unique")
        return self


class CashPosition(ContractModel):
    issuer_id: str = Field(min_length=1)
    as_of: datetime
    balance_sheet_date: date
    cash: Decimal = Field(ge=0)
    marketable_securities: Decimal = Field(ge=0)
    debt: Decimal = Field(ge=0)
    liquidity: Decimal = Field(ge=0)
    selected_facts: tuple[SelectedFact, ...]
    zero_debt_confirmation_evidence_id: UUID | None = None
    trace: CalculationTrace

    @model_validator(mode="after")
    def valid_cash_position(self) -> Self:
        _require_aware(self.as_of, "as_of")
        if self.liquidity != self.cash + self.marketable_securities:
            raise ValueError("liquidity must equal cash plus marketable securities")
        if self.balance_sheet_date > self.as_of.date():
            raise ValueError("balance sheet date cannot follow as_of")
        return self


class QuarterlyCashFlow(ContractModel):
    fiscal_year: int
    quarter: int = Field(ge=1, le=4)
    period_end: date
    reported_operating_cash_flow: Decimal
    derived_from_cumulative: bool
    input_fact_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class BurnAdjustment(ContractModel):
    quarter_end: date
    category: Literal["FINANCING", "ACQUISITION", "RESTRUCTURING"]
    cash_flow_effect: Decimal
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    confirmed_at: datetime

    @model_validator(mode="after")
    def confirmed_timestamp(self) -> Self:
        _require_aware(self.confirmed_at, "confirmed_at")
        return self


class BurnQuarter(ContractModel):
    period_end: date
    reported_operating_cash_flow: Decimal
    adjustment_cash_flow_effect: Decimal
    normalized_operating_cash_flow: Decimal
    normalized_burn: Decimal = Field(ge=0)
    input_fact_ids: tuple[UUID, ...] = Field(min_length=1)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class CashBurnSnapshot(ContractModel):
    issuer_id: str = Field(min_length=1)
    as_of: datetime
    quarters: tuple[BurnQuarter, ...] = Field(min_length=1, max_length=4)
    method: Literal["MEDIAN_LATEST_COMPARABLE", "CONSERVATIVE_SHORT_HISTORY"]
    confidence: Literal["LOW", "MODERATE", "HIGH"]
    normalized_quarterly_burn: Decimal = Field(gt=0)
    trace: CalculationTrace

    @model_validator(mode="after")
    def valid_burn_snapshot(self) -> Self:
        _require_aware(self.as_of, "as_of")
        if self.method == "MEDIAN_LATEST_COMPARABLE" and len(self.quarters) < 3:
            raise ValueError("median comparable method requires at least three quarters")
        if self.method == "CONSERVATIVE_SHORT_HISTORY" and len(self.quarters) >= 3:
            raise ValueError("short-history method is reserved for fewer than three quarters")
        return self


class ShareComponent(ContractModel):
    kind: Literal["OPTIONS", "WARRANTS", "RSUS", "CONVERTIBLES", "OTHER_DILUTIVE"]
    shares: Decimal = Field(ge=0)
    as_of: date
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class CapitalStructureSnapshot(ContractModel):
    issuer_id: str = Field(min_length=1)
    as_of: datetime
    basic_shares: Decimal = Field(gt=0)
    dilutive_options: Decimal = Field(ge=0)
    warrants: Decimal = Field(ge=0)
    rsus: Decimal = Field(ge=0)
    convertible_shares: Decimal = Field(ge=0)
    other_dilutive_shares: Decimal = Field(ge=0)
    fully_diluted_shares: Decimal = Field(gt=0)
    expected_financing_shares: Decimal = Field(ge=0)
    projected_fully_diluted_shares: Decimal = Field(gt=0)
    basic_share_fact_id: UUID
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    trace: CalculationTrace

    @model_validator(mode="after")
    def reconcile_shares(self) -> Self:
        _require_aware(self.as_of, "as_of")
        current = (
            self.basic_shares
            + self.dilutive_options
            + self.warrants
            + self.rsus
            + self.convertible_shares
            + self.other_dilutive_shares
        )
        if self.fully_diluted_shares != current:
            raise ValueError("fully diluted shares do not reconcile")
        if self.projected_fully_diluted_shares != current + self.expected_financing_shares:
            raise ValueError("projected fully diluted shares do not reconcile")
        return self


class SurvivalSnapshot(ContractModel):
    issuer_id: str = Field(min_length=1)
    as_of: datetime
    catalyst_latest_date: date
    liquidity: Decimal = Field(ge=0)
    normalized_quarterly_burn: Decimal = Field(gt=0)
    runway_months: Decimal = Field(ge=0)
    months_to_latest_catalyst: Decimal = Field(ge=0)
    runway_at_catalyst_months: Decimal = Field(ge=0)
    cash_position_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    burn_evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    trace: CalculationTrace

    @model_validator(mode="after")
    def aware_as_of(self) -> Self:
        _require_aware(self.as_of, "as_of")
        if self.catalyst_latest_date < self.as_of.date():
            raise ValueError("latest catalyst date cannot precede as_of")
        return self


class FinancingFiling(ContractModel):
    issuer_id: str = Field(min_length=1)
    cik: str = Field(pattern=r"^[0-9]{10}$")
    accession: str = Field(min_length=1)
    form: str = Field(min_length=1)
    filing_date: date
    accepted_at: datetime
    primary_document: str = Field(min_length=1)
    filing_url: str = Field(pattern=r"^https://www\.sec\.gov/Archives/edgar/data/")
    category: Literal["SHELF", "PROSPECTUS_SUPPLEMENT", "OTHER_FINANCING_FILING"]

    @model_validator(mode="after")
    def aware_accepted_at(self) -> Self:
        _require_aware(self.accepted_at, "accepted_at")
        return self


class FinancingDisclosureObservation(ContractModel):
    issuer_id: str = Field(min_length=1)
    accession: str = Field(min_length=1)
    kind: Literal["ATM", "SHELF", "OFFERING"]
    statement: str = Field(min_length=1)
    capacity_usd: Decimal | None = Field(default=None, ge=0)
    used_usd: Decimal | None = Field(default=None, ge=0)
    evidence_id: UUID
    known_at: datetime

    @model_validator(mode="after")
    def aware_known_at(self) -> Self:
        _require_aware(self.known_at, "known_at")
        if self.capacity_usd is not None and self.used_usd is not None:
            if self.used_usd > self.capacity_usd:
                raise ValueError("used financing capacity cannot exceed total capacity")
        return self


class FinancingFacility(ContractModel):
    issuer_id: str = Field(min_length=1)
    kind: Literal["ATM", "SHELF", "FOLLOW_ON", "OTHER"]
    active: bool
    opened_at: date
    capacity_usd: Decimal | None = Field(default=None, ge=0)
    used_usd: Decimal | None = Field(default=None, ge=0)
    remaining_usd: Decimal | None = Field(default=None, ge=0)
    observed_issuance_dependence: bool = False
    management_guided_use_before_catalyst: bool = False
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    confirmed_at: datetime

    @model_validator(mode="after")
    def valid_facility(self) -> Self:
        _require_aware(self.confirmed_at, "confirmed_at")
        if self.capacity_usd is not None and self.used_usd is not None:
            if self.used_usd > self.capacity_usd:
                raise ValueError("facility usage exceeds capacity")
        if self.capacity_usd is not None and self.remaining_usd is not None:
            if self.remaining_usd > self.capacity_usd:
                raise ValueError("remaining facility capacity exceeds total capacity")
        return self


class FinancingRiskInputs(ContractModel):
    issuer_id: str = Field(min_length=1)
    as_of: datetime
    runway_months: Decimal = Field(ge=0)
    runway_at_catalyst_months: Decimal = Field(ge=0)
    runway_below_12_months: bool
    cash_exhaustion_within_six_months_after_catalyst: bool
    mathematically_necessary_financing_before_catalyst: bool
    management_guided_financing_before_catalyst: bool
    active_atm: bool
    recent_shelf: bool
    observed_issuance_dependence: bool
    runway_below_18_months: bool
    expected_financing_shares: Decimal = Field(ge=0)
    current_fully_diluted_shares: Decimal = Field(gt=0)
    modeled_pre_catalyst_dilution_pct: Decimal = Field(ge=0)
    evidence_ids: tuple[UUID, ...]
    trace: CalculationTrace

    @model_validator(mode="after")
    def aware_as_of(self) -> Self:
        _require_aware(self.as_of, "as_of")
        return self


class ReconciliationItem(ContractModel):
    field_name: str = Field(min_length=1)
    observed: Decimal
    expected: Decimal
    absolute_tolerance: Decimal = Field(ge=0)
    relative_tolerance_pct: Decimal = Field(ge=0)


class ReconciliationResult(ContractModel):
    field_name: str = Field(min_length=1)
    observed: Decimal
    expected: Decimal
    absolute_error: Decimal = Field(ge=0)
    relative_error_pct: Decimal = Field(ge=0)
    passed: bool


class ReconciliationAudit(ContractModel):
    total: int = Field(ge=1)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    results: tuple[ReconciliationResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reconcile_counts(self) -> Self:
        if self.passed + self.failed != self.total or len(self.results) != self.total:
            raise ValueError("reconciliation audit counts do not reconcile")
        return self


def financial_facts_as_of(
    facts: tuple[FinancialFact, ...],
    cutoff: datetime,
) -> tuple[FinancialFact, ...]:
    _require_aware(cutoff, "cutoff")
    return tuple(
        fact
        for fact in facts
        if fact.source_available_at <= cutoff
        and (fact.instant is None or fact.instant <= cutoff.date())
        and (fact.period_end is None or fact.period_end <= cutoff.date())
    )


def build_cash_position(
    *,
    issuer_id: str,
    facts: tuple[FinancialFact, ...],
    as_of: datetime,
    confirmed_zero_debt_evidence_id: UUID | None = None,
) -> CashPosition:
    eligible = financial_facts_as_of(facts, as_of)
    cash_fact = _latest_instant_fact(eligible, CASH_CONCEPTS, "USD")
    if cash_fact is None:
        raise FinancialDataError("unrestricted cash fact is missing")
    securities_fact = _latest_instant_fact(eligible, MARKETABLE_SECURITIES_CONCEPTS, "USD")
    marketable = securities_fact.value if securities_fact is not None else Decimal("0")

    aggregate_debt = _latest_instant_fact(eligible, DEBT_AGGREGATE_CONCEPTS, "USD")
    debt_facts: list[FinancialFact] = []
    if aggregate_debt is not None:
        debt = aggregate_debt.value
        debt_facts.append(aggregate_debt)
    else:
        current = _latest_instant_fact(eligible, DEBT_CURRENT_CONCEPTS, "USD")
        noncurrent = _latest_instant_fact(eligible, DEBT_NONCURRENT_CONCEPTS, "USD")
        debt_facts = [item for item in (current, noncurrent) if item is not None]
        if not debt_facts and confirmed_zero_debt_evidence_id is None:
            raise FinancialDataError("debt cannot be bounded from filings")
        debt = sum((item.value for item in debt_facts), Decimal("0"))

    selected_facts = [
        _selected("cash", cash_fact),
    ]
    if securities_fact is not None:
        selected_facts.append(_selected("marketable_securities", securities_fact))
    selected_facts.extend(_selected("debt", item) for item in debt_facts)
    evidence_ids = [item.evidence_id for item in selected_facts]
    if confirmed_zero_debt_evidence_id is not None:
        evidence_ids.append(confirmed_zero_debt_evidence_id)
    balance_dates = [item.statement_date for item in selected_facts]
    balance_sheet_date = max(balance_dates)
    liquidity = cash_fact.value + marketable
    trace = CalculationTrace(
        formula=(
            "liquidity = unrestricted_cash + current_marketable_securities; "
            "debt uses aggregate debt when available, otherwise current + noncurrent debt"
        ),
        inputs=tuple(
            [f"cash={cash_fact.value}", f"marketable_securities={marketable}", f"debt={debt}"]
        ),
        evidence_ids=_unique_uuid(evidence_ids),
        result=f"liquidity={liquidity};debt={debt}",
    )
    return CashPosition(
        issuer_id=issuer_id,
        as_of=as_of,
        balance_sheet_date=balance_sheet_date,
        cash=cash_fact.value,
        marketable_securities=marketable,
        debt=debt,
        liquidity=liquidity,
        selected_facts=tuple(selected_facts),
        zero_debt_confirmation_evidence_id=confirmed_zero_debt_evidence_id,
        trace=trace,
    )


def derive_quarterly_operating_cash_flow(
    facts: tuple[FinancialFact, ...],
    as_of: datetime,
) -> tuple[QuarterlyCashFlow, ...]:
    eligible = [
        fact
        for fact in financial_facts_as_of(facts, as_of)
        if fact.concept in OPERATING_CASH_FLOW_CONCEPTS
        and fact.unit == "USD"
        and fact.period_start is not None
        and fact.period_end is not None
        and fact.fiscal_year is not None
        and fact.fiscal_period in {"Q1", "Q2", "Q3", "FY"}
    ]
    latest: dict[tuple[int, str], FinancialFact] = {}
    for fact in eligible:
        assert fact.fiscal_year is not None
        assert fact.fiscal_period is not None
        key = (fact.fiscal_year, fact.fiscal_period)
        previous = latest.get(key)
        if previous is None or (fact.source_available_at, fact.accession) > (
            previous.source_available_at,
            previous.accession,
        ):
            latest[key] = fact

    derived: list[QuarterlyCashFlow] = []
    for fiscal_year in sorted({key[0] for key in latest}):
        q1 = latest.get((fiscal_year, "Q1"))
        q2 = latest.get((fiscal_year, "Q2"))
        q3 = latest.get((fiscal_year, "Q3"))
        fy = latest.get((fiscal_year, "FY"))
        if q1 is not None:
            derived.append(_quarter_from_facts(fiscal_year, 1, q1.value, (q1,), False))
        if q1 is not None and q2 is not None:
            derived.append(_quarter_from_facts(fiscal_year, 2, q2.value - q1.value, (q1, q2), True))
        if q2 is not None and q3 is not None:
            derived.append(_quarter_from_facts(fiscal_year, 3, q3.value - q2.value, (q2, q3), True))
        if q3 is not None and fy is not None:
            derived.append(_quarter_from_facts(fiscal_year, 4, fy.value - q3.value, (q3, fy), True))
    return tuple(sorted(derived, key=lambda item: item.period_end))


def normalize_cash_burn(
    *,
    issuer_id: str,
    quarterly_cash_flow: tuple[QuarterlyCashFlow, ...],
    as_of: datetime,
    adjustments: tuple[BurnAdjustment, ...] = (),
) -> CashBurnSnapshot:
    _require_aware(as_of, "as_of")
    adjustment_by_end: dict[date, list[BurnAdjustment]] = {}
    for adjustment in adjustments:
        if adjustment.confirmed_at > as_of:
            raise FinancialDataError("burn adjustment was not confirmed by as_of")
        adjustment_by_end.setdefault(adjustment.quarter_end, []).append(adjustment)

    normalized: list[BurnQuarter] = []
    for quarter in quarterly_cash_flow:
        if quarter.period_end > as_of.date():
            continue
        quarter_adjustments = adjustment_by_end.get(quarter.period_end, [])
        adjustment_effect = sum(
            (item.cash_flow_effect for item in quarter_adjustments), Decimal("0")
        )
        normalized_ocf = quarter.reported_operating_cash_flow - adjustment_effect
        burn = max(-normalized_ocf, Decimal("0"))
        if burn <= 0:
            continue
        evidence = list(quarter.evidence_ids)
        for item in quarter_adjustments:
            evidence.extend(item.evidence_ids)
        normalized.append(
            BurnQuarter(
                period_end=quarter.period_end,
                reported_operating_cash_flow=quarter.reported_operating_cash_flow,
                adjustment_cash_flow_effect=adjustment_effect,
                normalized_operating_cash_flow=normalized_ocf,
                normalized_burn=burn,
                input_fact_ids=quarter.input_fact_ids,
                evidence_ids=_unique_uuid(evidence),
            )
        )

    latest = normalized[-4:]
    if not latest:
        raise FinancialDataError("no comparable negative operating-cash-flow quarter is available")
    burns = [item.normalized_burn for item in latest]
    median_burn = Decimal(str(median(burns)))
    if len(latest) >= 3:
        method: Literal["MEDIAN_LATEST_COMPARABLE", "CONSERVATIVE_SHORT_HISTORY"] = (
            "MEDIAN_LATEST_COMPARABLE"
        )
        normalized_burn = median_burn
        confidence: Literal["LOW", "MODERATE", "HIGH"] = "HIGH" if len(latest) == 4 else "MODERATE"
    else:
        method = "CONSERVATIVE_SHORT_HISTORY"
        normalized_burn = max(latest[-1].normalized_burn, median_burn)
        confidence = "LOW"

    evidence_ids = _unique_uuid(evidence_id for item in latest for evidence_id in item.evidence_ids)
    trace = CalculationTrace(
        formula=(
            "normalized quarterly burn = median(latest four comparable negative operating "
            "cash-flow quarters); with <3 quarters use max(latest burn, available-quarter median)"
        ),
        inputs=tuple(f"{item.period_end.isoformat()}={item.normalized_burn}" for item in latest),
        evidence_ids=evidence_ids,
        result=f"normalized_quarterly_burn={normalized_burn};method={method};confidence={confidence}",
    )
    return CashBurnSnapshot(
        issuer_id=issuer_id,
        as_of=as_of,
        quarters=tuple(latest),
        method=method,
        confidence=confidence,
        normalized_quarterly_burn=normalized_burn,
        trace=trace,
    )


def latest_basic_shares_outstanding(
    facts: tuple[FinancialFact, ...],
    as_of: datetime,
) -> Decimal | None:
    """Same source and as-of discipline as build_capital_structure_snapshot's
    ``basic`` fact, but non-raising: callers that only need a market-cap
    estimate (not a full dilution snapshot) should degrade to "unknown"
    when a company hasn't reported EntityCommonStockSharesOutstanding by
    ``as_of``, not lose an entire unrelated factor over it."""
    eligible = financial_facts_as_of(facts, as_of)
    basic = _latest_instant_fact(eligible, BASIC_SHARES_CONCEPTS, "shares")
    if basic is None or basic.value <= 0:
        return None
    return basic.value


def build_capital_structure_snapshot(
    *,
    issuer_id: str,
    facts: tuple[FinancialFact, ...],
    as_of: datetime,
    share_components: tuple[ShareComponent, ...] = (),
    expected_financing_shares: Decimal = Decimal("0"),
    expected_financing_evidence_ids: tuple[UUID, ...] = (),
) -> CapitalStructureSnapshot:
    eligible = financial_facts_as_of(facts, as_of)
    basic = _latest_instant_fact(eligible, BASIC_SHARES_CONCEPTS, "shares")
    if basic is None or basic.value <= 0:
        raise FinancialDataError("basic shares outstanding cannot be bounded")
    eligible_components = [
        component for component in share_components if component.as_of <= as_of.date()
    ]
    by_kind: dict[str, Decimal] = {
        "OPTIONS": Decimal("0"),
        "WARRANTS": Decimal("0"),
        "RSUS": Decimal("0"),
        "CONVERTIBLES": Decimal("0"),
        "OTHER_DILUTIVE": Decimal("0"),
    }
    evidence_ids: list[UUID] = [basic.source_evidence_id]
    for component in eligible_components:
        by_kind[component.kind] += component.shares
        evidence_ids.extend(component.evidence_ids)
    evidence_ids.extend(expected_financing_evidence_ids)
    fully_diluted = basic.value + sum(by_kind.values(), Decimal("0"))
    projected = fully_diluted + expected_financing_shares
    trace = CalculationTrace(
        formula=(
            "current fully diluted shares = basic + options + warrants + RSUs + convertible "
            "shares + other dilutive shares; projected fully diluted shares additionally "
            "include expected financing shares"
        ),
        inputs=(
            f"basic={basic.value}",
            f"options={by_kind['OPTIONS']}",
            f"warrants={by_kind['WARRANTS']}",
            f"rsus={by_kind['RSUS']}",
            f"convertibles={by_kind['CONVERTIBLES']}",
            f"other={by_kind['OTHER_DILUTIVE']}",
            f"expected_financing={expected_financing_shares}",
        ),
        evidence_ids=_unique_uuid(evidence_ids),
        result=f"fully_diluted_shares={fully_diluted};projected={projected}",
    )
    return CapitalStructureSnapshot(
        issuer_id=issuer_id,
        as_of=as_of,
        basic_shares=basic.value,
        dilutive_options=by_kind["OPTIONS"],
        warrants=by_kind["WARRANTS"],
        rsus=by_kind["RSUS"],
        convertible_shares=by_kind["CONVERTIBLES"],
        other_dilutive_shares=by_kind["OTHER_DILUTIVE"],
        fully_diluted_shares=fully_diluted,
        expected_financing_shares=expected_financing_shares,
        projected_fully_diluted_shares=projected,
        basic_share_fact_id=basic.id,
        evidence_ids=_unique_uuid(evidence_ids),
        trace=trace,
    )


def calculate_survival(
    *,
    cash_position: CashPosition,
    burn: CashBurnSnapshot,
    catalyst_latest_date: date,
    as_of: datetime,
) -> SurvivalSnapshot:
    _require_aware(as_of, "as_of")
    if cash_position.issuer_id != burn.issuer_id:
        raise ValueError("cash position and burn snapshot refer to different issuers")
    if cash_position.as_of > as_of or burn.as_of > as_of:
        raise FinancialDataError("survival inputs were unavailable at as_of")
    if catalyst_latest_date < as_of.date():
        raise FinancialDataError("latest plausible catalyst date is already past")
    runway = cash_position.liquidity / burn.normalized_quarterly_burn * Decimal("3")
    days_to_catalyst = Decimal((catalyst_latest_date - as_of.date()).days)
    months_to_catalyst = days_to_catalyst / MONTH_DAYS
    runway_at_catalyst = max(runway - months_to_catalyst, Decimal("0"))
    cash_evidence = _unique_uuid(item.evidence_id for item in cash_position.selected_facts)
    burn_evidence = _unique_uuid(
        evidence_id for quarter in burn.quarters for evidence_id in quarter.evidence_ids
    )
    trace = CalculationTrace(
        formula=(
            "runway_months = (cash + current marketable securities) / normalized_quarterly_burn "
            "* 3; runway_at_catalyst = max(runway_months - "
            "calendar_days_to_latest_catalyst/30.4375, 0)"
        ),
        inputs=(
            f"liquidity={cash_position.liquidity}",
            f"quarterly_burn={burn.normalized_quarterly_burn}",
            f"days_to_latest_catalyst={days_to_catalyst}",
        ),
        evidence_ids=_unique_uuid((*cash_evidence, *burn_evidence)),
        result=f"runway_months={runway};runway_at_catalyst_months={runway_at_catalyst}",
    )
    return SurvivalSnapshot(
        issuer_id=cash_position.issuer_id,
        as_of=as_of,
        catalyst_latest_date=catalyst_latest_date,
        liquidity=cash_position.liquidity,
        normalized_quarterly_burn=burn.normalized_quarterly_burn,
        runway_months=runway,
        months_to_latest_catalyst=months_to_catalyst,
        runway_at_catalyst_months=runway_at_catalyst,
        cash_position_evidence_ids=cash_evidence,
        burn_evidence_ids=burn_evidence,
        trace=trace,
    )


def build_financing_risk_inputs(
    *,
    survival: SurvivalSnapshot,
    capital_structure: CapitalStructureSnapshot,
    facilities: tuple[FinancingFacility, ...],
    as_of: datetime,
    recent_shelf_days: int = 365,
) -> FinancingRiskInputs:
    _require_aware(as_of, "as_of")
    if survival.issuer_id != capital_structure.issuer_id:
        raise ValueError("survival and capital structure refer to different issuers")
    if survival.as_of > as_of or capital_structure.as_of > as_of:
        raise FinancialDataError("financing-risk inputs contain post-cutoff snapshots")
    known_facilities = [facility for facility in facilities if facility.confirmed_at <= as_of]
    active_atm = any(item.kind == "ATM" and item.active for item in known_facilities)
    recent_shelf = any(
        item.kind == "SHELF"
        and (as_of.date() - item.opened_at).days <= recent_shelf_days
        and item.opened_at <= as_of.date()
        for item in known_facilities
    )
    observed_dependence = any(item.observed_issuance_dependence for item in known_facilities)
    management_guided = any(item.management_guided_use_before_catalyst for item in known_facilities)
    mathematically_necessary = survival.runway_at_catalyst_months <= 0
    dilution_pct = (
        capital_structure.expected_financing_shares
        / capital_structure.fully_diluted_shares
        * Decimal("100")
    )
    evidence_ids = _unique_uuid(
        evidence_id for facility in known_facilities for evidence_id in facility.evidence_ids
    )
    trace = CalculationTrace(
        formula=(
            "Milestone 4 exposes atomic financing-risk inputs only; modeled dilution percent = "
            "expected financing shares / current fully diluted shares * 100"
        ),
        inputs=(
            f"runway_months={survival.runway_months}",
            f"runway_at_catalyst_months={survival.runway_at_catalyst_months}",
            f"active_atm={active_atm}",
            f"recent_shelf={recent_shelf}",
            f"issuance_dependence={observed_dependence}",
            f"expected_financing_shares={capital_structure.expected_financing_shares}",
            f"current_fully_diluted_shares={capital_structure.fully_diluted_shares}",
        ),
        evidence_ids=evidence_ids,
        result=f"modeled_pre_catalyst_dilution_pct={dilution_pct}",
    )
    return FinancingRiskInputs(
        issuer_id=survival.issuer_id,
        as_of=as_of,
        runway_months=survival.runway_months,
        runway_at_catalyst_months=survival.runway_at_catalyst_months,
        runway_below_12_months=survival.runway_months < Decimal("12"),
        cash_exhaustion_within_six_months_after_catalyst=(
            survival.runway_at_catalyst_months < Decimal("6")
        ),
        mathematically_necessary_financing_before_catalyst=mathematically_necessary,
        management_guided_financing_before_catalyst=management_guided,
        active_atm=active_atm,
        recent_shelf=recent_shelf,
        observed_issuance_dependence=observed_dependence,
        runway_below_18_months=survival.runway_months < Decimal("18"),
        expected_financing_shares=capital_structure.expected_financing_shares,
        current_fully_diluted_shares=capital_structure.fully_diluted_shares,
        modeled_pre_catalyst_dilution_pct=dilution_pct,
        evidence_ids=evidence_ids,
        trace=trace,
    )


def audit_reconciliation(items: tuple[ReconciliationItem, ...]) -> ReconciliationAudit:
    if not items:
        raise ValueError("reconciliation audit requires at least one item")
    results: list[ReconciliationResult] = []
    for item in items:
        absolute_error = abs(item.observed - item.expected)
        if item.expected == 0:
            relative_error_pct = Decimal("0") if absolute_error == 0 else Decimal("100")
        else:
            relative_error_pct = absolute_error / abs(item.expected) * Decimal("100")
        passed = absolute_error <= item.absolute_tolerance or (
            relative_error_pct <= item.relative_tolerance_pct
        )
        results.append(
            ReconciliationResult(
                field_name=item.field_name,
                observed=item.observed,
                expected=item.expected,
                absolute_error=absolute_error,
                relative_error_pct=relative_error_pct,
                passed=passed,
            )
        )
    passed_count = sum(result.passed for result in results)
    return ReconciliationAudit(
        total=len(results),
        passed=passed_count,
        failed=len(results) - passed_count,
        results=tuple(results),
    )


def _latest_instant_fact(
    facts: tuple[FinancialFact, ...] | list[FinancialFact],
    concepts: tuple[str, ...],
    unit: str,
) -> FinancialFact | None:
    priority = {concept: position for position, concept in enumerate(concepts)}
    matching = [
        fact
        for fact in facts
        if fact.concept in priority and fact.unit == unit and fact.instant is not None
    ]
    if not matching:
        return None
    latest_date = max(fact.instant for fact in matching if fact.instant is not None)
    latest = [fact for fact in matching if fact.instant == latest_date]
    return min(
        latest,
        key=lambda fact: (
            priority[fact.concept],
            -int(fact.source_available_at.timestamp()),
            fact.accession,
        ),
    )


def _selected(role: str, fact: FinancialFact) -> SelectedFact:
    statement_date = fact.instant or fact.period_end
    assert statement_date is not None
    return SelectedFact(
        role=role,
        fact_id=fact.id,
        concept=fact.concept,
        value=fact.value,
        evidence_id=fact.source_evidence_id,
        statement_date=statement_date,
        available_at=fact.source_available_at,
    )


def _quarter_from_facts(
    fiscal_year: int,
    quarter: int,
    value: Decimal,
    facts: tuple[FinancialFact, ...],
    derived: bool,
) -> QuarterlyCashFlow:
    period_end = max(fact.period_end for fact in facts if fact.period_end is not None)
    return QuarterlyCashFlow(
        fiscal_year=fiscal_year,
        quarter=quarter,
        period_end=period_end,
        reported_operating_cash_flow=value,
        derived_from_cumulative=derived,
        input_fact_ids=tuple(fact.id for fact in facts),
        evidence_ids=_unique_uuid(fact.source_evidence_id for fact in facts),
    )


def _unique_uuid(values: Iterable[UUID]) -> tuple[UUID, ...]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
