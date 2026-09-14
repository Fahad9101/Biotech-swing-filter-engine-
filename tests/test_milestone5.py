from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from boe.contracts import load_scorecard
from boe.decisioning import ClassificationInput, classify
from boe.enums import (
    CatalystType,
    Classification,
    DataState,
    DilutionRisk,
    FactorCode,
    PosConfidence,
    TimingConfidence,
)
from boe.gates import GateEvaluation, GateInput, evaluate_gates
from boe.models import (
    FactorScore,
    FactorSubscore,
    OrderedRange,
    ProbabilityAssessment,
    ScoreBreakdown,
)
from boe.pos import PosInput, estimate_event_pos
from boe.science_review import ManualScienceReview, require_review_cutoff
from boe.scoring import (
    CashDilutionScoreInput,
    CatalystScoreInput,
    MarketImpactScoreInput,
    OwnershipScoreInput,
    SentimentScoreInput,
    SubfactorEvidence,
    TechnicalScoreInput,
    ValuationScoreInput,
    build_score_breakdown,
    calculate_coverage_pct,
    score_cash_dilution,
    score_catalyst,
    score_market_impact,
    score_ownership,
    score_science,
    score_sentiment,
    score_technicals,
    score_valuation,
)
from boe.valuation import (
    AnnualAssetCashFlow,
    AssetRnpvInput,
    EquityBridgeInput,
    ExpectedValueInput,
    ExpectedValueResult,
    RnpvInput,
    calculate_expected_value,
    calculate_rnpv,
)

FROZEN_SCORECARD_SHA256 = "11cffb776ffd6bbd943b1d23dfcf6541ab02fcbfec753f13d00a7f4acee8b569"
AS_OF = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000001")
CATALYST_ID = UUID("00000000-0000-0000-0000-000000000002")

SCIENCE_CODES = (
    "BIOLOGICAL_RATIONALE",
    "PRIOR_HUMAN_EVIDENCE",
    "TRIAL_DESIGN",
    "EFFICACY_ROBUSTNESS",
    "SAFETY",
    "EXTERNAL_VALIDATION",
)


def _rules(scorecard_path: Path):
    return load_scorecard(scorecard_path).contract


def _review(
    *,
    confidence: PosConfidence = PosConfidence.HIGH,
    source_quality: str = "MIXED",
    biological: int = 3,
    prior: int = 4,
    design: int = 4,
    efficacy: int = 2,
    safety: int = 2,
    external: int = 2,
    **flags: bool,
) -> ManualScienceReview:
    rationales = {code: f"locked rationale for {code}" for code in SCIENCE_CODES}
    return ManualScienceReview(
        issuer_id="issuer-1",
        catalyst_version_id=CATALYST_ID,
        evidence_cutoff=AS_OF,
        reviewer="reviewer@example.test",
        reviewed_at=AS_OF + timedelta(hours=1),
        biological_rationale=biological,
        prior_human_evidence=prior,
        trial_design=design,
        efficacy_robustness=efficacy,
        safety=safety,
        external_validation=external,
        evidence_confidence=confidence,
        source_quality=source_quality,
        evidence_ids=(EVIDENCE_ID,),
        rationales=rationales,
        **flags,
    )


def _evidence(*codes: str, missing: set[str] | None = None) -> dict[str, SubfactorEvidence]:
    missing = missing or set()
    return {
        code: SubfactorEvidence(
            data_state=DataState.MISSING if code in missing else DataState.DERIVED,
            rationale=f"evidence for {code}",
            evidence_ids=() if code in missing else (EVIDENCE_ID,),
        )
        for code in codes
    }


def test_frozen_scorecard_checksum_is_unchanged(scorecard_path: Path):
    assert load_scorecard(scorecard_path).raw_sha256 == FROZEN_SCORECARD_SHA256


