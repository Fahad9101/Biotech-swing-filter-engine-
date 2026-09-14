"""Milestone 7 historical-validation contracts and deterministic statistics.

This module validates the frozen BOE-1.0.0 engine. It does not alter investment
rules, scores, thresholds, gates, classifications, PoS, valuation, or technical
logic.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Self
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from boe.enums import CatalystType, Classification
from boe.models import ContractModel

VALIDATION_SEED = 100100
MIN_COHORT_SIZE = 120
STRATUM_MINIMUMS = {
    "PHASE_2_POC": 30,
    "PHASE_3_PIVOTAL": 30,
    "REGULATORY": 30,
    "EARLY_CLINICAL": 15,
    "CONFERENCE_OTHER": 15,
}
RULES_VERSION = "BOE-1.0.0"


class EventStratum(StrEnum):
    PHASE_2_POC = "PHASE_2_POC"
    PHASE_3_PIVOTAL = "PHASE_3_PIVOTAL"
    REGULATORY = "REGULATORY"
    EARLY_CLINICAL = "EARLY_CLINICAL"
    CONFERENCE_OTHER = "CONFERENCE_OTHER"


class ValidationPeriod(StrEnum):
    DIAGNOSTIC_2018_2022 = "DIAGNOSTIC_2018_2022"
    TEMPORAL_2023_2024 = "TEMPORAL_2023_2024"
    HOLDOUT_2025 = "HOLDOUT_2025"


class SnapshotLabel(StrEnum):
    T_MINUS_60 = "T_MINUS_60"
    T_MINUS_30 = "T_MINUS_30"
    T_MINUS_10 = "T_MINUS_10"
    LAST_COMPLETE_SESSION = "LAST_COMPLETE_SESSION"


class FailureCategory(StrEnum):
    SOURCE_DATA = "SOURCE_DATA_FAILURE"
    CATALYST_TIMING = "CATALYST_TIMING_FAILURE"
    SCIENCE = "SCIENTIFIC_REASONING_FAILURE"
    POS = "POS_CALIBRATION_FAILURE"
    VALUATION = "VALUATION_EXPECTATION_FAILURE"
    DILUTION = "DILUTION_CAPITAL_STRUCTURE_FAILURE"
    TECHNICAL = "TECHNICAL_ENTRY_FAILURE"
    EXTERNAL = "UNMODELED_EXTERNAL_EVENT"
    GATE_INTERACTION = "CLASSIFICATION_GATE_INTERACTION"
    UNKNOWABLE = "INFORMATION_UNKNOWABLE_PRE_EVENT"


class Recommendation(StrEnum):
    PROCEED = "PROCEED TO LIVE-SHADOW VALIDATION"
    REPAIR = "REPAIR DATA PIPELINE AND REPEAT M7"
    RECALIBRATE = "PROPOSE RECALIBRATION IN A NEW BOE VERSION"
    STOP = "STOP"


class HistoricalEvent(ContractModel):
    event_id: str = Field(min_length=1)
    issuer_id: str = Field(min_length=1)
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]{0,14}$")
    cik: str = Field(pattern=r"^[0-9]{10}$")
    company: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    indication: str = Field(min_length=1)
    catalyst_type: CatalystType
    clinical_phase: str = Field(min_length=1)
    primary_stratum: EventStratum
    event_at: datetime
    source_ids: tuple[str, ...] = Field(min_length=1)
    included: bool = True
    exclusion_reason: str | None = None
    negative_event: bool
    financing_t_minus_90_to_t_plus_30: bool
    single_asset_issuer: bool

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        _require_aware(self.event_at, "event_at")
        if not self.included and not self.exclusion_reason:
            raise ValueError("excluded event requires exclusion_reason")
        if self.included and self.exclusion_reason is not None:
            raise ValueError("included event cannot carry exclusion_reason")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("event source_ids must be unique")
        if not 2018 <= self.event_at.year <= 2025:
            raise ValueError("historical validation event must be in 2018..2025")
        return self


class CohortManifest(ContractModel):
    seed: int = VALIDATION_SEED
    rules_version: str = RULES_VERSION
    frozen_at: datetime
    events: tuple[HistoricalEvent, ...] = Field(min_length=MIN_COHORT_SIZE)
    registry_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cohort_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        _require_aware(self.frozen_at, "frozen_at")
        validate_cohort(self.events)
        calculated = cohort_sha256(self.events, self.seed)
        if calculated != self.cohort_sha256:
            raise ValueError("cohort_sha256 does not match cohort contents")
        return self


class HistoricalDecisionLock(ContractModel):
    event_id: str
    snapshot_label: SnapshotLabel
    snapshot_cutoff: datetime
    locked_at: datetime
    code_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    rules_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_score: int = Field(ge=0, le=100)
    coverage_pct: float = Field(ge=0, le=100)
    classification: Classification
    gate_codes: tuple[str, ...]
    pos_low_pct: float = Field(ge=0, le=100)
    pos_mid_pct: float = Field(ge=0, le=100)
    pos_high_pct: float = Field(ge=0, le=100)
    conservative_equity_value: Decimal
    base_equity_value: Decimal
    bull_equity_value: Decimal
    base_ev_pct: Decimal
    evidence_ids: tuple[str, ...]
    outcome_revealed_at_lock: bool = False

    @model_validator(mode="after")
    def validate_lock(self) -> Self:
        _require_aware(self.snapshot_cutoff, "snapshot_cutoff")
        _require_aware(self.locked_at, "locked_at")
        if self.locked_at < self.snapshot_cutoff:
            raise ValueError("decision cannot be locked before its evidence cutoff")
        if self.outcome_revealed_at_lock:
            raise ValueError("historical decision lock cannot contain revealed outcome")
        if not self.pos_low_pct <= self.pos_mid_pct <= self.pos_high_pct:
            raise ValueError("PoS range must be ordered")
        return self


class PriceObservation(ContractModel):
    session_date: date
    adjusted_close: Decimal = Field(gt=0)


class HistoricalOutcome(ContractModel):
    event_id: str
    t0_session: date
    t_minus_1_close: Decimal = Field(gt=0)
    return_t1_pct: Decimal
    return_t5_pct: Decimal
    return_t20_pct: Decimal
    xbi_relative_t1_pct: Decimal
    xbi_relative_t5_pct: Decimal
    xbi_relative_t20_pct: Decimal
    mfe_t20_pct: Decimal
    mae_t20_pct: Decimal
    severe_loss: bool
    swing_success: bool
    financing_through_t30: bool
    fully_diluted_share_change_pct: Decimal | None = None
    financing_proceeds_usd: Decimal | None = None


class FailureAnalysisRecord(ContractModel):
    event_id: str
    false_positive: bool
    false_negative: bool
    categories: tuple[FailureCategory, ...] = Field(min_length=1)
    knowable_pre_event: bool
    rationale: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]


class LeakageFinding(ContractModel):
    event_id: str
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    detected: bool
    repaired: bool = False

    @model_validator(mode="after")
    def repaired_only_when_detected(self) -> Self:
        if self.repaired and not self.detected:
            raise ValueError("leakage cannot be repaired if it was never detected")
        return self


class MetricEstimate(ContractModel):
    value: float
    n: int = Field(ge=0)
    ci_low: float | None = None
    ci_high: float | None = None


class ValidationSummary(ContractModel):
    event_count: int
    critical_field_completeness_pct: float
    source_lineage_coverage_pct: float
    known_unrepaired_leakage_count: int
    deterministic_rerun_agreement_pct: float
    catalyst_interval_precision_pct: float
    brier_score: float
    base_prior_brier_score: float
    investable_median_xbi_relative_t20_pct: float | None
    gated_median_xbi_relative_t20_pct: float | None
    investable_minus_gated_median_pp: float | None
    top_quintile_swing_success: MetricEstimate
    bottom_quintile_swing_success: MetricEstimate
    high_conviction_severe_loss: MetricEstimate
    financing_gate_precision: MetricEstimate
    acceptance: dict[str, bool]
    recommendation: Recommendation


def validation_period(event_date: date) -> ValidationPeriod:
    if event_date.year <= 2022:
        return ValidationPeriod.DIAGNOSTIC_2018_2022
    if event_date.year <= 2024:
        return ValidationPeriod.TEMPORAL_2023_2024
    if event_date.year == 2025:
        return ValidationPeriod.HOLDOUT_2025
    raise ValueError("event date is outside frozen validation periods")


def snapshot_cutoff(
    event_at: datetime, label: SnapshotLabel, last_complete_session: date
) -> datetime:
    _require_aware(event_at, "event_at")
    if label is SnapshotLabel.T_MINUS_60:
        return event_at - timedelta(days=60)
    if label is SnapshotLabel.T_MINUS_30:
        return event_at - timedelta(days=30)
    if label is SnapshotLabel.T_MINUS_10:
        return event_at - timedelta(days=10)
    if last_complete_session >= event_at.date():
        raise ValueError("last complete pre-event session must precede event date")
    return datetime.combine(last_complete_session, datetime.max.time(), tzinfo=event_at.tzinfo)


def validate_source_cutoff(available_at: datetime, cutoff: datetime) -> None:
    _require_aware(available_at, "available_at")
    _require_aware(cutoff, "cutoff")
    if available_at > cutoff:
        raise ValueError("historical source was not publicly available by snapshot cutoff")


def registry_sha256(events: tuple[HistoricalEvent, ...]) -> str:
    return _canonical_hash(
        [event.model_dump(mode="json") for event in sorted(events, key=lambda item: item.event_id)]
    )


def cohort_sha256(events: tuple[HistoricalEvent, ...], seed: int = VALIDATION_SEED) -> str:
    return _canonical_hash(
        {
            "seed": seed,
            "event_ids": [
                event.event_id for event in sorted(events, key=lambda item: item.event_id)
            ],
        }
    )


def select_frozen_cohort(
    registry: tuple[HistoricalEvent, ...],
    *,
    seed: int = VALIDATION_SEED,
) -> tuple[HistoricalEvent, ...]:
    """Select the minimum 120-event cohort deterministically across year/stratum.

    Selection is year-aware within each stratum, uses a fixed PRNG seed, and enforces
    issuer concentration limits during selection. Events must already have their
    primary stratum assigned before this function is called.
    """
    eligible = tuple(event for event in registry if event.included)
    selected: list[HistoricalEvent] = []
    issuer_counts: Counter[str] = Counter()
    stratum_issuer_counts: dict[EventStratum, Counter[str]] = defaultdict(Counter)
    rng = random.Random(seed)

    for stratum in EventStratum:
        minimum = STRATUM_MINIMUMS[stratum.value]
        pool = [event for event in eligible if event.primary_stratum is stratum]
        if len(pool) < minimum:
            raise ValueError(f"{stratum.value} has {len(pool)} events; minimum is {minimum}")
        by_year: dict[int, list[HistoricalEvent]] = defaultdict(list)
        for event in pool:
            by_year[event.event_at.year].append(event)
        year_order = sorted(by_year)
        for year in year_order:
            rng.shuffle(by_year[year])
        cursors = {year: 0 for year in year_order}
        while sum(1 for item in selected if item.primary_stratum is stratum) < minimum:
            progressed = False
            for year in year_order:
                group = by_year[year]
                while cursors[year] < len(group):
                    candidate = group[cursors[year]]
                    cursors[year] += 1
                    if issuer_counts[candidate.issuer_id] >= 5:
                        continue
                    stratum_limit = max(1, math.floor(minimum * 0.10))
                    if stratum_issuer_counts[stratum][candidate.issuer_id] >= stratum_limit:
                        continue
                    selected.append(candidate)
                    issuer_counts[candidate.issuer_id] += 1
                    stratum_issuer_counts[stratum][candidate.issuer_id] += 1
                    progressed = True
                    break
                if sum(1 for item in selected if item.primary_stratum is stratum) >= minimum:
                    break
            if not progressed:
                raise ValueError(f"cannot satisfy issuer concentration limit for {stratum.value}")

    cohort = tuple(sorted(selected, key=lambda item: (item.event_at, item.event_id)))
    validate_cohort(cohort)
    return cohort


def validate_cohort(events: tuple[HistoricalEvent, ...]) -> None:
    if len(events) < MIN_COHORT_SIZE:
        raise ValueError(f"cohort has {len(events)} events; minimum is {MIN_COHORT_SIZE}")
    ids = [event.event_id for event in events]
    if len(set(ids)) != len(ids):
        raise ValueError("cohort contains duplicate event IDs")
    strata = Counter(event.primary_stratum.value for event in events)
    for stratum, minimum in STRATUM_MINIMUMS.items():
        if strata[stratum] < minimum:
            raise ValueError(f"cohort stratum {stratum} below minimum {minimum}")
    if sum(event.negative_event for event in events) < 40:
        raise ValueError("cohort requires at least 40 negative events")
    if sum(event.financing_t_minus_90_to_t_plus_30 for event in events) < 20:
        raise ValueError("cohort requires at least 20 financing/dilution events")
    if sum(event.single_asset_issuer for event in events) < 20:
        raise ValueError("cohort requires at least 20 single-asset issuers")
    issuer_counts = Counter(event.issuer_id for event in events)
    if any(count > 5 for count in issuer_counts.values()):
        raise ValueError("an issuer contributes more than five cohort events")
    for stratum in EventStratum:
        stratum_events = [event for event in events if event.primary_stratum is stratum]
        per_issuer = Counter(event.issuer_id for event in stratum_events)
        if any(count / len(stratum_events) > 0.10 for count in per_issuer.values()):
            raise ValueError(f"issuer exceeds 10% concentration in {stratum.value}")


def align_t0_session(event_at: datetime, trading_sessions: tuple[date, ...]) -> date:
    _require_aware(event_at, "event_at")
    if not trading_sessions:
        raise ValueError("trading sessions are required")
    eastern = event_at.astimezone(ZoneInfo("America/New_York"))
    local_date = eastern.date()
    before_close = eastern.hour < 16
    candidates = [session for session in trading_sessions if session >= local_date]
    if not candidates:
        raise ValueError("no trading session available on or after event")
    if local_date in trading_sessions and before_close:
        return local_date
    later = [session for session in trading_sessions if session > local_date]
    if not later:
        raise ValueError("no next regular session after out-of-hours event")
    return later[0]


def calculate_outcome(
    *,
    event_id: str,
    event_at: datetime,
    security: tuple[PriceObservation, ...],
    benchmark: tuple[PriceObservation, ...],
    financing_through_t30: bool,
    fully_diluted_share_change_pct: Decimal | None = None,
    financing_proceeds_usd: Decimal | None = None,
) -> HistoricalOutcome:
    security_map = {item.session_date: item.adjusted_close for item in security}
    benchmark_map = {item.session_date: item.adjusted_close for item in benchmark}
    common = tuple(sorted(set(security_map) & set(benchmark_map)))
    t0 = align_t0_session(event_at, common)
    index = common.index(t0)
    if index < 1 or index + 20 >= len(common):
        raise ValueError("outcome path requires T-1 through T+20 complete sessions")
    base_date = common[index - 1]
    base_security = security_map[base_date]
    base_benchmark = benchmark_map[base_date]

    def security_return(offset: int) -> Decimal:
        return _return_pct(base_security, security_map[common[index + offset]])

    def benchmark_return(offset: int) -> Decimal:
        return _return_pct(base_benchmark, benchmark_map[common[index + offset]])

    path = [security_return(offset) for offset in range(0, 21)]
    first_success_index = next(
        (offset for offset, value in enumerate(path) if value >= Decimal("20")), None
    )
    swing_success = first_success_index is not None and not any(
        value <= Decimal("-25") for value in path[:first_success_index]
    )
    severe_loss = any(value <= Decimal("-40") for value in path)
    return HistoricalOutcome(
        event_id=event_id,
        t0_session=t0,
        t_minus_1_close=base_security,
        return_t1_pct=security_return(1),
        return_t5_pct=security_return(5),
        return_t20_pct=security_return(20),
        xbi_relative_t1_pct=security_return(1) - benchmark_return(1),
        xbi_relative_t5_pct=security_return(5) - benchmark_return(5),
        xbi_relative_t20_pct=security_return(20) - benchmark_return(20),
        mfe_t20_pct=max(path),
        mae_t20_pct=min(path),
        severe_loss=severe_loss,
        swing_success=swing_success,
        financing_through_t30=financing_through_t30,
        fully_diluted_share_change_pct=fully_diluted_share_change_pct,
        financing_proceeds_usd=financing_proceeds_usd,
    )


def brier_score(predicted_pct: tuple[float, ...], observed: tuple[bool, ...]) -> float:
    if len(predicted_pct) != len(observed) or not predicted_pct:
        raise ValueError("Brier score requires equal non-empty prediction/outcome arrays")
    errors = [
        ((prediction / 100.0) - float(outcome)) ** 2
        for prediction, outcome in zip(predicted_pct, observed, strict=True)
    ]
    return sum(errors) / len(errors)


def wilson_rate(successes: int, total: int, z: float = 1.96) -> MetricEstimate:
    if total == 0:
        return MetricEstimate(value=0.0, n=0, ci_low=None, ci_high=None)
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return MetricEstimate(
        value=p, n=total, ci_low=max(0.0, center - margin), ci_high=min(1.0, center + margin)
    )


def build_failure_register(
    decisions: tuple[HistoricalDecisionLock, ...],
    outcomes: tuple[HistoricalOutcome, ...],
    annotations: dict[str, tuple[tuple[FailureCategory, ...], bool, str, tuple[str, ...]]],
) -> tuple[FailureAnalysisRecord, ...]:
    primary = {
        item.event_id: item for item in decisions if item.snapshot_label is SnapshotLabel.T_MINUS_30
    }
    outcome_map = {item.event_id: item for item in outcomes}
    required: list[tuple[str, bool, bool]] = []
    investable = {Classification.HIGH_CONVICTION_CATALYST_SWING, Classification.CATALYST_SWING}
    for event_id, outcome in outcome_map.items():
        decision = primary.get(event_id)
        if decision is None:
            continue
        false_positive = (
            decision.classification in investable and outcome.return_t20_pct <= Decimal("-20")
        )
        false_negative = (
            decision.classification not in investable and outcome.mfe_t20_pct >= Decimal("40")
        )
        if false_positive or false_negative:
            required.append((event_id, false_positive, false_negative))
    missing = sorted(event_id for event_id, _, _ in required if event_id not in annotations)
    if missing:
        raise ValueError(f"failure analysis annotations missing for: {', '.join(missing)}")
    return tuple(
        FailureAnalysisRecord(
            event_id=event_id,
            false_positive=false_positive,
            false_negative=false_negative,
            categories=annotations[event_id][0],
            knowable_pre_event=annotations[event_id][1],
            rationale=annotations[event_id][2],
            evidence_ids=annotations[event_id][3],
        )
        for event_id, false_positive, false_negative in required
    )


def assert_zero_unrepaired_leakage(findings: tuple[LeakageFinding, ...]) -> None:
    unresolved = [item for item in findings if item.detected and not item.repaired]
    if unresolved:
        raise ValueError(f"historical leakage remains in {len(unresolved)} findings")


def deterministic_record_hash(*records: ContractModel) -> str:
    return _canonical_hash([record.model_dump(mode="json") for record in records])


def summarize_validation(
    *,
    decisions: tuple[HistoricalDecisionLock, ...],
    outcomes: tuple[HistoricalOutcome, ...],
    base_prior_pct_by_event: dict[str, float],
    critical_field_completeness_pct: float,
    source_lineage_coverage_pct: float,
    leakage_findings: tuple[LeakageFinding, ...],
    deterministic_rerun_agreement_pct: float,
    catalyst_interval_precision_pct: float,
) -> ValidationSummary:
    primary = {
        item.event_id: item for item in decisions if item.snapshot_label is SnapshotLabel.T_MINUS_30
    }
    matched = [(primary[item.event_id], item) for item in outcomes if item.event_id in primary]
    if not matched:
        raise ValueError("validation summary requires matched T-30 decisions and outcomes")
    observed = tuple(item.swing_success for _, item in matched)
    predicted = tuple(decision.pos_mid_pct for decision, _ in matched)
    priors = tuple(base_prior_pct_by_event[decision.event_id] for decision, _ in matched)
    brier = brier_score(predicted, observed)
    base_brier = brier_score(priors, observed)
    investable_set = {Classification.HIGH_CONVICTION_CATALYST_SWING, Classification.CATALYST_SWING}
    investable = [
        float(outcome.xbi_relative_t20_pct)
        for decision, outcome in matched
        if decision.classification in investable_set
    ]
    gated = [
        float(outcome.xbi_relative_t20_pct)
        for decision, outcome in matched
        if decision.classification not in investable_set
    ]
    investable_median = statistics.median(investable) if investable else None
    gated_median = statistics.median(gated) if gated else None
    median_delta = (
        investable_median - gated_median
        if investable_median is not None and gated_median is not None
        else None
    )

    ordered = sorted(matched, key=lambda pair: (pair[0].raw_score, pair[0].event_id))
    quintile = max(1, len(ordered) // 5)
    bottom = ordered[:quintile]
    top = ordered[-quintile:]
    top_rate = wilson_rate(sum(outcome.swing_success for _, outcome in top), len(top))
    bottom_rate = wilson_rate(sum(outcome.swing_success for _, outcome in bottom), len(bottom))

    high = [
        (decision, outcome)
        for decision, outcome in matched
        if decision.classification is Classification.HIGH_CONVICTION_CATALYST_SWING
    ]
    high_loss = wilson_rate(sum(outcome.severe_loss for _, outcome in high), len(high))
    financing_gate = [
        (decision, outcome)
        for decision, outcome in matched
        if "FINANCING_RISK" in decision.gate_codes
        or decision.classification is Classification.FINANCING_RISK
    ]
    financing_precision = wilson_rate(
        sum(outcome.financing_through_t30 for _, outcome in financing_gate), len(financing_gate)
    )
    unrepaired = sum(item.detected and not item.repaired for item in leakage_findings)
    acceptance = {
        "critical_field_completeness": critical_field_completeness_pct >= 95.0,
        "source_lineage": source_lineage_coverage_pct == 100.0,
        "zero_known_leakage": unrepaired == 0,
        "deterministic_rerun": deterministic_rerun_agreement_pct == 100.0,
        "catalyst_interval_precision": catalyst_interval_precision_pct >= 85.0,
        "pos_brier_vs_prior": brier <= base_brier,
        "investable_median_advantage": median_delta is not None and median_delta >= 10.0,
        "top_bottom_swing_success": bottom_rate.value == 0.0
        and top_rate.value > 0.0
        or bottom_rate.value > 0.0
        and top_rate.value >= 1.5 * bottom_rate.value,
        "high_conviction_severe_loss": high_loss.n > 0 and high_loss.value <= 0.15,
        "financing_gate_precision": financing_precision.n > 0 and financing_precision.value >= 0.60,
    }
    recommendation = _recommendation(acceptance, unrepaired)
    return ValidationSummary(
        event_count=len(matched),
        critical_field_completeness_pct=critical_field_completeness_pct,
        source_lineage_coverage_pct=source_lineage_coverage_pct,
        known_unrepaired_leakage_count=unrepaired,
        deterministic_rerun_agreement_pct=deterministic_rerun_agreement_pct,
        catalyst_interval_precision_pct=catalyst_interval_precision_pct,
        brier_score=brier,
        base_prior_brier_score=base_brier,
        investable_median_xbi_relative_t20_pct=investable_median,
        gated_median_xbi_relative_t20_pct=gated_median,
        investable_minus_gated_median_pp=median_delta,
        top_quintile_swing_success=top_rate,
        bottom_quintile_swing_success=bottom_rate,
        high_conviction_severe_loss=high_loss,
        financing_gate_precision=financing_precision,
        acceptance=acceptance,
        recommendation=recommendation,
    )


def _recommendation(acceptance: dict[str, bool], unrepaired_leakage: int) -> Recommendation:
    if (
        unrepaired_leakage
        or not acceptance["critical_field_completeness"]
        or not acceptance["source_lineage"]
        or not acceptance["deterministic_rerun"]
    ):
        return Recommendation.REPAIR
    predictive = (
        acceptance["pos_brier_vs_prior"]
        and acceptance["investable_median_advantage"]
        and acceptance["top_bottom_swing_success"]
        and acceptance["high_conviction_severe_loss"]
        and acceptance["financing_gate_precision"]
    )
    if predictive:
        return Recommendation.PROCEED
    return Recommendation.RECALIBRATE


def _return_pct(start: Decimal, end: Decimal) -> Decimal:
    return (end / start - Decimal("1")) * Decimal("100")


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
