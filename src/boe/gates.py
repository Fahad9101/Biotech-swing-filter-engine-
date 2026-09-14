"""Ordered BOE-1.0.0 hard-risk gates."""

from __future__ import annotations

from decimal import Decimal
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.enums import Classification, TimingConfidence
from boe.models import ContractModel, ScorecardContract, TriggeredGate


class GateInput(ContractModel):
    universe_eligible: bool
    investability_floor_pass: bool
    critical_data_complete: bool
    coverage_pct: Decimal = Field(ge=0, le=100)
    unresolved_clinical_hold: bool
    unbounded_safety_risk: bool
    unreliable_provenance_or_capital_structure: bool
    catalyst_primary_source_verified: bool
    catalyst_interval_bounded: bool
    fatal_trial_interpretability_defect: bool
    valuation_bounded: bool

    runway_now_months: Decimal = Field(ge=0)
    runway_at_catalyst_months: Decimal = Field(ge=0)
    financing_likely_before_catalyst: bool
    active_atm_or_recent_shelf: bool
    observed_issuance_dependence: bool
    modeled_pre_catalyst_dilution_pct: Decimal = Field(ge=0)

    base_ev_pct: Decimal
    conservative_ev_pct: Decimal
    reward_risk: Decimal = Field(ge=0)
    failure_downside_pct: Decimal = Field(ge=0)
    success_upside_pct: Decimal
    single_asset: bool
    post_failure_runway_months: Decimal | None = Field(default=None, ge=0)
    credible_second_asset: bool = False

    above_sma20_pct: Decimal | None = None
    rsi14: Decimal | None = Field(default=None, ge=0, le=100)
    distance_to_base_success_target_pct: Decimal | None = None
    ten_session_return_pct: Decimal | None = None
    fundamental_value_increase_pct: Decimal | None = None

    earliest_catalyst_days: int
    timing_confidence: TimingConfidence
    required_evidence_pending: bool = False
    evidence_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def unique_evidence(self) -> Self:
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("gate evidence IDs must be unique")
        return self


class GateResult(ContractModel):
    code: str = Field(min_length=1)
    classification: Classification
    precedence: int = Field(ge=1, le=5)
    reason: str = Field(min_length=1)
    observed_value: str = Field(min_length=1)
    threshold: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...]


class GateEvaluation(ContractModel):
    triggered: tuple[GateResult, ...]
    dominant_classification: Classification | None

    @model_validator(mode="after")
    def ordered_results(self) -> Self:
        precedence = [item.precedence for item in self.triggered]
        if precedence != sorted(precedence):
            raise ValueError("gate results must be sorted by precedence")
        if self.triggered:
            if self.dominant_classification is None:
                raise ValueError("triggered gates require a dominant classification")
            if self.dominant_classification is not self.triggered[0].classification:
                raise ValueError("dominant classification must match highest-precedence gate")
        elif self.dominant_classification is not None:
            raise ValueError("dominant classification without a triggered gate")
        return self

    def as_triggered_gates(self) -> tuple[TriggeredGate, ...]:
        """Collapse detailed results to one display gate per precedence/classification."""

        output: list[TriggeredGate] = []
        seen: set[tuple[Classification, int]] = set()
        for item in self.triggered:
            key = (item.classification, item.precedence)
            if key in seen:
                continue
            seen.add(key)
            reasons = [
                result.reason
                for result in self.triggered
                if result.classification is item.classification
                and result.precedence == item.precedence
            ]
            output.append(
                TriggeredGate(
                    code=item.classification.value,
                    reason="; ".join(reasons),
                    precedence=item.precedence,
                )
            )
        return tuple(output)