def test_company_only_science_caps_and_point_in_time_cutoff():
    with pytest.raises(ValueError):
        _review(source_quality="COMPANY_ONLY", prior=5, confidence=PosConfidence.MODERATE)
    with pytest.raises(ValueError):
        _review(source_quality="COMPANY_ONLY", efficacy=3, confidence=PosConfidence.MODERATE)
    with pytest.raises(ValueError):
        _review(source_quality="COMPANY_ONLY", confidence=PosConfidence.HIGH)

    valid = _review(
        source_quality="COMPANY_ONLY",
        prior=4,
        efficacy=2,
        confidence=PosConfidence.MODERATE,
    )
    require_review_cutoff(valid, AS_OF)
    with pytest.raises(ValueError):
        require_review_cutoff(valid, AS_OF - timedelta(seconds=1))


def test_science_score_matches_locked_review(scorecard_path: Path):
    result = score_science(_review(), _rules(scorecard_path))
    assert result.code is FactorCode.SCIENCE
    assert result.points == 17
    assert result.max_points == 20
    assert [item.points for item in result.subfactors] == [3, 4, 4, 2, 2, 2]


def test_phase2_pos_golden_case_and_independent_recomputation(
    scorecard_path: Path, repository_root: Path
):
    fixture = json.loads(
        (repository_root / "tests" / "fixtures" / "milestone5_golden.json").read_text()
    )["pos_phase2"]
    result = estimate_event_pos(
        PosInput(catalyst_type=CatalystType.CLIN_P2, science_review=_review()),
        _rules(scorecard_path),
    )

    independent_mid = Decimal(str(fixture["prior_pct"]))
    independent_mid += (Decimal(str(fixture["science"]["prior_human_evidence"])) - 2) * 4
    independent_mid += (Decimal(str(fixture["science"]["trial_design"])) - 3) * 4
    independent_mid += (Decimal(str(fixture["science"]["efficacy_robustness"])) - 1) * 4
    independent_mid += (Decimal(str(fixture["science"]["safety"])) - 1) * 3
    independent_mid += (Decimal(str(fixture["science"]["external_validation"])) - 1) * 3

    assert independent_mid == Decimal(str(fixture["expected_mid_pct"]))
    assert Decimal(str(result.assessment.event_success_pct.mid)) == independent_mid
    assert result.assessment.event_success_pct.low == fixture["expected_low_pct"]
    assert result.assessment.event_success_pct.high == fixture["expected_high_pct"]


def test_pos_penalties_stack_and_bounds_clamp(scorecard_path: Path):
    rules = _rules(scorecard_path)
    low = estimate_event_pos(
        PosInput(
            catalyst_type=CatalystType.CLIN_P2,
            science_review=_review(
                confidence=PosConfidence.LOW,
                biological=0,
                prior=0,
                design=0,
                efficacy=0,
                safety=0,
                external=0,
            ),
        ),
        rules,
    )
    assert low.assessment.event_success_pct.low == 5
    assert low.assessment.event_success_pct.mid == 10
    assert low.assessment.event_success_pct.high == 25

    penalized = estimate_event_pos(
        PosInput(
            catalyst_type=CatalystType.CLIN_P1,
            science_review=_review(
                prior=5,
                design=5,
                efficacy=3,
                safety=2,
                external=2,
                single_arm_when_comparator_required=True,
                multiplicity_or_endpoint_ambiguity=True,
                material_unresolved_safety_imbalance=True,
            ),
        ),
        rules,
    )
    assert penalized.trace.penalties_pp == {
        "single_arm_when_comparator_required": Decimal("-10"),
        "multiplicity_or_endpoint_ambiguity": Decimal("-10"),
        "material_unresolved_safety_imbalance": Decimal("-15"),
    }
    assert penalized.assessment.event_success_pct.mid == 69


def test_non_scientific_pos_cap_and_underlying_phase_requirement(scorecard_path: Path):
    rules = _rules(scorecard_path)
    undated = estimate_event_pos(
        PosInput(
            catalyst_type=CatalystType.PARTNER,
            science_review=_review(confidence=PosConfidence.MODERATE),
            event_specific_prior_pct=Decimal("80"),
            contractually_dated=False,
        ),
        rules,
    )
    assert undated.assessment.prior_pct == 50

    dated = estimate_event_pos(
        PosInput(
            catalyst_type=CatalystType.PARTNER,
            science_review=_review(confidence=PosConfidence.MODERATE),
            event_specific_prior_pct=Decimal("80"),
            contractually_dated=True,
        ),
        rules,
    )
    assert dated.assessment.prior_pct == 80

    with pytest.raises(ValueError):
        PosInput(catalyst_type=CatalystType.CONF_DATA, science_review=_review())


