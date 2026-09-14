"""Pydantic models implementing the BOE-1.0.0 data contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from boe.enums import (
    CatalystType,
    Classification,
    DataState,
    DilutionRisk,
    EvidenceTier,
    Exchange,
    FactorCode,
    PosConfidence,
    SecurityType,
    TimingConfidence,
)


class ContractModel(BaseModel):
    """Strict immutable base for external BOE contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Money(ContractModel):
    value: Decimal
    currency: Literal["USD"] = "USD"

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("money must be finite")
        return value


class OrderedRange(ContractModel):
    low: float
    mid: float
    high: float

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.low <= self.mid <= self.high:
            raise ValueError("range must satisfy low <= mid <= high")
        return self


class SourceReference(ContractModel):
    id: str = Field(min_length=1)
    url: HttpUrl
    available_at: datetime
    retrieved_at: datetime
    tier: EvidenceTier
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_timestamps(self) -> Self:
        if self.retrieved_at < self.available_at:
            raise ValueError("source cannot be retrieved before it is available")
        return self


class AnalysisMeta(ContractModel):
    analysis_run_id: UUID
    generated_at: datetime
    as_of: datetime
    evidence_cutoff: datetime
    rules_version: Literal["BOE-1.0.0"]
    rules_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    code_commit_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    data_coverage_pct: float = Field(ge=0, le=100)


class CandidateIdentity(ContractModel):
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,9}$")
    company: str = Field(min_length=1)
    cik: str = Field(pattern=r"^[0-9]{10}$")
    exchange: Exchange
    security_type: SecurityType
    universe_eligible: bool
    market_cap: Money | None = None
    enterprise_value: Money | None = None

    @model_validator(mode="after")
    def nonnegative_market_cap(self) -> Self:
        if self.market_cap is not None and self.market_cap.value < 0:
            raise ValueError("market capitalization cannot be negative")
        return self


class Catalyst(ContractModel):
    type: CatalystType
    lead_asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    clinical_phase: str = Field(min_length=1)
    title: str = Field(min_length=1)
    window_start: date
    window_end: date
    timing_confidence: TimingConfidence
    primary_source_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.window_end < self.window_start:
            raise ValueError("catalyst window_end precedes window_start")
        return self


class FactorSubscore(ContractModel):
    code: str = Field(min_length=1)
    points: int = Field(ge=0)
    max_points: int = Field(gt=0)
    data_state: DataState
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def points_within_maximum(self) -> Self:
        if self.points > self.max_points:
            raise ValueError("subfactor points exceed maximum")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("subfactor evidence_ids must be unique")
        if self.data_state is DataState.MISSING and self.points != 0:
            raise ValueError("missing subfactor must score zero")
        return self


