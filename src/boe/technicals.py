"""Milestone 6 deterministic technical calculations from validated market series."""

from __future__ import annotations

import statistics
from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import Field, model_validator

from boe.enums import DataState
from boe.market import MarketBar, MarketSeries, point_in_time_series, series_manifest_sha256
from boe.models import ContractModel, FactorScore, ScorecardContract
from boe.scoring import SubfactorEvidence, TechnicalScoreInput, score_technicals

TECHNICAL_CALCULATION_VERSION = "BOE-M6-TECHNICAL-1"
MIN_REQUIRED_SESSIONS = 60


class PivotSupportEvidence(ContractModel):
    level: Decimal = Field(gt=0)
    tested_sessions: tuple[date, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def distinct_tests(self) -> Self:
        if len(set(self.tested_sessions)) != len(self.tested_sessions):
            raise ValueError("pivot support test sessions must be distinct")
        return self


class TechnicalCalculationTrace(ContractModel):
    calculation_version: str = TECHNICAL_CALCULATION_VERSION
    security_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    benchmark_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    common_sessions: int = Field(ge=MIN_REQUIRED_SESSIONS)
    indicator_window_sessions: int = MIN_REQUIRED_SESSIONS
    latest_complete_session: date
    expected_latest_session: date
    stale: bool
    formulas: tuple[str, ...] = Field(min_length=1)
    notes: tuple[str, ...]


class TechnicalSnapshot(ContractModel):
    symbol: str
    benchmark_symbol: str
    as_of: datetime
    session_date: date
    close: Decimal = Field(gt=0)
    sma20: Decimal = Field(gt=0)
    sma50: Decimal = Field(gt=0)
    rsi14: Decimal = Field(ge=0, le=100)
    atr14: Decimal = Field(gt=0)
    security_return_20d_pct: Decimal
    benchmark_return_20d_pct: Decimal
    xbi_relative_return_20d_pct: Decimal
    up_down_dollar_volume_ratio: Decimal = Field(ge=0)
    obv_slope: Decimal
    support: Decimal | None = Field(default=None, gt=0)
    resistance: Decimal | None = Field(default=None, gt=0)
    stale: bool
    calculation_trace: TechnicalCalculationTrace

    @model_validator(mode="after")
    def reconcile(self) -> Self:
        if self.calculation_trace.latest_complete_session != self.session_date:
            raise ValueError("technical trace session differs from snapshot")
        if self.calculation_trace.stale != self.stale:
            raise ValueError("technical stale state differs from trace")
        return self


class InvestabilityMarketInputs(ContractModel):
    adjusted_close: Decimal = Field(gt=0)
    median_dollar_volume_20d: Decimal = Field(ge=0)
    valid_trading_sessions: int = Field(ge=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    as_of_session: date
    stale: bool


def build_technical_snapshot(
    security: MarketSeries,
    benchmark: MarketSeries,
    *,
    as_of: datetime,
    expected_latest_session: date,
    pivot_support: PivotSupportEvidence | None = None,
) -> TechnicalSnapshot:
    _require_aware(as_of, "as_of")
    if expected_latest_session > as_of.date():
        raise ValueError("expected latest session cannot be after analysis date")
    if security.symbol == benchmark.symbol:
        raise ValueError("security and benchmark symbols must differ")
    security = point_in_time_series(security, as_of.date())
    benchmark = point_in_time_series(benchmark, as_of.date())
    common = _aligned_common_bars(security, benchmark, as_of.date())
    if len(common) < MIN_REQUIRED_SESSIONS:
        raise ValueError("technical engine requires at least 60 aligned complete sessions")
    sec_bars = tuple(pair[0] for pair in common)
    bench_bars = tuple(pair[1] for pair in common)
    latest_session = sec_bars[-1].session_date
    stale = latest_session < expected_latest_session

    closes = tuple(bar.adjusted_close for bar in sec_bars)
    bench_closes = tuple(bar.adjusted_close for bar in bench_bars)
    sma20 = _mean(closes[-20:])
    sma50 = _mean(closes[-50:])
    security_return = _return_pct(closes[-21], closes[-1])
    benchmark_return = _return_pct(bench_closes[-21], bench_closes[-1])
    relative_return = security_return - benchmark_return
    rsi14 = _wilder_rsi(closes, period=14)
    atr14 = _wilder_atr(sec_bars, period=14)
    ratio, ratio_note = _up_down_dollar_volume_ratio(sec_bars[-21:])
    obv_slope = _obv_slope(sec_bars[-21:])
    support = _validated_support(
        sec_bars=sec_bars,
        close=closes[-1],
        sma20=sma20,
        sma50=sma50,
        pivot=pivot_support,
    )
    notes: list[str] = []
    if ratio_note:
        notes.append(ratio_note)
    if pivot_support is None:
        notes.append(
            "No automatic pivot detector is used because BOE-1.0.0 freezes no pivot tolerance; "
            "only SMA20/SMA50 and explicitly reviewed pivot evidence are eligible support."
        )
    trace = TechnicalCalculationTrace(
        security_manifest_sha256=series_manifest_sha256(security),
        benchmark_manifest_sha256=series_manifest_sha256(benchmark),
        common_sessions=len(common),
        latest_complete_session=latest_session,
        expected_latest_session=expected_latest_session,
        stale=stale,
        formulas=(
            "SMA20/SMA50 = arithmetic mean of adjusted closes.",
            "20-session total return = close[t]/close[t-20]-1.",
            "XBI relative return = security 20-session return minus XBI 20-session return.",
            "RSI14 = Wilder smoothing of gains/losses.",
            "ATR14 = Wilder smoothing of true range.",
            "Up/down dollar-volume ratio = sum(close*volume on up sessions) / down sessions.",
            "OBV slope = OLS slope of 20-session cumulative OBV.",
            "Validated support = highest eligible SMA20, SMA50, or explicitly validated pivot below close.",
        ),
        notes=tuple(notes),
    )
    return TechnicalSnapshot(
        symbol=security.symbol,
        benchmark_symbol=benchmark.symbol,
        as_of=as_of,
        session_date=latest_session,
        close=closes[-1],
        sma20=sma20,
        sma50=sma50,
        rsi14=rsi14,
        atr14=atr14,
        security_return_20d_pct=security_return,
        benchmark_return_20d_pct=benchmark_return,
        xbi_relative_return_20d_pct=relative_return,
        up_down_dollar_volume_ratio=ratio,
        obv_slope=obv_slope,
        support=support,
        resistance=None,
        stale=stale,
        calculation_trace=trace,
    )


def technical_score_input(
    snapshot: TechnicalSnapshot,
    *,
    base_success_target: Decimal | None,
    evidence: dict[str, SubfactorEvidence],
) -> TechnicalScoreInput:
    if snapshot.stale:
        raise ValueError("stale technical snapshot cannot drive BOE technical scoring")
    return TechnicalScoreInput(
        close=snapshot.close,
        sma20=snapshot.sma20,
        sma50=snapshot.sma50,
        xbi_relative_return_20d_pct=snapshot.xbi_relative_return_20d_pct,
        up_down_dollar_volume_ratio=snapshot.up_down_dollar_volume_ratio,
        obv_slope_positive=snapshot.obv_slope > 0,
        support=snapshot.support,
        base_success_target=base_success_target,
        rsi14=snapshot.rsi14,
        evidence=evidence,
    )


def score_snapshot_technicals(
    snapshot: TechnicalSnapshot,
    *,
    base_success_target: Decimal | None,
    evidence: dict[str, SubfactorEvidence],
    rules: ScorecardContract,
) -> FactorScore:
    return score_technicals(
        technical_score_input(
            snapshot,
            base_success_target=base_success_target,
            evidence=evidence,
        ),
        rules,
    )


def investability_market_inputs(
    series: MarketSeries,
    *,
    as_of_session: date,
    expected_latest_session: date,
    shares_outstanding: Decimal | None = None,
) -> InvestabilityMarketInputs:
    bars = tuple(bar for bar in series.bars if bar.session_date <= as_of_session)
    if not bars:
        raise ValueError("no market bars exist at or before investability cutoff")
    latest = bars[-1]
    stale = latest.session_date < expected_latest_session
    if len(bars) < 20:
        raise ValueError("median dollar-volume input requires at least 20 sessions")
    dollar_volumes = sorted(
        latest_bar.adjusted_close * Decimal(latest_bar.volume) for latest_bar in bars[-20:]
    )
    median = _median_decimal(dollar_volumes)
    market_cap = (
        latest.adjusted_close * shares_outstanding if shares_outstanding is not None else None
    )
    return InvestabilityMarketInputs(
        adjusted_close=latest.adjusted_close,
        median_dollar_volume_20d=median,
        valid_trading_sessions=len(bars),
        market_cap=market_cap,
        as_of_session=latest.session_date,
        stale=stale,
    )


def market_capitalization(close: Decimal, shares_outstanding: Decimal) -> Decimal:
    if close <= 0 or shares_outstanding <= 0:
        raise ValueError("market capitalization requires positive close and shares")
    return close * shares_outstanding


def technical_evidence(
    evidence_id,
    *,
    rationale_prefix: str = "Milestone 6 deterministic market calculation",
) -> dict[str, SubfactorEvidence]:
    return {
        code: SubfactorEvidence(
            data_state=DataState.DERIVED,
            rationale=f"{rationale_prefix}: {code}",
            evidence_ids=(evidence_id,),
        )
        for code in ("TREND", "RELATIVE_STRENGTH", "ACCUMULATION", "STRUCTURE", "EXTENSION")
    }


def _aligned_common_bars(
    security: MarketSeries,
    benchmark: MarketSeries,
    cutoff: date,
) -> tuple[tuple[MarketBar, MarketBar], ...]:
    security_by_date = {
        bar.session_date: bar for bar in security.bars if bar.session_date <= cutoff
    }
    benchmark_by_date = {
        bar.session_date: bar for bar in benchmark.bars if bar.session_date <= cutoff
    }
    common_dates = sorted(set(security_by_date) & set(benchmark_by_date))
    return tuple((security_by_date[item], benchmark_by_date[item]) for item in common_dates)


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    if not values:
        raise ValueError("cannot calculate mean of empty sequence")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _return_pct(start: Decimal, end: Decimal) -> Decimal:
    if start <= 0:
        raise ValueError("return denominator must be positive")
    return (end / start - Decimal("1")) * Decimal("100")


def _wilder_rsi(closes: tuple[Decimal, ...], period: int) -> Decimal:
    if len(closes) < period + 1:
        raise ValueError("insufficient closes for RSI")
    changes = tuple(closes[index] - closes[index - 1] for index in range(1, len(closes)))
    gains = tuple(max(change, Decimal("0")) for change in changes)
    losses = tuple(max(-change, Decimal("0")) for change in changes)
    avg_gain = _mean(gains[:period])
    avg_loss = _mean(losses[:period])
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * Decimal(period - 1) + gain) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + loss) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100") if avg_gain > 0 else Decimal("50")
    rs = avg_gain / avg_loss
    return Decimal("100") - Decimal("100") / (Decimal("1") + rs)