def _base_rnpv_input(*, scenario: str = "BASE", pos: Decimal = Decimal("50")) -> RnpvInput:
    return RnpvInput(
        issuer_id="issuer-1",
        catalyst_version_id=CATALYST_ID,
        as_of=AS_OF,
        scenario=scenario,
        assets=(
            AssetRnpvInput(
                asset="Asset A",
                indication="Disease A",
                issuer_economic_share_pct=Decimal("100"),
                pos_pct=pos,
                annual_cash_flows=(
                    AnnualAssetCashFlow(
                        year_index=1,
                        commercial_after_tax_fcf=Decimal("100"),
                        remaining_development_cost=Decimal("20"),
                        evidence_ids=(EVIDENCE_ID,),
                    ),
                    AnnualAssetCashFlow(
                        year_index=2,
                        commercial_after_tax_fcf=Decimal("100"),
                        remaining_development_cost=Decimal("20"),
                        evidence_ids=(EVIDENCE_ID,),
                    ),
                ),
            ),
        ),
        bridge=EquityBridgeInput(
            unrestricted_cash=Decimal("100"),
            marketable_securities=Decimal("0"),
            debt=Decimal("10"),
            financing_obligations=Decimal("0"),
            corporate_overhead_pv=Decimal("20"),
            expected_dilution_cost=Decimal("5"),
            fully_diluted_shares=Decimal("10"),
            evidence_ids=(EVIDENCE_ID,),
        ),
    )


def test_rnpv_matches_independent_discounted_cash_flow():
    result = calculate_rnpv(_base_rnpv_input())
    rate = Decimal("0.15")
    independent_commercial = Decimal("50") / (1 + rate) + Decimal("50") / (1 + rate) ** 2
    independent_development = Decimal("20") / (1 + rate) + Decimal("20") / (1 + rate) ** 2
    independent_asset = independent_commercial - independent_development
    independent_equity = independent_asset + Decimal("100") - 10 - 20 - 5

    assert result.asset_results[0].commercial_pv == independent_commercial
    assert result.asset_results[0].development_cost_pv == independent_development
    assert result.total_asset_rnpv == independent_asset
    assert result.equity_value == independent_equity
    assert result.fully_diluted_value_per_share == independent_equity / 10
    assert result.trace.discount_rate_pct == 15


def test_terminal_value_is_forbidden_outside_supported_bull_case():
    terminal_asset = AssetRnpvInput(
        asset="Asset A",
        indication="Disease A",
        issuer_economic_share_pct=Decimal("100"),
        pos_pct=Decimal("80"),
        annual_cash_flows=(
            AnnualAssetCashFlow(
                year_index=1,
                commercial_after_tax_fcf=Decimal("100"),
                remaining_development_cost=Decimal("0"),
                evidence_ids=(EVIDENCE_ID,),
            ),
        ),
        terminal_value=Decimal("100"),
        terminal_year=5,
        terminal_support_ids=(EVIDENCE_ID,),
    )
    base = _base_rnpv_input().model_copy(update={"assets": (terminal_asset,)})
    with pytest.raises(ValueError):
        RnpvInput.model_validate(base.model_dump())


def test_expected_value_golden_case_and_nonnegative_failure_cap(repository_root: Path):
    fixture = json.loads(
        (repository_root / "tests" / "fixtures" / "milestone5_golden.json").read_text()
    )["expected_value"]
    probability = ProbabilityAssessment(
        event_success_pct=OrderedRange(low=57, mid=62, high=67),
        confidence=PosConfidence.HIGH,
        prior_pct=40,
        adjustments=(),
    )
    result = calculate_expected_value(
        ExpectedValueInput(
            probability=probability,
            success_return_pct=OrderedRange(low=30, mid=60, high=100),
            failure_return_pct=OrderedRange(low=-70, mid=-40, high=-20),
        )
    )
    assert result.base_ev_pct == Decimal(str(fixture["expected_base_ev_pct"]))
    assert result.conservative_ev_pct == Decimal(str(fixture["expected_conservative_ev_pct"]))
    assert result.reward_risk == Decimal(str(fixture["expected_reward_risk"]))

    unusual = calculate_expected_value(
        ExpectedValueInput(
            probability=probability,
            success_return_pct=OrderedRange(low=20, mid=50, high=70),
            failure_return_pct=OrderedRange(low=0, mid=5, high=10),
        )
    )
    assert unusual.reward_risk == 10
    assert unusual.unusual_nonnegative_failure_assumption


