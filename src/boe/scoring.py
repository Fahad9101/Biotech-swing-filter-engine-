"""Deterministic BOE-1.0.0 factor scoring and coverage calculation.

Milestone 5 scores validated inputs only.  It does not ingest or calculate market
bars; technical observations may be supplied explicitly and Milestone 6 remains
responsible for producing them from market data.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.enums import CatalystType, DataState, DilutionRisk, FactorCode, TimingConfidence
from boe.models import ContractModel, FactorScore, FactorSubscore, ScoreBreakdown, ScorecardContract
from boe.science_review import ManualScienceReview

MaturityBucket = Literal[
    "PRECLINICAL_OTHER",
    "PHASE_1",
    "PHASE_1_2_OR_FILING_ACCEPTANCE",
    "PHASE_2_OR_MATERIAL_REGULATORY",
    "PHASE_2_3_PHASE_3_ADCOM_DECISION",
]
BurnConfidence = Literal["LOW", "MODERATE", "HIGH"]

MATERIALITY_CEILINGS: dict[CatalystType, int] = {
    CatalystType.CLIN_P1: 4,
    CatalystType.CLIN_P1_2: 6,
    CatalystType.CLIN_P2: 7,
    CatalystType.CLIN_P2_3: 8,
    CatalystType.CLIN_P3: 8,
    CatalystType.REG_SUBMIT: 5,
    CatalystType.REG_ADCOM: 8,
    CatalystType.REG_DECISION: 8,
    CatalystType.REG_OTHER: 7,
    CatalystType.CONF_DATA: 6,
    CatalystType.PUBLICATION: 4,
    CatalystType.PARTNER: 5,
    CatalystType.COMMERCIAL: 5,
    CatalystType.FINANCING: 3,
}


class SubfactorEvidence(ContractModel):
    data_state: DataState
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...]

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("subfactor evidence IDs must be unique")
        if self.data_state is not DataState.MISSING and not self.evidence_ids:
            raise ValueError("non-missing scored inputs require evidence lineage")
        return self


class CatalystScoreInput(ContractModel):
    as_of: datetime
    catalyst_type: CatalystType
    window_start: date
    timing_confidence: TimingConfidence
    materiality_points: int | None = None
    novelty_points: int | None = None
    maturity_bucket: MaturityBucket | None = None
    evidence: dict[str, SubfactorEvidence]

    @model_validator(mode="after")
    def validate_manual_points(self) -> Self:
        _require_aware(self.as_of, "as_of")
        if self.materiality_points is not None:
            if self.materiality_points not in {0, 2, 4, 6, 8}:
                raise ValueError("materiality must use the frozen allowed point values")
            if self.materiality_points > MATERIALITY_CEILINGS[self.catalyst_type]:
                raise ValueError("materiality exceeds the frozen catalyst-type ceiling")
        if self.novelty_points is not None and self.novelty_points not in {0, 1, 2, 3}:
            raise ValueError("novel-information points outside frozen rubric")
        return self


class MarketImpactScoreInput(ContractModel):
    asset_value_concentration_pct: Decimal | None = None
    asset_is_immaterial: bool = False
    success_rerating_pct: Decimal | None = None
    expectation_gap_points: int | None = None
    independent_expectation_supports: int = Field(default=0, ge=0)
    competitive_position_points: int | None = None
    evidence: dict[str, SubfactorEvidence]


class CashDilutionScoreInput(ContractModel):
    runway_months: Decimal | None = Field(default=None, ge=0)
    burn_confidence: BurnConfidence | None = None
    financing_overhang: DilutionRisk | None = None
    cash_and_securities: Decimal | None = Field(default=None, ge=0)
    debt: Decimal | None = Field(default=None, ge=0)
    runway_at_catalyst_months: Decimal | None = Field(default=None, ge=0)
    restrictive_obligations: bool | None = None
    evidence: dict[str, SubfactorEvidence]


class ValuationScoreInput(ContractModel):
    conservative_mos_pct: Decimal | None = None
    base_mos_pct: Decimal | None = None
    failure_downside_pct: Decimal | None = Field(default=None, ge=0)
    valuation_bounded: bool = True
    evidence: dict[str, SubfactorEvidence]


class TechnicalScoreInput(ContractModel):
    close: Decimal | None = None
    sma20: Decimal | None = None
    sma50: Decimal | None = None
    xbi_relative_return_20d_pct: Decimal | None = None
    up_down_dollar_volume_ratio: Decimal | None = Field(default=None, ge=0)
    obv_slope_positive: bool | None = None
    support: Decimal | None = None
    base_success_target: Decimal | None = None
    rsi14: Decimal | None = Field(default=None, ge=0, le=100)
    evidence: dict[str, SubfactorEvidence]


class OwnershipScoreInput(ContractModel):
    reliable_specialist_data: bool
    net_specialist_exit: bool = False
    accumulating_specialist_funds: int = Field(default=0, ge=0)
    meaningful_specialist_funds: int = Field(default=0, ge=0)
    new_or_add_ge_half_pct: bool = False
    insider_purchase_usd: Decimal | None = Field(default=None, ge=0)
    insider_purchase_age_days: int | None = Field(default=None, ge=0)
    offsetting_discretionary_sale: bool = False
    material_discretionary_selling: bool = False
    evidence: dict[str, SubfactorEvidence]


class SentimentScoreInput(ContractModel):
    five_day_to_prior_sixty_day_volume_ratio: Decimal | None = Field(default=None, ge=0)
    attributable_primary_news: bool | None = None
    independent_positive_revisions: int | None = Field(default=None, ge=0)
    mixed_or_one_revision: bool | None = None
    xbi_close_above_sma50: bool | None = None
    xbi_20d_return_positive: bool | None = None
    evidence: dict[str, SubfactorEvidence]


def score_catalyst(input_: CatalystScoreInput, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.CATALYST)
    values: list[FactorSubscore] = []
    values.append(
        _subscore(
            definition,
            "MATERIALITY",
            input_.materiality_points,
            input_.evidence,
        )
    )
    timing_mapping = _subfactor_rule(definition, "TIMING_CONFIDENCE").get("mapping")
    if not isinstance(timing_mapping, dict):
        raise TypeError("timing-confidence mapping missing from scorecard")
    timing_points = int(timing_mapping[input_.timing_confidence.value])
    values.append(_subscore(definition, "TIMING_CONFIDENCE", timing_points, input_.evidence))
    days = (input_.window_start - input_.as_of.date()).days
    proximity_points = _proximity_points(days)
    values.append(_subscore(definition, "PROXIMITY", proximity_points, input_.evidence))
    maturity_bucket = input_.maturity_bucket or _derived_maturity_bucket(input_.catalyst_type)
    if maturity_bucket is None:
        raise ValueError("catalyst type requires an explicit underlying maturity bucket")
    maturity_mapping = _subfactor_rule(definition, "MATURITY").get("mapping")
    if not isinstance(maturity_mapping, dict):
        raise TypeError("maturity mapping missing from scorecard")
    maturity_points = int(maturity_mapping[maturity_bucket])
    values.append(_subscore(definition, "MATURITY", maturity_points, input_.evidence))
    values.append(
        _subscore(definition, "NOVEL_INFORMATION", input_.novelty_points, input_.evidence)
    )
    return _factor_score(FactorCode.CATALYST, definition.max_points, values)


def score_science(review: ManualScienceReview, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.SCIENCE)
    scores = review.score_by_code()
    values: list[FactorSubscore] = []
    evidence_ids = tuple(str(value) for value in review.evidence_ids)
    for code in (
        "BIOLOGICAL_RATIONALE",
        "PRIOR_HUMAN_EVIDENCE",
        "TRIAL_DESIGN",
        "EFFICACY_ROBUSTNESS",
        "SAFETY",
        "EXTERNAL_VALIDATION",
    ):
        subrule = _subfactor_rule(definition, code)
        max_points = int(subrule["max_points"])
        point = scores[code]
        allowed = subrule.get("allowed_points")
        if isinstance(allowed, list) and point not in allowed:
            raise ValueError(f"{code} review score is outside frozen allowed values")
        values.append(
            FactorSubscore(
                code=code,
                points=point,
                max_points=max_points,
                data_state=DataState.DERIVED,
                rationale=review.rationales[code],
                evidence_ids=evidence_ids,
            )
        )
    return _factor_score(FactorCode.SCIENCE, definition.max_points, values)


def score_market_impact(
    input_: MarketImpactScoreInput,
    rules: ScorecardContract,
) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.MARKET_IMPACT)
    if input_.asset_is_immaterial:
        concentration = 0
    elif input_.asset_value_concentration_pct is None:
        concentration = None
    else:
        concentration = _asset_concentration_points(input_.asset_value_concentration_pct)
    rerating = (
        None
        if input_.success_rerating_pct is None
        else _success_rerating_points(input_.success_rerating_pct)
    )
    expectation = input_.expectation_gap_points
    if expectation is not None:
        if expectation not in {0, 1, 2, 3, 4}:
            raise ValueError("expectation-gap points outside frozen rubric")
        if expectation == 4 and input_.independent_expectation_supports < 2:
            raise ValueError("maximum expectation-gap score requires two independent supports")
    competitive = input_.competitive_position_points
    if competitive is not None and competitive not in {0, 1, 2}:
        raise ValueError("competitive-position points outside frozen rubric")
    values = [
        _subscore(definition, "ASSET_VALUE_CONCENTRATION", concentration, input_.evidence),
        _subscore(definition, "SUCCESS_RERATING", rerating, input_.evidence),
        _subscore(definition, "EXPECTATION_GAP", expectation, input_.evidence),
        _subscore(definition, "COMPETITIVE_POSITION", competitive, input_.evidence),
    ]
    return _factor_score(FactorCode.MARKET_IMPACT, definition.max_points, values)


def score_cash_dilution(
    input_: CashDilutionScoreInput,
    rules: ScorecardContract,
) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.CASH_DILUTION)
    runway = None
    if input_.runway_months is not None:
        runway = _runway_points(input_.runway_months, input_.burn_confidence)
    overhang = None
    if input_.financing_overhang is not None:
        mapping = _subfactor_rule(definition, "FINANCING_OVERHANG").get("mapping")
        if not isinstance(mapping, dict):
            raise TypeError("financing-overhang mapping missing from scorecard")
        overhang = int(mapping[input_.financing_overhang.value])
    flexibility = _balance_sheet_flexibility(input_)
    values = [
        _subscore(definition, "RUNWAY", runway, input_.evidence),
        _subscore(definition, "FINANCING_OVERHANG", overhang, input_.evidence),
        _subscore(definition, "BALANCE_SHEET_FLEXIBILITY", flexibility, input_.evidence),
    ]
    return _factor_score(FactorCode.CASH_DILUTION, definition.max_points, values)


def score_valuation(input_: ValuationScoreInput, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.VALUATION)
    if not input_.valuation_bounded:
        values = [
            _subscore(definition, "CONSERVATIVE_MOS", 0, input_.evidence),
            _subscore(definition, "BASE_MOS", 0, input_.evidence),
            _subscore(definition, "FAILURE_VALUE_SUPPORT", 0, input_.evidence),
        ]
        return _factor_score(FactorCode.VALUATION, definition.max_points, values)
    conservative = (
        None
        if input_.conservative_mos_pct is None
        else _conservative_mos_points(input_.conservative_mos_pct)
    )
    base = None if input_.base_mos_pct is None else _base_mos_points(input_.base_mos_pct)
    failure = (
        None
        if input_.failure_downside_pct is None
        else _failure_support_points(input_.failure_downside_pct)
    )
    values = [
        _subscore(definition, "CONSERVATIVE_MOS", conservative, input_.evidence),
        _subscore(definition, "BASE_MOS", base, input_.evidence),
        _subscore(definition, "FAILURE_VALUE_SUPPORT", failure, input_.evidence),
    ]
    return _factor_score(FactorCode.VALUATION, definition.max_points, values)


def score_technicals(input_: TechnicalScoreInput, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.TECHNICAL)
    trend = _trend_points(input_)
    relative = _relative_strength_points(input_.xbi_relative_return_20d_pct)
    accumulation = _accumulation_points(input_)
    structure = _structure_points(input_)
    extension = _extension_points(input_)
    values = [
        _subscore(definition, "TREND", trend, input_.evidence),
        _subscore(definition, "RELATIVE_STRENGTH", relative, input_.evidence),
        _subscore(definition, "ACCUMULATION", accumulation, input_.evidence),
        _subscore(definition, "STRUCTURE", structure, input_.evidence),
        _subscore(definition, "EXTENSION", extension, input_.evidence),
    ]
    return _factor_score(FactorCode.TECHNICAL, definition.max_points, values)


def score_ownership(input_: OwnershipScoreInput, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.OWNERSHIP)
    if not input_.reliable_specialist_data or input_.net_specialist_exit:
        specialist = 0
    elif input_.meaningful_specialist_funds >= 3 and input_.new_or_add_ge_half_pct:
        specialist = 3
    elif input_.accumulating_specialist_funds >= 2:
        specialist = 2
    else:
        specialist = 1
    if input_.material_discretionary_selling or input_.insider_purchase_usd is None:
        insider = 0
    elif (
        input_.insider_purchase_usd >= Decimal("50000")
        and input_.insider_purchase_age_days is not None
        and input_.insider_purchase_age_days <= 180
        and not input_.offsetting_discretionary_sale
    ):
        insider = 2
    else:
        insider = 1
    values = [
        _subscore(definition, "SPECIALIST_OWNERSHIP", specialist, input_.evidence),
        _subscore(definition, "INSIDER_SIGNAL", insider, input_.evidence),
    ]
    return _factor_score(FactorCode.OWNERSHIP, definition.max_points, values)


def score_sentiment(input_: SentimentScoreInput, rules: ScorecardContract) -> FactorScore:
    definition = _factor_definition(rules, FactorCode.SENTIMENT)
    ratio_condition = (
        input_.five_day_to_prior_sixty_day_volume_ratio is not None
        and input_.five_day_to_prior_sixty_day_volume_ratio >= Decimal("1.5")
    )
    news_condition = input_.attributable_primary_news is True
    if (
        input_.five_day_to_prior_sixty_day_volume_ratio is None
        and input_.attributable_primary_news is None
    ):
        attention = None
    elif ratio_condition and news_condition:
        attention = 2
    elif ratio_condition or news_condition:
        attention = 1
    else:
        attention = 0
    if input_.independent_positive_revisions is None and input_.mixed_or_one_revision is None:
        direction = None
    elif (
        input_.independent_positive_revisions is not None
        and input_.independent_positive_revisions >= 2
    ):
        direction = 2
    elif input_.mixed_or_one_revision is True or input_.independent_positive_revisions == 1:
        direction = 1
    else:
        direction = 0
    if input_.xbi_close_above_sma50 is None or input_.xbi_20d_return_positive is None:
        sector = None
    else:
        sector = int(input_.xbi_close_above_sma50 and input_.xbi_20d_return_positive)
    values = [
        _subscore(definition, "ATTENTION_VOLUME", attention, input_.evidence),
        _subscore(definition, "EXPECTATION_DIRECTION", direction, input_.evidence),
        _subscore(definition, "SECTOR_REGIME", sector, input_.evidence),
    ]
    return _factor_score(FactorCode.SENTIMENT, definition.max_points, values)


def build_score_breakdown(factors: tuple[FactorScore, ...]) -> ScoreBreakdown:
    return ScoreBreakdown(
        raw_total=sum(factor.points for factor in factors),
        factors=factors,
    )


def calculate_coverage_pct(score: ScoreBreakdown) -> Decimal:
    observed_maximum = sum(
        subfactor.max_points
        for factor in score.factors
        for subfactor in factor.subfactors
        if subfactor.data_state is not DataState.MISSING
    )
    return Decimal(observed_maximum)


def _factor_definition(rules: ScorecardContract, code: FactorCode):
    for definition in rules.factors:
        if definition.code is code:
            return definition
    raise ValueError(f"factor definition missing: {code.value}")


def _subfactor_rule(definition, code: str) -> dict[str, object]:
    for subfactor in definition.subfactors:
        if subfactor.code == code:
            return subfactor.model_dump()
    raise ValueError(f"subfactor definition missing: {code}")


def _subscore(
    definition,
    code: str,
    points: int | None,
    evidence: dict[str, SubfactorEvidence],
) -> FactorSubscore:
    if code not in evidence:
        raise ValueError(f"evidence metadata missing for {code}")
    metadata = evidence[code]
    max_points = int(_subfactor_rule(definition, code)["max_points"])
    if points is None:
        if metadata.data_state is not DataState.MISSING:
            raise ValueError(f"{code} has no value but is not marked missing")
        resolved_points = 0
    else:
        if metadata.data_state is DataState.MISSING:
            raise ValueError(f"{code} has a value but is marked missing")
        resolved_points = points
    return FactorSubscore(
        code=code,
        points=resolved_points,
        max_points=max_points,
        data_state=metadata.data_state,
        rationale=metadata.rationale,
        evidence_ids=tuple(str(value) for value in metadata.evidence_ids),
    )


def _factor_score(code: FactorCode, max_points: int, values: list[FactorSubscore]) -> FactorScore:
    return FactorScore(
        code=code,
        points=sum(item.points for item in values),
        max_points=max_points,
        subfactors=tuple(values),
    )


def _proximity_points(days: int) -> int:
    if days > 180 or days < 0:
        return 0
    if days >= 85:
        return 1
    if days >= 43:
        return 3
    if days >= 7:
        return 4
    return 2


def _derived_maturity_bucket(catalyst_type: CatalystType) -> MaturityBucket | None:
    if catalyst_type is CatalystType.CLIN_P1:
        return "PHASE_1"
    if catalyst_type in {CatalystType.CLIN_P1_2, CatalystType.REG_SUBMIT}:
        return "PHASE_1_2_OR_FILING_ACCEPTANCE"
    if catalyst_type in {CatalystType.CLIN_P2, CatalystType.REG_OTHER}:
        return "PHASE_2_OR_MATERIAL_REGULATORY"
    if catalyst_type in {
        CatalystType.CLIN_P2_3,
        CatalystType.CLIN_P3,
        CatalystType.REG_ADCOM,
        CatalystType.REG_DECISION,
    }:
        return "PHASE_2_3_PHASE_3_ADCOM_DECISION"
    return None


def _asset_concentration_points(value: Decimal) -> int:
    if value < 0:
        raise ValueError("asset-value concentration cannot be negative")
    if value < 10:
        return 1
    if value < 25:
        return 2
    if value < 50:
        return 3
    if value < 75:
        return 4
    return 5


def _success_rerating_points(value: Decimal) -> int:
    if value < 10:
        return 0
    if value < 20:
        return 1
    if value < 40:
        return 2
    if value < 75:
        return 3
    return 4


def _runway_points(value: Decimal, confidence: BurnConfidence | None) -> int:
    if confidence is None:
        raise ValueError("runway scoring requires burn confidence")
    if value < 12:
        return 0
    if value < 18:
        return 1
    if value < 24:
        return 2 if confidence == "LOW" else 3
    if value < 30:
        return 4
    return 5


def _balance_sheet_flexibility(input_: CashDilutionScoreInput) -> int | None:
    required = (
        input_.cash_and_securities,
        input_.debt,
        input_.runway_at_catalyst_months,
        input_.restrictive_obligations,
    )
    if any(value is None for value in required):
        return None
    assert input_.cash_and_securities is not None
    assert input_.debt is not None
    assert input_.runway_at_catalyst_months is not None
    assert input_.restrictive_obligations is not None
    if input_.debt > input_.cash_and_securities or input_.restrictive_obligations:
        return 0
    if input_.cash_and_securities > input_.debt and input_.runway_at_catalyst_months >= 18:
        return 2
    return 1


def _conservative_mos_points(value: Decimal) -> int:
    if value < -25:
        return 0
    if value < 0:
        return 1
    if value < 25:
        return 2
    if value < 50:
        return 3
    return 4


def _base_mos_points(value: Decimal) -> int:
    if value < 0:
        return 0
    if value < 25:
        return 1
    if value < 75:
        return 2
    return 3


def _failure_support_points(downside: Decimal) -> int:
    if downside > 70:
        return 0
    if downside > 50:
        return 1
    if downside > 30:
        return 2
    return 3


def _trend_points(input_: TechnicalScoreInput) -> int | None:
    if input_.close is None or input_.sma20 is None or input_.sma50 is None:
        return None
    if input_.close > input_.sma20 > input_.sma50:
        return 2
    if input_.close > input_.sma50:
        return 1
    return 0


def _relative_strength_points(value: Decimal | None) -> int | None:
    if value is None:
        return None
    if value >= 10:
        return 2
    if value >= 0:
        return 1
    return 0


def _accumulation_points(input_: TechnicalScoreInput) -> int | None:
    if input_.up_down_dollar_volume_ratio is None or input_.obv_slope_positive is None:
        return None
    conditions = int(input_.up_down_dollar_volume_ratio >= Decimal("1.5")) + int(
        input_.obv_slope_positive
    )
    return conditions


def _structure_points(input_: TechnicalScoreInput) -> int | None:
    if input_.close is None or input_.support is None or input_.base_success_target is None:
        return None
    if input_.support <= 0 or input_.close <= 0:
        raise ValueError("technical prices must be positive")
    support_distance = (input_.close / input_.support - Decimal("1")) * Decimal("100")
    target_room = (input_.base_success_target / input_.close - Decimal("1")) * Decimal("100")
    if Decimal("0") <= support_distance <= Decimal("8") and target_room >= 15:
        return 2
    if Decimal("8") < support_distance <= Decimal("15") or Decimal("8") <= target_room <= Decimal(
        "15"
    ):
        return 1
    return 0


def _extension_points(input_: TechnicalScoreInput) -> int | None:
    if input_.close is None or input_.sma20 is None or input_.rsi14 is None:
        return None
    if input_.sma20 <= 0:
        raise ValueError("SMA20 must be positive")
    above_sma20 = (input_.close / input_.sma20 - Decimal("1")) * Decimal("100")
    if above_sma20 <= 8 and Decimal("45") <= input_.rsi14 <= Decimal("70"):
        return 2
    if above_sma20 <= 15 and input_.rsi14 < 75:
        return 1
    return 0


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