def evaluate_gates(input_: GateInput, rules: ScorecardContract) -> GateEvaluation:
    gate_rules = rules.gates
    results: list[GateResult] = []
    evidence = input_.evidence_ids

    reject_checks = (
        (
            not input_.universe_eligible,
            "OUTSIDE_UNIVERSE",
            "issuer is outside the BOE research universe",
            str(input_.universe_eligible),
            "universe_eligible=True",
        ),
        (
            not input_.investability_floor_pass,
            "BELOW_INVESTABILITY_FLOOR",
            "security fails the investability floor",
            str(input_.investability_floor_pass),
            "investability_floor_pass=True",
        ),
        (
            not input_.critical_data_complete,
            "INSUFFICIENT_CRITICAL_DATA",
            "one or more frozen critical fields are missing",
            str(input_.critical_data_complete),
            "critical_data_complete=True",
        ),
        (
            input_.coverage_pct < Decimal(str(rules.missing_data["coverage_reject_below_pct"])),
            "COVERAGE_BELOW_80",
            "data coverage is below the frozen reject threshold",
            str(input_.coverage_pct),
            f">={rules.missing_data['coverage_reject_below_pct']}%",
        ),
        (
            input_.unresolved_clinical_hold,
            "UNRESOLVED_CLINICAL_HOLD",
            "lead catalyst is affected by an unresolved clinical hold",
            str(input_.unresolved_clinical_hold),
            "False",
        ),
        (
            input_.unbounded_safety_risk,
            "UNBOUNDED_SAFETY_RISK",
            "major unresolved safety risk makes the outcome unbounded",
            str(input_.unbounded_safety_risk),
            "False",
        ),
        (
            input_.unreliable_provenance_or_capital_structure,
            "UNRELIABLE_PROVENANCE_OR_CAPITAL_STRUCTURE",
            "provenance or fully diluted capital structure cannot be bounded",
            str(input_.unreliable_provenance_or_capital_structure),
            "False",
        ),
        (
            not input_.catalyst_primary_source_verified or not input_.catalyst_interval_bounded,
            "UNVERIFIED_OR_UNBOUNDED_CATALYST",
            "catalyst lacks primary-source verification or a bounded interval",
            (
                f"primary={input_.catalyst_primary_source_verified},"
                f"bounded={input_.catalyst_interval_bounded}"
            ),
            "primary=True,bounded=True",
        ),
        (
            input_.fatal_trial_interpretability_defect,
            "FATAL_TRIAL_INTERPRETABILITY_DEFECT",
            "trial design cannot answer the stated catalyst thesis",
            str(input_.fatal_trial_interpretability_defect),
            "False",
        ),
        (
            not input_.valuation_bounded,
            "UNBOUNDED_VALUATION",
            "conservative and base valuation cannot both be bounded",
            str(input_.valuation_bounded),
            "valuation_bounded=True",
        ),
    )
    for active, code, reason, observed, threshold in reject_checks:
        if active:
            results.append(
                _result(
                    code,
                    Classification.REJECT,
                    1,
                    reason,
                    observed,
                    threshold,
                    evidence,
                )
            )

    financing = gate_rules["financing"]
    runway_now_threshold = Decimal(str(financing["runway_now_below_months"]))
    runway_event_threshold = Decimal(str(financing["runway_at_latest_catalyst_below_months"]))
    dependence_threshold = Decimal(str(financing["active_issuance_dependency_runway_below_months"]))
    dilution_threshold = Decimal(str(financing["modeled_pre_catalyst_dilution_above_pct"]))
    financing_checks = (
        (
            input_.runway_now_months < runway_now_threshold,
            "FINANCING_RUNWAY_NOW",
            "runway at analysis date is below 12 months",
            str(input_.runway_now_months),
            f">={runway_now_threshold} months",
        ),
        (
            input_.runway_at_catalyst_months < runway_event_threshold,
            "FINANCING_POST_CATALYST_CASH",
            "cash is projected to run out within six months after the latest catalyst",
            str(input_.runway_at_catalyst_months),
            f">={runway_event_threshold} months after catalyst",
        ),
        (
            input_.financing_likely_before_catalyst,
            "FINANCING_BEFORE_CATALYST",
            "management-guided or mathematically necessary financing is likely pre-catalyst",
            str(input_.financing_likely_before_catalyst),
            "False",
        ),
        (
            input_.active_atm_or_recent_shelf
            and input_.runway_now_months < dependence_threshold
            and input_.observed_issuance_dependence,
            "ACTIVE_ISSUANCE_DEPENDENCE",
            "active ATM/recent shelf combines with short runway and observed issuance dependence",
            str(input_.runway_now_months),
            f">={dependence_threshold} months or no issuance dependence",
        ),
        (
            input_.modeled_pre_catalyst_dilution_pct > dilution_threshold,
            "PRE_CATALYST_DILUTION",
            "modeled pre-catalyst dilution exceeds the frozen limit",
            str(input_.modeled_pre_catalyst_dilution_pct),
            f"<={dilution_threshold}%",
        ),
    )
    _append_checks(
        results,
        financing_checks,
        Classification.FINANCING_RISK,
        2,
        evidence,
    )

    binary = gate_rules["binary"]
    binary_checks = (
        (
            input_.base_ev_pct < Decimal(str(binary["base_ev_below_pct"])),
            "BASE_EV_BELOW_10",
            "base expected value is below 10%",
            str(input_.base_ev_pct),
            f">={binary['base_ev_below_pct']}%",
        ),
        (
            input_.reward_risk < Decimal(str(binary["reward_risk_below"])),
            "REWARD_RISK_BELOW_1_5",
            "reward/risk is below 1.5",
            str(input_.reward_risk),
            f">={binary['reward_risk_below']}",
        ),
        (
            input_.failure_downside_pct > Decimal(str(binary["failure_downside_above_pct"]))
            and input_.success_upside_pct < Decimal(str(binary["paired_success_upside_below_pct"])),
            "SEVERE_FAILURE_WITH_INSUFFICIENT_UPSIDE",
            "failure downside is >70% while success upside is <140%",
            f"down={input_.failure_downside_pct},up={input_.success_upside_pct}",
            (
                f"down<={binary['failure_downside_above_pct']}% or "
                f"up>={binary['paired_success_upside_below_pct']}%"
            ),
        ),
        (
            input_.success_upside_pct < Decimal(str(binary["success_upside_below_pct"])),
            "SUCCESS_UPSIDE_BELOW_20",
            "success upside is below the minimum investable BOE swing threshold",
            str(input_.success_upside_pct),
            f">={binary['success_upside_below_pct']}%",
        ),
        (
            input_.conservative_ev_pct < Decimal(str(binary["conservative_ev_below_pct"])),
            "CONSERVATIVE_EV_BELOW_MINUS_20",
            "conservative expected value is below -20%",
            str(input_.conservative_ev_pct),
            f">={binary['conservative_ev_below_pct']}%",
        ),
        (
            _single_asset_failure_gate(input_, binary),
            "SINGLE_ASSET_FAILURE_FRAGILITY",
            (
                "single-asset failure leaves <12 months cash with no credible second asset "
                "and >60% downside"
            ),
            (
                f"runway={input_.post_failure_runway_months},"
                f"downside={input_.failure_downside_pct},"
                f"second_asset={input_.credible_second_asset}"
            ),
            "post-failure runway >=12m or downside <=60% or credible second asset",
        ),
    )
    _append_checks(
        results,
        binary_checks,
        Classification.BINARY_RISK_UNFAVORABLE_ASYMMETRY,
        3,
        evidence,
    )

    overextended = gate_rules["overextended"]
    overextended_checks = (
        (
            input_.above_sma20_pct is not None
            and input_.above_sma20_pct > Decimal(str(overextended["above_sma20_pct"])),
            "ABOVE_SMA20_EXTENSION",
            "close is more than 25% above SMA20",
            str(input_.above_sma20_pct),
            f"<={overextended['above_sma20_pct']}%",
        ),
        (
            input_.rsi14 is not None and input_.rsi14 >= Decimal(str(overextended["rsi14_min"])),
            "RSI_EXTENSION",
            "RSI14 is at or above 80",
            str(input_.rsi14),
            f"<{overextended['rsi14_min']}",
        ),
        (
            input_.distance_to_base_success_target_pct is not None
            and input_.distance_to_base_success_target_pct
            <= Decimal(str(overextended["within_base_success_target_pct"])),
            "NEAR_BASE_SUCCESS_TARGET",
            "close is within 5% of the base success target",
            str(input_.distance_to_base_success_target_pct),
            f">{overextended['within_base_success_target_pct']}% below target",
        ),
        (
            _ten_session_extension_gate(input_, overextended),
            "TEN_SESSION_UNSUPPORTED_RUN",
            "price rose at least 40% in ten sessions without a >=25% fundamental value increase",
            (
                f"return={input_.ten_session_return_pct},"
                f"value_change={input_.fundamental_value_increase_pct}"
            ),
            (
                f"return<{overextended['ten_session_return_min_pct']}% or value increase "
                f">={overextended['required_fundamental_value_increase_pct']}%"
            ),
        ),
    )
    _append_checks(
        results,
        overextended_checks,
        Classification.OVEREXTENDED_DO_NOT_CHASE,
        4,
        evidence,
    )

    too_early = gate_rules["too_early"]
    too_early_checks = (
        (
            input_.earliest_catalyst_days > int(too_early["earliest_catalyst_days_above"]),
            "CATALYST_TOO_EARLY",
            "earliest plausible catalyst date is more than 84 days away",
            str(input_.earliest_catalyst_days),
            f"<={too_early['earliest_catalyst_days_above']} days",
        ),
        (
            input_.timing_confidence.value == str(too_early["timing_confidence"]),
            "LOW_TIMING_CONFIDENCE",
            "timing confidence is Low",
            input_.timing_confidence.value,
            "MODERATE or HIGH",
        ),
        (
            input_.required_evidence_pending,
            "REQUIRED_EVIDENCE_PENDING",
            "required evidence is pending and cannot be sourced before ranking",
            str(input_.required_evidence_pending),
            "False",
        ),
    )
    _append_checks(
        results,
        too_early_checks,
        Classification.TOO_EARLY,
        5,
        evidence,
    )

    results.sort(key=lambda item: (item.precedence, item.code))
    dominant = results[0].classification if results else None
    return GateEvaluation(triggered=tuple(results), dominant_classification=dominant)