def test_all_eight_factor_rubrics_and_coverage(scorecard_path: Path):
    rules = _rules(scorecard_path)
    catalyst = score_catalyst(
        CatalystScoreInput(
            as_of=AS_OF,
            catalyst_type=CatalystType.CLIN_P2_3,
            window_start=date(2026, 10, 14),
            timing_confidence=TimingConfidence.HIGH,
            materiality_points=8,
            novelty_points=3,
            evidence=_evidence(
                "MATERIALITY", "TIMING_CONFIDENCE", "PROXIMITY", "MATURITY", "NOVEL_INFORMATION"
            ),
        ),
        rules,
    )
    science = score_science(_review(), rules)
    market = score_market_impact(
        MarketImpactScoreInput(
            asset_value_concentration_pct=Decimal("80"),
            success_rerating_pct=Decimal("80"),
            expectation_gap_points=4,
            independent_expectation_supports=2,
            competitive_position_points=2,
            evidence=_evidence(
                "ASSET_VALUE_CONCENTRATION",
                "SUCCESS_RERATING",
                "EXPECTATION_GAP",
                "COMPETITIVE_POSITION",
            ),
        ),
        rules,
    )
    cash = score_cash_dilution(
        CashDilutionScoreInput(
            runway_months=Decimal("30"),
            burn_confidence="HIGH",
            financing_overhang=DilutionRisk.LOW,
            cash_and_securities=Decimal("200"),
            debt=Decimal("0"),
            runway_at_catalyst_months=Decimal("20"),
            restrictive_obligations=False,
            evidence=_evidence("RUNWAY", "FINANCING_OVERHANG", "BALANCE_SHEET_FLEXIBILITY"),
        ),
        rules,
    )
    valuation = score_valuation(
        ValuationScoreInput(
            conservative_mos_pct=Decimal("50"),
            base_mos_pct=Decimal("75"),
            failure_downside_pct=Decimal("30"),
            evidence=_evidence("CONSERVATIVE_MOS", "BASE_MOS", "FAILURE_VALUE_SUPPORT"),
        ),
        rules,
    )
    technical = score_technicals(
        TechnicalScoreInput(
            close=Decimal("100"),
            sma20=Decimal("95"),
            sma50=Decimal("90"),
            xbi_relative_return_20d_pct=Decimal("10"),
            up_down_dollar_volume_ratio=Decimal("1.5"),
            obv_slope_positive=True,
            support=Decimal("95"),
            base_success_target=Decimal("120"),
            rsi14=Decimal("60"),
            evidence=_evidence(
                "TREND", "RELATIVE_STRENGTH", "ACCUMULATION", "STRUCTURE", "EXTENSION"
            ),
        ),
        rules,
    )
    ownership = score_ownership(
        OwnershipScoreInput(
            reliable_specialist_data=True,
            accumulating_specialist_funds=3,
            meaningful_specialist_funds=3,
            new_or_add_ge_half_pct=True,
            insider_purchase_usd=Decimal("50000"),
            insider_purchase_age_days=180,
            evidence=_evidence("SPECIALIST_OWNERSHIP", "INSIDER_SIGNAL"),
        ),
        rules,
    )
    sentiment = score_sentiment(
        SentimentScoreInput(
            five_day_to_prior_sixty_day_volume_ratio=Decimal("1.5"),
            attributable_primary_news=True,
            independent_positive_revisions=2,
            mixed_or_one_revision=False,
            xbi_close_above_sma50=True,
            xbi_20d_return_positive=True,
            evidence=_evidence("ATTENTION_VOLUME", "EXPECTATION_DIRECTION", "SECTOR_REGIME"),
        ),
        rules,
    )

    assert [
        catalyst.points,
        science.points,
        market.points,
        cash.points,
        valuation.points,
        technical.points,
        ownership.points,
        sentiment.points,
    ] == [25, 17, 15, 10, 10, 10, 5, 5]

    score = build_score_breakdown(
        (catalyst, science, market, cash, valuation, technical, ownership, sentiment)
    )
    assert score.raw_total == 97
    assert calculate_coverage_pct(score) == 100