class FactorScore(ContractModel):
    code: FactorCode
    points: int = Field(ge=0)
    max_points: int = Field(gt=0)
    subfactors: tuple[FactorSubscore, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reconcile_subfactors(self) -> Self:
        if self.points > self.max_points:
            raise ValueError("factor points exceed maximum")
        if sum(item.points for item in self.subfactors) != self.points:
            raise ValueError("factor points do not equal subfactor points")
        if sum(item.max_points for item in self.subfactors) != self.max_points:
            raise ValueError("factor maximum does not equal subfactor maxima")
        codes = [item.code for item in self.subfactors]
        if len(set(codes)) != len(codes):
            raise ValueError("subfactor codes must be unique within a factor")
        return self


class ScoreBreakdown(ContractModel):
    raw_total: int = Field(ge=0, le=100)
    factors: tuple[FactorScore, ...] = Field(min_length=8, max_length=8)

    @model_validator(mode="after")
    def reconcile_factors(self) -> Self:
        if sum(item.points for item in self.factors) != self.raw_total:
            raise ValueError("raw_total does not equal factor points")
        codes = [item.code for item in self.factors]
        if len(set(codes)) != len(codes):
            raise ValueError("factor codes must be unique")
        if set(codes) != set(FactorCode):
            raise ValueError("all eight BOE factors are required")
        return self


class TriggeredGate(ContractModel):
    code: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    precedence: int = Field(ge=1)


class PriceZone(ContractModel):
    low: Money
    high: Money

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.high.value < self.low.value:
            raise ValueError("entry-zone high precedes low")
        return self


class Decision(ContractModel):
    classification: Classification
    final_decision: str = Field(min_length=1)
    triggered_gates: tuple[TriggeredGate, ...]
    preferred_entry_zone: PriceZone | None
    do_not_chase_price: Money | None
    bull_target: Money | None
    base_target: Money | None
    failure_value: Money | None

    @model_validator(mode="after")
    def valid_prices_and_gate_order(self) -> Self:
        prices = (
            self.do_not_chase_price,
            self.bull_target,
            self.base_target,
            self.failure_value,
        )
        if any(price is not None and price.value < 0 for price in prices):
            raise ValueError("decision prices cannot be negative")
        precedence = [gate.precedence for gate in self.triggered_gates]
        if precedence != sorted(set(precedence)):
            raise ValueError("triggered gates must have unique ascending precedence")
        return self


class ProbabilityAdjustment(ContractModel):
    code: str = Field(min_length=1)
    percentage_points: float
    rationale: str = Field(min_length=1)


class ProbabilityAssessment(ContractModel):
    event_success_pct: OrderedRange
    confidence: PosConfidence
    prior_pct: float = Field(ge=0, le=100)
    adjustments: tuple[ProbabilityAdjustment, ...]

    @model_validator(mode="after")
    def percentage_range(self) -> Self:
        if self.event_success_pct.low < 0 or self.event_success_pct.high > 100:
            raise ValueError("event success range must be within 0..100")
        return self


class Financials(ContractModel):
    cash: Money
    short_term_investments: Money
    debt: Money
    normalized_quarterly_burn: Money
    runway_months: float
    runway_at_catalyst_months: float
    dilution_risk: DilutionRisk
    fully_diluted_shares: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def nonnegative_financials(self) -> Self:
        amounts = (
            self.cash,
            self.short_term_investments,
            self.debt,
            self.normalized_quarterly_burn,
        )
        if any(amount.value < 0 for amount in amounts):
            raise ValueError("cash, securities, debt, and burn cannot be negative")
        if self.runway_months < 0 or self.runway_at_catalyst_months < 0:
            raise ValueError("runway cannot be negative")
        return self


class Valuation(ContractModel):
    conservative_rnpv: Money
    base_rnpv: Money
    bull_rnpv: Money
    margin_of_safety_pct: OrderedRange
    success_return_pct: OrderedRange
    failure_return_pct: OrderedRange
    base_expected_return_pct: float
    conservative_expected_return_pct: float
    reward_risk: float = Field(ge=0, le=10)

    @model_validator(mode="after")
    def ordered_rnpv(self) -> Self:
        values = (
            self.conservative_rnpv.value,
            self.base_rnpv.value,
            self.bull_rnpv.value,
        )
        if not values[0] <= values[1] <= values[2]:
            raise ValueError("rNPV scenarios must be conservative <= base <= bull")
        return self


class Technicals(ContractModel):
    price: Money
    support: Money | None
    resistance: Money | None
    sma20: Money
    sma50: Money
    rsi14: float = Field(ge=0, le=100)
    atr14: Money
    xbi_relative_return_20d_pct: float
    setup_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def positive_price_inputs(self) -> Self:
        required = (self.price, self.sma20, self.sma50, self.atr14)
        optional = (self.support, self.resistance)
        if any(item.value <= 0 for item in required):
            raise ValueError("technical price inputs must be positive")
        if any(item is not None and item.value <= 0 for item in optional):
            raise ValueError("optional technical levels must be positive")
        return self


class RiskRegister(ContractModel):
    scientific: tuple[str, ...]
    financial: tuple[str, ...]
    regulatory: tuple[str, ...]
    technical: tuple[str, ...]


class Thesis(ContractModel):
    summary: str = Field(min_length=1)
    must_happen: tuple[str, ...]
    breakers: tuple[str, ...]
    next_refresh: datetime


class Provenance(ContractModel):
    sources: tuple[SourceReference, ...]
    conflicts: tuple[str, ...]
    input_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CandidateOutput(ContractModel):
    meta: AnalysisMeta
    identity: CandidateIdentity
    catalyst: Catalyst
    score: ScoreBreakdown
    decision: Decision
    probability: ProbabilityAssessment
    financials: Financials
    valuation: Valuation
    technicals: Technicals
    risks: RiskRegister
    thesis: Thesis
    provenance: Provenance

    @model_validator(mode="after")
    def point_in_time_integrity(self) -> Self:
        if self.meta.evidence_cutoff > self.meta.as_of:
            raise ValueError("evidence_cutoff cannot be after as_of")
        if self.meta.generated_at < self.meta.as_of:
            raise ValueError("generated_at cannot be before as_of")
        source_ids = [source.id for source in self.provenance.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source ids must be unique")
        for source in self.provenance.sources:
            if source.available_at > self.meta.evidence_cutoff:
                raise ValueError("source available after evidence cutoff")
        if self.catalyst.primary_source_id not in set(source_ids):
            raise ValueError("catalyst primary source is absent from provenance")
        referenced_evidence = {
            evidence_id
            for factor in self.score.factors
            for subfactor in factor.subfactors
            for evidence_id in subfactor.evidence_ids
        }
        unknown_evidence = referenced_evidence - set(source_ids)
        if unknown_evidence:
            raise ValueError(f"scored evidence absent from provenance: {sorted(unknown_evidence)}")
        if self.thesis.next_refresh <= self.meta.as_of:
            raise ValueError("next_refresh must be after as_of")
        return self


class SubfactorDefinition(BaseModel):
    """Variable rule payload with invariant identity and maximum."""

    model_config = ConfigDict(extra="allow", frozen=True)

    code: str = Field(min_length=1)
    max_points: int = Field(gt=0)


class FactorDefinition(ContractModel):
    code: FactorCode
    name: str = Field(min_length=1)
    max_points: int = Field(gt=0)
    subfactors: tuple[SubfactorDefinition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_maximum(self) -> Self:
        if sum(item.max_points for item in self.subfactors) != self.max_points:
            raise ValueError("factor definition maximum does not equal subfactor maxima")
        codes = [item.code for item in self.subfactors]
        if len(set(codes)) != len(codes):
            raise ValueError("subfactor definition codes must be unique")
        return self


class ScorecardContract(ContractModel):
    format_version: Literal["1.0"]
    contract: Literal["BOE scorecard"]
    version: Literal["BOE-1.0.0"]
    currency: Literal["USD"]
    score_max: Literal[100]
    time_windows_days: dict[str, int]
    investability_floor: dict[str, float]
    catalyst_types: tuple[CatalystType, ...]
    missing_data: dict[str, Any]
    factors: tuple[FactorDefinition, ...]
    pos: dict[str, Any]
    gates: dict[str, Any]
    classifications: dict[str, Any]

    @model_validator(mode="after")
    def internal_consistency(self) -> Self:
        if sum(item.max_points for item in self.factors) != self.score_max:
            raise ValueError("scorecard factor maxima do not total 100")
        factor_codes = [item.code for item in self.factors]
        if len(set(factor_codes)) != len(factor_codes) or set(factor_codes) != set(FactorCode):
            raise ValueError("scorecard must define each BOE factor exactly once")
        if len(set(self.catalyst_types)) != len(self.catalyst_types):
            raise ValueError("catalyst types must be unique")
        if set(self.catalyst_types) != set(CatalystType):
            raise ValueError("scorecard catalyst taxonomy differs from executable enum")
        gate_precedence = self.gates.get("precedence")
        classification_precedence = self.classifications.get("precedence")
        if not isinstance(gate_precedence, list) or not isinstance(classification_precedence, list):
            raise ValueError("gate and classification precedence must be lists")
        if classification_precedence[: len(gate_precedence)] != gate_precedence:
            raise ValueError("gate precedence must prefix classification precedence")
        if set(classification_precedence) != {item.value for item in Classification}:
            raise ValueError("classification precedence must contain every classification")
        pos_priors = self.pos.get("base_midpoint_pct")
        if not isinstance(pos_priors, dict) or not set(pos_priors).issubset(
            {item.value for item in CatalystType}
        ):
            raise ValueError("PoS priors must use catalyst taxonomy codes")
        windows = self.time_windows_days
        if not (windows["actionable_min"] <= windows["actionable_max"] <= windows["discovery_max"]):
            raise ValueError("time windows are not ordered")
        critical_fields = self.missing_data.get("critical_fields")
        if not isinstance(critical_fields, list) or len(critical_fields) != len(
            set(critical_fields)
        ):
            raise ValueError("critical fields must be a unique list")
        high = self.classifications.get("HIGH_CONVICTION_CATALYST_SWING", {}).get("raw_score_min")
        catalyst = self.classifications.get("CATALYST_SWING", {}).get("raw_score_min")
        watchlist = self.classifications.get("WATCHLIST", {}).get("raw_score_min")
        if not all(isinstance(value, int) for value in (high, catalyst, watchlist)):
            raise ValueError("classification score thresholds must be integers")
        if not high > catalyst > watchlist:
            raise ValueError("classification score thresholds are not strictly ordered")
        return self
