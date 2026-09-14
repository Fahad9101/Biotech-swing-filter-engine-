from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from boe.enums import CatalystType, Classification
from boe.historical_validation import (
    CohortManifest,
    EventStratum,
    FailureCategory,
    HistoricalDecisionLock,
    HistoricalEvent,
    LeakageFinding,
    PriceObservation,
    Recommendation,
    SnapshotLabel,
    align_t0_session,
    assert_zero_unrepaired_leakage,
    brier_score,
    build_failure_register,
    calculate_outcome,
    cohort_sha256,
    registry_sha256,
    select_frozen_cohort,
    snapshot_cutoff,
    summarize_validation,
    validate_cohort,
    validate_source_cutoff,
    validation_period,
)

RULES_CHECKSUM = "11cffb776ffd6bbd943b1d23dfcf6541ab02fcbfec753f13d00a7f4acee8b569"
CODE_SHA = "3" * 40


def _event(index: int, stratum: EventStratum) -> HistoricalEvent:
    catalyst = {
        EventStratum.PHASE_2_POC: CatalystType.CLIN_P2,
        EventStratum.PHASE_3_PIVOTAL: CatalystType.CLIN_P3,
        EventStratum.REGULATORY: CatalystType.REG_DECISION,
        EventStratum.EARLY_CLINICAL: CatalystType.CLIN_P1,
        EventStratum.CONFERENCE_OTHER: CatalystType.CONF_DATA,
    }[stratum]
    year = 2018 + index % 8
    day = 1 + index % 20
    issuer_number = index + 1
    return HistoricalEvent(
        event_id=f"EV-{index:03d}",
        issuer_id=f"ISS-{issuer_number:03d}",
        ticker=f"B{issuer_number:03d}",
        cik=f"{issuer_number:010d}",
        company=f"Biotech {issuer_number}",
        asset=f"Asset-{issuer_number}",
        indication="Oncology",
        catalyst_type=catalyst,
        clinical_phase={
            EventStratum.PHASE_2_POC: "PHASE_2",
            EventStratum.PHASE_3_PIVOTAL: "PHASE_3",
            EventStratum.REGULATORY: "REGULATORY",
            EventStratum.EARLY_CLINICAL: "PHASE_1",
            EventStratum.CONFERENCE_OTHER: "PHASE_2",
        }[stratum],
        primary_stratum=stratum,
        event_at=datetime(year, (index % 12) + 1, day, 12, 0, tzinfo=UTC),
        source_ids=(f"SRC-{index:03d}",),
        negative_event=index % 3 == 0,
        financing_t_minus_90_to_t_plus_30=index % 5 == 0,
        single_asset_issuer=index % 4 == 0,
    )


def _registry() -> tuple[HistoricalEvent, ...]:
    events: list[HistoricalEvent] = []
    index = 0
    for stratum, count in (
        (EventStratum.PHASE_2_POC, 34),
        (EventStratum.PHASE_3_PIVOTAL, 34),
        (EventStratum.REGULATORY, 34),
        (EventStratum.EARLY_CLINICAL, 19),
        (EventStratum.CONFERENCE_OTHER, 19),
    ):
        for _ in range(count):
            events.append(_event(index, stratum))
            index += 1
    return tuple(events)


def _prices(start: date, count: int, base: Decimal, daily: Decimal) -> tuple[PriceObservation, ...]:
    sessions: list[PriceObservation] = []
    current = start
    index = 0
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(
                PriceObservation(
                    session_date=current,
                    adjusted_close=base + daily * Decimal(index),
                )
            )
            index += 1
        current += timedelta(days=1)
    return tuple(sessions)


def _decision(
    event_id: str,
    score: int,
    classification: Classification,
    *,
    pos: float = 50.0,
    gate_codes: tuple[str, ...] = (),
) -> HistoricalDecisionLock:
    cutoff = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    return HistoricalDecisionLock(
        event_id=event_id,
        snapshot_label=SnapshotLabel.T_MINUS_30,
        snapshot_cutoff=cutoff,
        locked_at=cutoff + timedelta(hours=1),
        code_sha=CODE_SHA,
        rules_checksum=RULES_CHECKSUM,
        input_manifest_sha256="a" * 64,
        raw_score=score,
        coverage_pct=100.0,
        classification=classification,
        gate_codes=gate_codes,
        pos_low_pct=max(5.0, pos - 10),
        pos_mid_pct=pos,
        pos_high_pct=min(95.0, pos + 10),
        conservative_equity_value=Decimal("10"),
        base_equity_value=Decimal("20"),
        bull_equity_value=Decimal("30"),
        base_ev_pct=Decimal("20"),
        evidence_ids=(f"E-{event_id}",),
    )