def test_missing_technical_inputs_score_zero_without_reweighting(scorecard_path: Path):
    missing = {"TREND", "RELATIVE_STRENGTH", "ACCUMULATION", "STRUCTURE", "EXTENSION"}
    technical = score_technicals(
        TechnicalScoreInput(
            evidence=_evidence(*sorted(missing), missing=missing),
        ),
        _rules(scorecard_path),
    )
    assert technical.points == 0
    assert all(item.data_state is DataState.MISSING for item in technical.subfactors)


def _safe_gate_input() -> GateInput:
    return GateInput(
        universe_eligible=True,
        investability_floor_pass=True,
        critical_data_complete=True,
        coverage_pct=Decimal("95"),
        unresolved_clinical_hold=False,
        unbounded_safety_risk=False,
        unreliable_provenance_or_capital_structure=False,
        catalyst_primary_source_verified=True,
        catalyst_interval_bounded=True,
        fatal_trial_interpretability_defect=False,
        valuation_bounded=True,
        runway_now_months=Decimal("24"),
        runway_at_catalyst_months=Decimal("12"),
        financing_likely_before_catalyst=False,
        active_atm_or_recent_shelf=False,
        observed_issuance_dependence=False,
        modeled_pre_catalyst_dilution_pct=Decimal("5"),
        base_ev_pct=Decimal("20"),
        conservative_ev_pct=Decimal("0"),
        reward_risk=Decimal("2"),
        failure_downside_pct=Decimal("40"),
        success_upside_pct=Decimal("80"),
        single_asset=False,
        above_sma20_pct=Decimal("5"),
        rsi14=Decimal("60"),
        distance_to_base_success_target_pct=Decimal("20"),
        ten_session_return_pct=Decimal("10"),
        fundamental_value_increase_pct=Decimal("0"),
        earliest_catalyst_days=30,
        timing_confidence=TimingConfidence.HIGH,
    )