def _wilder_atr(bars: tuple[MarketBar, ...], period: int) -> Decimal:
    if len(bars) < period + 1:
        raise ValueError("insufficient bars for ATR")
    true_ranges: list[Decimal] = []
    for index in range(1, len(bars)):
        bar = bars[index]
        previous_close = bars[index - 1].adjusted_close
        true_ranges.append(
            max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
    atr = _mean(tuple(true_ranges[:period]))
    for true_range in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + true_range) / Decimal(period)
    return atr


def _up_down_dollar_volume_ratio(
    bars: tuple[MarketBar, ...],
) -> tuple[Decimal, str | None]:
    if len(bars) < 21:
        raise ValueError("up/down dollar-volume ratio requires 20 return sessions")
    up = Decimal("0")
    down = Decimal("0")
    for previous, current in zip(bars, bars[1:]):
        dollar_volume = current.adjusted_close * Decimal(current.volume)
        if current.adjusted_close > previous.adjusted_close:
            up += dollar_volume
        elif current.adjusted_close < previous.adjusted_close:
            down += dollar_volume
    if down == 0:
        if up == 0:
            return Decimal("0"), "No directional sessions in 20-session accumulation window."
        return Decimal("1000000000"), (
            "No down-session dollar volume; finite sentinel 1e9 represents an effectively "
            "unbounded ratio and does not alter the frozen >=1.5 threshold."
        )
    return up / down, None


