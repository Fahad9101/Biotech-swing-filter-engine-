"""Deterministic BOE-1.0.0 rNPV and catalyst expected-value calculations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from boe.models import ContractModel, Money, OrderedRange, ProbabilityAssessment, Valuation

Scenario = Literal["CONSERVATIVE", "BASE", "BULL"]
SCENARIO_DISCOUNT_RATE_PCT: dict[str, Decimal] = {
    "CONSERVATIVE": Decimal("18"),
    "BASE": Decimal("15"),
    "BULL": Decimal("12"),
}


class AnnualAssetCashFlow(ContractModel):
    year_index: int = Field(ge=1)
    commercial_after_tax_fcf: Decimal
    remaining_development_cost: Decimal = Field(ge=0)
    development_cost_probability_pct: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class AssetRnpvInput(ContractModel):
    asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    issuer_economic_share_pct: Decimal = Field(ge=0, le=100)
    pos_pct: Decimal = Field(ge=0, le=100)
    annual_cash_flows: tuple[AnnualAssetCashFlow, ...] = Field(min_length=1)
    terminal_value: Decimal = Field(default=Decimal("0"), ge=0)
    terminal_year: int | None = Field(default=None, ge=1)
    terminal_support_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def terminal_fields_reconcile(self) -> Self:
        if self.terminal_value > 0:
            if self.terminal_year is None:
                raise ValueError("non-zero terminal value requires terminal_year")
            if not self.terminal_support_ids:
                raise ValueError("non-zero terminal value requires patent/exclusivity evidence")
        elif self.terminal_year is not None:
            raise ValueError("terminal_year must be absent when terminal value is zero")
        return self


class EquityBridgeInput(ContractModel):
    unrestricted_cash: Decimal = Field(ge=0)
    marketable_securities: Decimal = Field(ge=0)
    debt: Decimal = Field(ge=0)
    financing_obligations: Decimal = Field(ge=0)
    corporate_overhead_pv: Decimal = Field(ge=0)
    expected_dilution_cost: Decimal = Field(ge=0)
    non_operating_assets: Decimal = Field(default=Decimal("0"), ge=0)
    non_operating_liabilities: Decimal = Field(default=Decimal("0"), ge=0)
    fully_diluted_shares: Decimal = Field(gt=0)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class RnpvInput(ContractModel):
    issuer_id: str = Field(min_length=1)
    catalyst_version_id: UUID
    as_of: datetime
    scenario: Scenario
    assets: tuple[AssetRnpvInput, ...] = Field(min_length=1)
    bridge: EquityBridgeInput

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        _require_aware(self.as_of, "as_of")
        if self.scenario != "BULL" and any(asset.terminal_value > 0 for asset in self.assets):
            raise ValueError("terminal value is zero in conservative/base BOE-1.0.0 scenarios")
        return self


class AssetRnpvResult(ContractModel):
    asset: str
    indication: str
    commercial_pv: Decimal
    development_cost_pv: Decimal
    terminal_pv: Decimal
    rnpv: Decimal
    evidence_ids: tuple[UUID, ...]


class RnpvTrace(ContractModel):
    discount_rate_pct: Decimal
    formula: str
    equity_bridge_formula: str
    evidence_ids: tuple[UUID, ...]


class RnpvResult(ContractModel):
    issuer_id: str
    catalyst_version_id: UUID
    as_of: datetime
    scenario: Scenario
    asset_results: tuple[AssetRnpvResult, ...]
    total_asset_rnpv: Decimal
    equity_value: Decimal
    fully_diluted_value_per_share: Decimal
    trace: RnpvTrace


class ThreeScenarioRnpv(ContractModel):
    conservative: RnpvResult
    base: RnpvResult
    bull: RnpvResult

    @model_validator(mode="after")
    def scenario_identity(self) -> Self:
        if self.conservative.scenario != "CONSERVATIVE":
            raise ValueError("conservative result has wrong scenario")
        if self.base.scenario != "BASE":
            raise ValueError("base result has wrong scenario")
        if self.bull.scenario != "BULL":
            raise ValueError("bull result has wrong scenario")
        ids = {
            self.conservative.issuer_id,
            self.base.issuer_id,
            self.bull.issuer_id,
        }
        catalysts = {
            self.conservative.catalyst_version_id,
            self.base.catalyst_version_id,
            self.bull.catalyst_version_id,
        }
        if len(ids) != 1 or len(catalysts) != 1:
            raise ValueError("three-scenario results must describe one issuer/catalyst")
        return self


class ExpectedValueInput(ContractModel):
    probability: ProbabilityAssessment
    success_return_pct: OrderedRange
    failure_return_pct: OrderedRange

    @model_validator(mode="after")
    def positive_success_midpoint(self) -> Self:
        if self.success_return_pct.mid < 0:
            raise ValueError("success-return midpoint cannot be negative")
        return self


class ExpectedValueResult(ContractModel):
    base_ev_pct: Decimal
    conservative_ev_pct: Decimal
    reward_risk: Decimal = Field(ge=0, le=10)
    unusual_nonnegative_failure_assumption: bool
    formula: str


class FailurePriceRange(ContractModel):
    worst: Decimal = Field(ge=0)
    mid: Decimal = Field(ge=0)
    best: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.worst <= self.mid <= self.best:
            raise ValueError("failure prices must satisfy worst <= mid <= best")
        return self


def calculate_rnpv(input_: RnpvInput) -> RnpvResult:
    """Calculate one scenario using the frozen equity bridge and scenario discount rate."""

    discount_rate_pct = SCENARIO_DISCOUNT_RATE_PCT[input_.scenario]
    rate = discount_rate_pct / Decimal("100")
    asset_results: list[AssetRnpvResult] = []
    lineage: list[UUID] = []

    for asset in input_.assets:
        economic_share = asset.issuer_economic_share_pct / Decimal("100")
        pos = asset.pos_pct / Decimal("100")
        commercial_pv = Decimal("0")
        development_cost_pv = Decimal("0")
        asset_lineage: list[UUID] = []
        for cash_flow in asset.annual_cash_flows:
            discount = (Decimal("1") + rate) ** cash_flow.year_index
            commercial_pv += (
                cash_flow.commercial_after_tax_fcf * pos * economic_share / discount
            )
            development_cost_pv += (
                cash_flow.remaining_development_cost
                * (cash_flow.development_cost_probability_pct / Decimal("100"))
                * economic_share
                / discount
            )
            asset_lineage.extend(cash_flow.evidence_ids)
        terminal_pv = Decimal("0")
        if asset.terminal_value > 0:
            assert asset.terminal_year is not None
            terminal_discount = (Decimal("1") + rate) ** asset.terminal_year
            terminal_pv = asset.terminal_value * pos * economic_share / terminal_discount
            asset_lineage.extend(asset.terminal_support_ids)
        result = commercial_pv + terminal_pv - development_cost_pv
        unique_lineage = _unique_uuid(asset_lineage)
        lineage.extend(unique_lineage)
        asset_results.append(
            AssetRnpvResult(
                asset=asset.asset,
                indication=asset.indication,
                commercial_pv=commercial_pv,
                development_cost_pv=development_cost_pv,
                terminal_pv=terminal_pv,
                rnpv=result,
                evidence_ids=unique_lineage,
            )
        )

    total_asset_rnpv = sum((item.rnpv for item in asset_results), Decimal("0"))
    bridge = input_.bridge
    equity_value = (
        total_asset_rnpv
        + bridge.unrestricted_cash
        + bridge.marketable_securities
        - bridge.debt
        - bridge.financing_obligations
        - bridge.corporate_overhead_pv
        - bridge.expected_dilution_cost
        + bridge.non_operating_assets
        - bridge.non_operating_liabilities
    )
    per_share = equity_value / bridge.fully_diluted_shares
    lineage.extend(bridge.evidence_ids)
    return RnpvResult(
        issuer_id=input_.issuer_id,
        catalyst_version_id=input_.catalyst_version_id,
        as_of=input_.as_of,
        scenario=input_.scenario,
        asset_results=tuple(asset_results),
        total_asset_rnpv=total_asset_rnpv,
        equity_value=equity_value,
        fully_diluted_value_per_share=per_share,
        trace=RnpvTrace(
            discount_rate_pct=discount_rate_pct,
            formula=(
                "asset rNPV = PV(commercial after-tax FCF * event/program PoS * issuer "
                "economic share) + supported terminal PV - PV(remaining development costs)"
            ),
            equity_bridge_formula=(
                "equity = asset rNPV + cash + securities - debt - financing obligations - "
                "corporate overhead PV - expected dilution cost + non-operating assets - "
                "non-operating liabilities"
            ),
            evidence_ids=_unique_uuid(lineage),
        ),
    )


def calculate_three_scenario_rnpv(
    conservative: RnpvInput,
    base: RnpvInput,
    bull: RnpvInput,
) -> ThreeScenarioRnpv:
    return ThreeScenarioRnpv(
        conservative=calculate_rnpv(conservative),
        base=calculate_rnpv(base),
        bull=calculate_rnpv(bull),
    )


def calculate_expected_value(input_: ExpectedValueInput) -> ExpectedValueResult:
    probability = input_.probability.event_success_pct
    p_mid = Decimal(str(probability.mid)) / Decimal("100")
    p_low = Decimal(str(probability.low)) / Decimal("100")
    success_mid = Decimal(str(input_.success_return_pct.mid))
    success_low = Decimal(str(input_.success_return_pct.low))
    failure_mid = Decimal(str(input_.failure_return_pct.mid))
    failure_worst = Decimal(str(input_.failure_return_pct.low))

    base_ev = p_mid * success_mid + (Decimal("1") - p_mid) * failure_mid
    conservative_ev = p_low * success_low + (Decimal("1") - p_low) * failure_worst
    unusual = failure_mid >= 0
    if unusual:
        reward_risk = Decimal("10")
    elif failure_mid == 0:
        reward_risk = Decimal("10")
    else:
        reward_risk = success_mid / abs(failure_mid)
        reward_risk = min(reward_risk, Decimal("10"))
    return ExpectedValueResult(
        base_ev_pct=base_ev,
        conservative_ev_pct=conservative_ev,
        reward_risk=reward_risk,
        unusual_nonnegative_failure_assumption=unusual,
        formula=(
            "base_EV=p_mid*success_mid+(1-p_mid)*failure_mid; "
            "conservative_EV=p_low*success_low+(1-p_low)*failure_worst; "
            "reward_risk=success_mid/abs(failure_mid)"
        ),
    )


def build_valuation_assessment(
    scenarios: ThreeScenarioRnpv,
    *,
    current_price: Decimal,
    current_fully_diluted_shares: Decimal,
    failure_prices: FailurePriceRange,
    probability: ProbabilityAssessment,
) -> Valuation:
    if current_price <= 0 or current_fully_diluted_shares <= 0:
        raise ValueError("current price and fully diluted shares must be positive")
    current_fully_diluted_market_value = current_price * current_fully_diluted_shares
    scenario_results = (scenarios.conservative, scenarios.base, scenarios.bull)
    mos = [
        (item.equity_value / current_fully_diluted_market_value - Decimal("1"))
        * Decimal("100")
        for item in scenario_results
    ]
    success_returns = [
        (item.fully_diluted_value_per_share / current_price - Decimal("1")) * Decimal("100")
        for item in scenario_results
    ]
    failure_returns = [
        (value / current_price - Decimal("1")) * Decimal("100")
        for value in (failure_prices.worst, failure_prices.mid, failure_prices.best)
    ]
    expected = calculate_expected_value(
        ExpectedValueInput(
            probability=probability,
            success_return_pct=OrderedRange(
                low=float(success_returns[0]),
                mid=float(success_returns[1]),
                high=float(success_returns[2]),
            ),
            failure_return_pct=OrderedRange(
                low=float(failure_returns[0]),
                mid=float(failure_returns[1]),
                high=float(failure_returns[2]),
            ),
        )
    )
    return Valuation(
        conservative_rnpv=Money(value=scenarios.conservative.equity_value),
        base_rnpv=Money(value=scenarios.base.equity_value),
        bull_rnpv=Money(value=scenarios.bull.equity_value),
        margin_of_safety_pct=OrderedRange(
            low=float(mos[0]),
            mid=float(mos[1]),
            high=float(mos[2]),
        ),
        success_return_pct=OrderedRange(
            low=float(success_returns[0]),
            mid=float(success_returns[1]),
            high=float(success_returns[2]),
        ),
        failure_return_pct=OrderedRange(
            low=float(failure_returns[0]),
            mid=float(failure_returns[1]),
            high=float(failure_returns[2]),
        ),
        base_expected_return_pct=float(expected.base_ev_pct),
        conservative_expected_return_pct=float(expected.conservative_ev_pct),
        reward_risk=float(expected.reward_risk),
    )


def _unique_uuid(values: list[UUID]) -> tuple[UUID, ...]:
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