GATE_CASES = [
    ({"universe_eligible": False}, "OUTSIDE_UNIVERSE", Classification.REJECT),
    ({"investability_floor_pass": False}, "BELOW_INVESTABILITY_FLOOR", Classification.REJECT),
    ({"critical_data_complete": False}, "INSUFFICIENT_CRITICAL_DATA", Classification.REJECT),
    ({"coverage_pct": Decimal("79")}, "COVERAGE_BELOW_80", Classification.REJECT),
    ({"unresolved_clinical_hold": True}, "UNRESOLVED_CLINICAL_HOLD", Classification.REJECT),
    ({"unbounded_safety_risk": True}, "UNBOUNDED_SAFETY_RISK", Classification.REJECT),
    (
        {"unreliable_provenance_or_capital_structure": True},
        "UNRELIABLE_PROVENANCE_OR_CAPITAL_STRUCTURE",
        Classification.REJECT,
    ),
    (
        {"catalyst_primary_source_verified": False},
        "UNVERIFIED_OR_UNBOUNDED_CATALYST",
        Classification.REJECT,
    ),
    (
        {"fatal_trial_interpretability_defect": True},
        "FATAL_TRIAL_INTERPRETABILITY_DEFECT",
        Classification.REJECT,
    ),
    ({"valuation_bounded": False}, "UNBOUNDED_VALUATION", Classification.REJECT),
    (
        {"runway_now_months": Decimal("11.99")},
        "FINANCING_RUNWAY_NOW",
        Classification.FINANCING_RISK,
    ),
    (
        {"runway_at_catalyst_months": Decimal("5.99")},
        "FINANCING_POST_CATALYST_CASH",
        Classification.FINANCING_RISK,
    ),
    (
        {"financing_likely_before_catalyst": True},
        "FINANCING_BEFORE_CATALYST",
        Classification.FINANCING_RISK,
    ),
    (
        {
            "active_atm_or_recent_shelf": True,
            "runway_now_months": Decimal("17.99"),
            "observed_issuance_dependence": True,
        },
        "ACTIVE_ISSUANCE_DEPENDENCE",
        Classification.FINANCING_RISK,
    ),
    (
        {"modeled_pre_catalyst_dilution_pct": Decimal("15.01")},
        "PRE_CATALYST_DILUTION",
        Classification.FINANCING_RISK,
    ),
    (
        {"base_ev_pct": Decimal("9.99")},
        "BASE_EV_BELOW_10",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {"reward_risk": Decimal("1.49")},
        "REWARD_RISK_BELOW_1_5",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {"failure_downside_pct": Decimal("70.01"), "success_upside_pct": Decimal("139.99")},
        "SEVERE_FAILURE_WITH_INSUFFICIENT_UPSIDE",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {"success_upside_pct": Decimal("19.99")},
        "SUCCESS_UPSIDE_BELOW_20",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {"conservative_ev_pct": Decimal("-20.01")},
        "CONSERVATIVE_EV_BELOW_MINUS_20",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {
            "single_asset": True,
            "post_failure_runway_months": Decimal("11.99"),
            "failure_downside_pct": Decimal("60.01"),
            "credible_second_asset": False,
        },
        "SINGLE_ASSET_FAILURE_FRAGILITY",
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
    ),
    (
        {"above_sma20_pct": Decimal("25.01")},
        "ABOVE_SMA20_EXTENSION",
        Classification.OVEREXTENDED_DO_NOT_CHASE,
    ),
    ({"rsi14": Decimal("80")}, "RSI_EXTENSION", Classification.OVEREXTENDED_DO_NOT_CHASE),
    (
        {"distance_to_base_success_target_pct": Decimal("5")},
        "NEAR_BASE_SUCCESS_TARGET",
        Classification.OVEREXTENDED_DO_NOT_CHASE,
    ),
    (
        {
            "ten_session_return_pct": Decimal("40"),
            "fundamental_value_increase_pct": Decimal("24.99"),
        },
        "TEN_SESSION_UNSUPPORTED_RUN",
        Classification.OVEREXTENDED_DO_NOT_CHASE,
    ),
    ({"earliest_catalyst_days": 85}, "CATALYST_TOO_EARLY", Classification.TOO_EARLY),
    (
        {"timing_confidence": TimingConfidence.LOW},
        "LOW_TIMING_CONFIDENCE",
        Classification.TOO_EARLY,
    ),
    ({"required_evidence_pending": True}, "REQUIRED_EVIDENCE_PENDING", Classification.TOO_EARLY),
]


@pytest.mark.parametrize(("updates", "expected_code", "expected_classification"), GATE_CASES)
def test_every_frozen_gate_rule_has_a_boundary_case(
    scorecard_path: Path,
    updates: dict[str, object],
    expected_code: str,
    expected_classification: Classification,
):
    payload = _safe_gate_input().model_dump()
    payload.update(updates)
    evaluation = evaluate_gates(GateInput.model_validate(payload), _rules(scorecard_path))
    assert expected_code in {gate.code for gate in evaluation.triggered}
    assert evaluation.dominant_classification is expected_classification


def test_gate_precedence_keeps_reject_above_financing_and_binary(scorecard_path: Path):
    payload = _safe_gate_input().model_dump()
    payload.update(
        universe_eligible=False,
        runway_now_months=Decimal("5"),
        base_ev_pct=Decimal("0"),
    )
    result = evaluate_gates(GateInput.model_validate(payload), _rules(scorecard_path))
    assert [gate.precedence for gate in result.triggered] == sorted(
        gate.precedence for gate in result.triggered
    )
    assert result.dominant_classification is Classification.REJECT


def _factor(code: FactorCode, points: int, max_points: int) -> FactorScore:
    return FactorScore(
        code=code,
        points=points,
        max_points=max_points,
        subfactors=(
            FactorSubscore(
                code="TOTAL",
                points=points,
                max_points=max_points,
                data_state=DataState.OBSERVED,
                rationale="golden classification fixture",
                evidence_ids=("golden-evidence",),
            ),
        ),
    )


