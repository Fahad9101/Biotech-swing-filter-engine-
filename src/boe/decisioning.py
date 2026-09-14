"""Deterministic BOE-1.0.0 classification after ordered gate evaluation."""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from boe.enums import Classification, FactorCode, TimingConfidence
from boe.gates import GateEvaluation
from boe.models import ContractModel, ScoreBreakdown, ScorecardContract
from boe.valuation import ExpectedValueResult


class ClassificationInput(ContractModel):
    score: ScoreBreakdown
    coverage_pct: Decimal = Field(ge=0, le=100)
    timing_confidence: TimingConfidence
    catalyst_days: int
    expected_value: ExpectedValueResult
    success_upside_pct: Decimal
    failure_downside_pct: Decimal = Field(ge=0)
    gates: GateEvaluation
    critical_data_refresh_age_hours: Decimal | None = Field(default=None, ge=0)
    watchlist_specific_price_clears_test: bool = False
    watchlist_noncritical_uncertainty: bool = False


class ClassificationResult(ContractModel):
    classification: Classification
    rationale: str
    raw_score: int
    coverage_pct: Decimal
    factor_points: dict[str, int]


def classify(input_: ClassificationInput, rules: ScorecardContract) -> ClassificationResult:
    factor_points = {factor.code.value: factor.points for factor in input_.score.factors}
    if input_.gates.dominant_classification is not None:
        return _result(
            input_.gates.dominant_classification,
            "higher-precedence frozen risk gate triggered",
            input_,
            factor_points,
        )

    high = rules.classifications[Classification.HIGH_CONVICTION_CATALYST_SWING.value]
    if _meets_high_conviction(input_, factor_points, high):
        return _result(
            Classification.HIGH_CONVICTION_CATALYST_SWING,
            "all frozen high-conviction requirements satisfied",
            input_,
            factor_points,
        )

    swing = rules.classifications[Classification.CATALYST_SWING.value]
    if _meets_catalyst_swing(input_, factor_points, swing):
        return _result(
            Classification.CATALYST_SWING,
            "all frozen catalyst-swing requirements satisfied",
            input_,
            factor_points,
        )

    watchlist = rules.classifications[Classification.WATCHLIST.value]
    watchlist_score = input_.score.raw_total >= int(watchlist["raw_score_min"])
    forced_coverage = input_.coverage_pct >= Decimal(
        str(watchlist["coverage_pct_min"])
    ) and input_.coverage_pct <= Decimal(str(watchlist["coverage_pct_max_for_forced_watchlist"]))
    if (
        watchlist_score
        or forced_coverage
        or input_.watchlist_specific_price_clears_test
        or input_.watchlist_noncritical_uncertainty
    ):
        return _result(
            Classification.WATCHLIST,
            "credible setup remains below an investable BOE-1.0.0 classification",
            input_,
            factor_points,
        )

    return _result(
        Classification.REJECT,
        "raw score below 60 without a higher-precedence gate or watchlist condition",
        input_,
        factor_points,
    )


def _meets_high_conviction(
    input_: ClassificationInput,
    factor_points: dict[str, int],
    rules: dict[str, object],
) -> bool:
    return (
        input_.score.raw_total >= int(rules["raw_score_min"])
        and input_.coverage_pct >= Decimal(str(rules["coverage_pct_min"]))
        and _factor_minimums(factor_points, rules["factor_min"])
        and input_.timing_confidence.value in set(rules["allowed_timing_confidence"])
        and input_.catalyst_days >= int(rules["catalyst_days_min"])
        and input_.catalyst_days <= int(rules["catalyst_days_max"])
        and input_.expected_value.base_ev_pct >= Decimal(str(rules["base_ev_min_pct"]))
        and input_.expected_value.conservative_ev_pct
        >= Decimal(str(rules["conservative_ev_min_pct"]))
        and input_.expected_value.reward_risk >= Decimal(str(rules["reward_risk_min"]))
        and input_.success_upside_pct >= Decimal(str(rules["success_upside_min_pct"]))
        and input_.failure_downside_pct <= Decimal(str(rules["failure_downside_max_pct"]))
    )


def _meets_catalyst_swing(
    input_: ClassificationInput,
    factor_points: dict[str, int],
    rules: dict[str, object],
) -> bool:
    if input_.catalyst_days < 7:
        max_age = Decimal(str(rules["inside_seven_days_critical_refresh_hours_max"]))
        if (
            input_.critical_data_refresh_age_hours is None
            or input_.critical_data_refresh_age_hours > max_age
        ):
            return False
    return (
        input_.score.raw_total >= int(rules["raw_score_min"])
        and input_.coverage_pct >= Decimal(str(rules["coverage_pct_min"]))
        and _factor_minimums(factor_points, rules["factor_min"])
        and input_.timing_confidence.value in set(rules["allowed_timing_confidence"])
        and input_.catalyst_days >= int(rules["catalyst_days_min"])
        and input_.catalyst_days <= int(rules["catalyst_days_max"])
        and input_.expected_value.base_ev_pct >= Decimal(str(rules["base_ev_min_pct"]))
        and input_.expected_value.conservative_ev_pct
        >= Decimal(str(rules["conservative_ev_min_pct"]))
        and input_.expected_value.reward_risk >= Decimal(str(rules["reward_risk_min"]))
        and input_.success_upside_pct >= Decimal(str(rules["success_upside_min_pct"]))
    )


def _factor_minimums(factor_points: dict[str, int], raw: object) -> bool:
    if not isinstance(raw, dict):
        raise TypeError("classification factor_min must be a mapping")
    for code in (
        FactorCode.CATALYST,
        FactorCode.SCIENCE,
        FactorCode.CASH_DILUTION,
        FactorCode.VALUATION,
    ):
        minimum = raw.get(code.value)
        if minimum is not None and factor_points.get(code.value, 0) < int(minimum):
            return False
    return True


def _result(
    classification: Classification,
    rationale: str,
    input_: ClassificationInput,
    factor_points: dict[str, int],
) -> ClassificationResult:
    return ClassificationResult(
        classification=classification,
        rationale=rationale,
        raw_score=input_.score.raw_total,
        coverage_pct=input_.coverage_pct,
        factor_points=factor_points,
    )