def _single_asset_failure_gate(input_: GateInput, rules: dict[str, object]) -> bool:
    if not input_.single_asset or input_.credible_second_asset:
        return False
    if input_.post_failure_runway_months is None:
        return False
    return input_.post_failure_runway_months < Decimal(
        str(rules["single_asset_post_failure_runway_below_months"])
    ) and input_.failure_downside_pct > Decimal(
        str(rules["single_asset_failure_downside_above_pct"])
    )


def _ten_session_extension_gate(input_: GateInput, rules: dict[str, object]) -> bool:
    if input_.ten_session_return_pct is None:
        return False
    if input_.ten_session_return_pct < Decimal(str(rules["ten_session_return_min_pct"])):
        return False
    if input_.fundamental_value_increase_pct is None:
        return True
    return input_.fundamental_value_increase_pct < Decimal(
        str(rules["required_fundamental_value_increase_pct"])
    )


def _append_checks(
    results: list[GateResult],
    checks: tuple[tuple[bool, str, str, str, str], ...],
    classification: Classification,
    precedence: int,
    evidence_ids: tuple[UUID, ...],
) -> None:
    for active, code, reason, observed, threshold in checks:
        if active:
            results.append(
                _result(
                    code,
                    classification,
                    precedence,
                    reason,
                    observed,
                    threshold,
                    evidence_ids,
                )
            )


def _result(
    code: str,
    classification: Classification,
    precedence: int,
    reason: str,
    observed: str,
    threshold: str,
    evidence_ids: tuple[UUID, ...],
) -> GateResult:
    return GateResult(
        code=code,
        classification=classification,
        precedence=precedence,
        reason=reason,
        observed_value=observed,
        threshold=threshold,
        evidence_ids=evidence_ids,
    )