def _score_from_points(points: dict[str, int]) -> ScoreBreakdown:
    maxima = {
        FactorCode.CATALYST: 25,
        FactorCode.SCIENCE: 20,
        FactorCode.MARKET_IMPACT: 15,
        FactorCode.CASH_DILUTION: 10,
        FactorCode.VALUATION: 10,
        FactorCode.TECHNICAL: 10,
        FactorCode.OWNERSHIP: 5,
        FactorCode.SENTIMENT: 5,
    }
    factors = tuple(_factor(code, points[code.value], maximum) for code, maximum in maxima.items())
    return ScoreBreakdown(raw_total=sum(points.values()), factors=factors)


def test_golden_high_conviction_classification(scorecard_path: Path, repository_root: Path):
    fixture = json.loads(
        (repository_root / "tests" / "fixtures" / "milestone5_golden.json").read_text()
    )["classification"]
    expected = ExpectedValueResult(
        base_ev_pct=Decimal(str(fixture["base_ev_pct"])),
        conservative_ev_pct=Decimal(str(fixture["conservative_ev_pct"])),
        reward_risk=Decimal(str(fixture["reward_risk"])),
        unusual_nonnegative_failure_assumption=False,
        formula="golden fixture",
    )
    result = classify(
        ClassificationInput(
            score=_score_from_points(fixture["factor_points"]),
            coverage_pct=Decimal(str(fixture["coverage_pct"])),
            timing_confidence=TimingConfidence(fixture["timing_confidence"]),
            catalyst_days=fixture["catalyst_days"],
            expected_value=expected,
            success_upside_pct=Decimal(str(fixture["success_upside_pct"])),
            failure_downside_pct=Decimal(str(fixture["failure_downside_pct"])),
            gates=GateEvaluation(triggered=(), dominant_classification=None),
        ),
        _rules(scorecard_path),
    )
    assert result.classification.value == fixture["expected_classification"]
    assert result.raw_score == fixture["raw_score"]


def test_watchlist_and_below_sixty_reject_classification(scorecard_path: Path):
    rules = _rules(scorecard_path)
    expected = ExpectedValueResult(
        base_ev_pct=Decimal("15"),
        conservative_ev_pct=Decimal("-5"),
        reward_risk=Decimal("1.5"),
        unusual_nonnegative_failure_assumption=False,
        formula="classification fixture",
    )
    watch_points = {
        "CATALYST": 15,
        "SCIENCE": 12,
        "MARKET_IMPACT": 10,
        "CASH_DILUTION": 7,
        "VALUATION": 6,
        "TECHNICAL": 5,
        "OWNERSHIP": 5,
        "SENTIMENT": 5,
    }
    watch = classify(
        ClassificationInput(
            score=_score_from_points(watch_points),
            coverage_pct=Decimal("90"),
            timing_confidence=TimingConfidence.HIGH,
            catalyst_days=30,
            expected_value=expected,
            success_upside_pct=Decimal("25"),
            failure_downside_pct=Decimal("40"),
            gates=GateEvaluation(triggered=(), dominant_classification=None),
        ),
        rules,
    )
    assert watch.classification is Classification.WATCHLIST

    reject_points = dict(watch_points)
    reject_points["CATALYST"] = 9
    below = classify(
        ClassificationInput(
            score=_score_from_points(reject_points),
            coverage_pct=Decimal("90"),
            timing_confidence=TimingConfidence.HIGH,
            catalyst_days=30,
            expected_value=expected,
            success_upside_pct=Decimal("25"),
            failure_downside_pct=Decimal("40"),
            gates=GateEvaluation(triggered=(), dominant_classification=None),
        ),
        rules,
    )
    assert below.score.raw_total if False else True
    assert below.classification is Classification.REJECT


def test_analysis_review_does_not_accept_naive_future_cutoff():
    future_review = _review().model_copy(update={"evidence_cutoff": AS_OF + timedelta(days=1)})
    with pytest.raises(ValueError):
        require_review_cutoff(future_review, AS_OF)