def test_deterministic_cohort_selection_and_manifest_hashing():
    registry = _registry()
    first = select_frozen_cohort(registry)
    second = select_frozen_cohort(registry)
    assert first == second
    assert len(first) == 120
    validate_cohort(first)
    assert cohort_sha256(first) == cohort_sha256(second)
    assert registry_sha256(registry) == registry_sha256(tuple(reversed(registry)))

    manifest = CohortManifest(
        frozen_at=datetime(2026, 9, 14, 20, 0, tzinfo=UTC),
        events=first,
        registry_sha256=registry_sha256(registry),
        cohort_sha256=cohort_sha256(first),
    )
    assert len(manifest.events) == 120


def test_cohort_minimums_are_hard_gates():
    cohort = select_frozen_cohort(_registry())
    with pytest.raises(ValueError, match="minimum"):
        validate_cohort(cohort[:-1])


def test_validation_periods_are_frozen():
    assert validation_period(date(2022, 12, 31)).value.startswith("DIAGNOSTIC")
    assert validation_period(date(2024, 12, 31)).value.startswith("TEMPORAL")
    assert validation_period(date(2025, 12, 31)).value.startswith("HOLDOUT")
    with pytest.raises(ValueError, match="outside"):
        validation_period(date(2026, 1, 1))


def test_snapshot_cutoffs_and_source_availability_are_point_in_time():
    event = datetime(2024, 6, 30, 20, 0, tzinfo=UTC)
    assert snapshot_cutoff(event, SnapshotLabel.T_MINUS_30, date(2024, 6, 28)) == event - timedelta(days=30)
    last = snapshot_cutoff(event, SnapshotLabel.LAST_COMPLETE_SESSION, date(2024, 6, 28))
    assert last.date() == date(2024, 6, 28)

    validate_source_cutoff(event - timedelta(days=31), event - timedelta(days=30))
    with pytest.raises(ValueError, match="not publicly available"):
        validate_source_cutoff(event - timedelta(days=29), event - timedelta(days=30))


def test_after_hours_event_aligns_to_next_regular_session():
    sessions = (date(2024, 6, 28), date(2024, 7, 1), date(2024, 7, 2))
    after_hours = datetime(2024, 6, 28, 21, 30, tzinfo=UTC)  # 17:30 New York EDT
    assert align_t0_session(after_hours, sessions) == date(2024, 7, 1)

    premarket = datetime(2024, 7, 1, 11, 0, tzinfo=UTC)  # 07:00 New York EDT
    assert align_t0_session(premarket, sessions) == date(2024, 7, 1)


def test_outcome_math_path_logic_and_xbi_relative_return():
    security = list(_prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("1")))
    benchmark = _prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("0.2"))
    event_at = datetime(2024, 1, 8, 13, 0, tzinfo=UTC)
    outcome = calculate_outcome(
        event_id="EV",
        event_at=event_at,
        security=tuple(security),
        benchmark=benchmark,
        financing_through_t30=False,
    )
    assert outcome.return_t20_pct > outcome.xbi_relative_t20_pct
    assert outcome.mfe_t20_pct >= outcome.return_t20_pct
    assert outcome.mae_t20_pct <= outcome.mfe_t20_pct
    assert outcome.severe_loss is False


def test_swing_success_rejects_earlier_25_percent_drawdown():
    security = list(_prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("0")))
    benchmark = _prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("0"))
    event_at = datetime(2024, 1, 8, 13, 0, tzinfo=UTC)
    sessions = [item.session_date for item in security]
    t0 = align_t0_session(event_at, tuple(sessions))
    t0_index = sessions.index(t0)
    base = security[t0_index - 1].adjusted_close
    security[t0_index + 1] = PriceObservation(session_date=sessions[t0_index + 1], adjusted_close=base * Decimal("0.74"))
    security[t0_index + 5] = PriceObservation(session_date=sessions[t0_index + 5], adjusted_close=base * Decimal("1.30"))
    outcome = calculate_outcome(
        event_id="EV",
        event_at=event_at,
        security=tuple(security),
        benchmark=benchmark,
        financing_through_t30=False,
    )
    assert outcome.mfe_t20_pct >= Decimal("20")
    assert outcome.swing_success is False