def _obv_slope(bars: tuple[MarketBar, ...]) -> Decimal:
    if len(bars) < 21:
        raise ValueError("OBV slope requires 20 return sessions")
    obv = Decimal("0")
    values: list[Decimal] = []
    for previous, current in zip(bars, bars[1:]):
        if current.adjusted_close > previous.adjusted_close:
            obv += Decimal(current.volume)
        elif current.adjusted_close < previous.adjusted_close:
            obv -= Decimal(current.volume)
        values.append(obv)
    x_values = tuple(Decimal(index) for index in range(len(values)))
    x_mean = _mean(x_values)
    y_values = tuple(values)
    y_mean = _mean(y_values)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean)
        for x_value, y_value in zip(x_values, y_values, strict=True)
    )
    denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator


def _validated_support(
    *,
    sec_bars: tuple[MarketBar, ...],
    close: Decimal,
    sma20: Decimal,
    sma50: Decimal,
    pivot: PivotSupportEvidence | None,
) -> Decimal | None:
    candidates = [level for level in (sma20, sma50) if level < close]
    if pivot is not None:
        recent = {bar.session_date: bar for bar in sec_bars[-60:]}
        if any(session not in recent for session in pivot.tested_sessions):
            raise ValueError("pivot test session falls outside the prior 60 aligned sessions")
        if any(
            not (recent[session].low <= pivot.level <= recent[session].high)
            for session in pivot.tested_sessions
        ):
            raise ValueError("pivot level was not traded within each declared test session")
        if pivot.level >= close:
            raise ValueError("validated pivot support must be below current close")
        candidates.append(pivot.level)
    return max(candidates) if candidates else None


def _median_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        raise ValueError("cannot calculate median of empty values")
    return Decimal(str(statistics.median(values)))


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