def test_severe_loss_is_path_dependent():
    security = list(_prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("0")))
    benchmark = _prices(date(2024, 1, 2), 30, Decimal("100"), Decimal("0"))
    event_at = datetime(2024, 1, 8, 13, 0, tzinfo=UTC)
    sessions = [item.session_date for item in security]
    t0 = align_t0_session(event_at, tuple(sessions))
    t0_index = sessions.index(t0)
    base = security[t0_index - 1].adjusted_close
    security[t0_index + 5] = PriceObservation(session_date=sessions[t0_index + 5], adjusted_close=base * Decimal("0.59"))
    security[t0_index + 20] = PriceObservation(session_date=sessions[t0_index + 20], adjusted_close=base * Decimal("1.20"))
    outcome = calculate_outcome(
        event_id="EV",
        event_at=event_at,
        security=tuple(security),
        benchmark=benchmark,
        financing_through_t30=False,
    )
    assert outcome.return_t20_pct == Decimal("20.0")
    assert outcome.severe_loss is True


def test_brier_and_failure_register_are_deterministic():
    assert brier_score((80.0, 20.0), (True, False)) == pytest.approx(0.04)
    decisions = (
        _decision("FP", 85, Classification.CATALYST_SWING, pos=80),
        _decision("FN", 40, Classification.REJECT, pos=20),
    )
    outcomes = (
        _simple_outcome("FP", Decimal("-25"), Decimal("5"), severe=False, success=False),
        _simple_outcome("FN", Decimal("15"), Decimal("45"), severe=False, success=True),
    )
    annotations = {
        "FP": ((FailureCategory.SCIENCE,), True, "Science was overestimated.", ("E-FP",)),
        "FN": ((FailureCategory.VALUATION,), True, "Expectation gap was underestimated.", ("E-FN",)),
    }
    records = build_failure_register(decisions, outcomes, annotations)
    assert {record.event_id for record in records} == {"FP", "FN"}


def test_unrepaired_leakage_blocks_validation():
    findings = (
        LeakageFinding(event_id="EV", code="FUTURE_SEC", description="future filing", detected=True),
    )
    with pytest.raises(ValueError, match="leakage remains"):
        assert_zero_unrepaired_leakage(findings)
    assert_zero_unrepaired_leakage((findings[0].model_copy(update={"repaired": True}),))


def test_validation_summary_uses_frozen_acceptance_without_rule_tuning():
    decisions = tuple(
        _decision(
            f"EV-{index}",
            90 - index,
            Classification.HIGH_CONVICTION_CATALYST_SWING if index < 5 else Classification.REJECT,
            pos=80.0 if index < 5 else 20.0,
            gate_codes=() if index < 5 else ("REJECT",),
        )
        for index in range(10)
    )
    outcomes = tuple(
        _simple_outcome(
            f"EV-{index}",
            Decimal("30") if index < 5 else Decimal("-5"),
            Decimal("40") if index < 5 else Decimal("5"),
            severe=False,
            success=index < 5,
        )
        for index in range(10)
    )
    priors = {f"EV-{index}": 50.0 for index in range(10)}
    summary = summarize_validation(
        decisions=decisions,
        outcomes=outcomes,
        base_prior_pct_by_event=priors,
        critical_field_completeness_pct=100.0,
        source_lineage_coverage_pct=100.0,
        leakage_findings=(),
        deterministic_rerun_agreement_pct=100.0,
        catalyst_interval_precision_pct=100.0,
    )
    assert summary.brier_score < summary.base_prior_brier_score
    assert summary.investable_minus_gated_median_pp == pytest.approx(35.0)
    assert summary.acceptance["zero_known_leakage"] is True
    assert summary.recommendation in {Recommendation.PROCEED, Recommendation.RECALIBRATE}


def _simple_outcome(
    event_id: str,
    t20: Decimal,
    mfe: Decimal,
    *,
    severe: bool,
    success: bool,
):
    from boe.historical_validation import HistoricalOutcome

    return HistoricalOutcome(
        event_id=event_id,
        t0_session=date(2024, 1, 2),
        t_minus_1_close=Decimal("10"),
        return_t1_pct=t20,
        return_t5_pct=t20,
        return_t20_pct=t20,
        xbi_relative_t1_pct=t20,
        xbi_relative_t5_pct=t20,
        xbi_relative_t20_pct=t20,
        mfe_t20_pct=mfe,
        mae_t20_pct=min(t20, Decimal("0")),
        severe_loss=severe,
        swing_success=success,
        financing_through_t30=False,
    )
