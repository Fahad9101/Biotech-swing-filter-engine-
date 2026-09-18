"""Regressions for the live CATALYST facts builder."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from boe.contracts import load_scorecard
from boe.enums import CatalystType
from boe.filter.extraction import DatePrecision, DiscoveredCatalyst
from boe.filter.live_catalyst import live_catalyst_score

ROOT = Path(__file__).resolve().parents[1]
RULES = load_scorecard(ROOT / "contracts/boe-scorecard.v1.0.0.json").contract
AS_OF = datetime(2026, 9, 18, tzinfo=UTC)


def _candidate(catalyst_type: CatalystType, window_start: date) -> DiscoveredCatalyst:
    return DiscoveredCatalyst(
        ticker="CAPR",
        cik="0001133869",
        company="Capricor Therapeutics, Inc.",
        catalyst_type=catalyst_type,
        window_start=window_start,
        window_end=window_start,
        precision=DatePrecision.EXACT_DATE,
        trigger_phrase="PDUFA",
        source_sentence="New PDUFA target action date of November 22, 2026...",
        source_url="https://www.sec.gov/example/capr.htm",
        filing_date=date(2026, 8, 24),
    )


def test_live_catalyst_score_reg_decision_gets_high_timing_confidence():
    candidate = _candidate(CatalystType.REG_DECISION, date(2026, 11, 22))
    factor_score = live_catalyst_score(candidate, as_of=AS_OF, rules=RULES, candidate_id="capr-1")
    timing = next(s for s in factor_score.subfactors if s.code == "TIMING_CONFIDENCE")
    assert timing.data_state.value == "DERIVED"
    materiality = next(s for s in factor_score.subfactors if s.code == "MATERIALITY")
    assert materiality.data_state.value == "MISSING"
    assert materiality.points == 0
    assert 0 <= factor_score.points <= factor_score.max_points


def test_live_catalyst_score_clin_p2_gets_moderate_timing_and_real_proximity():
    candidate = _candidate(CatalystType.CLIN_P2, date(2026, 10, 15))
    factor_score = live_catalyst_score(candidate, as_of=AS_OF, rules=RULES, candidate_id="capr-2")
    proximity = next(s for s in factor_score.subfactors if s.code == "PROXIMITY")
    assert proximity.points > 0
    assert proximity.data_state.value == "DERIVED"


def test_live_catalyst_score_proximity_reflects_real_days_to_event():
    near = live_catalyst_score(
        _candidate(CatalystType.REG_DECISION, date(2026, 9, 25)),
        as_of=AS_OF,
        rules=RULES,
        candidate_id="near",
    )
    far = live_catalyst_score(
        _candidate(CatalystType.REG_DECISION, date(2027, 6, 1)),
        as_of=AS_OF,
        rules=RULES,
        candidate_id="far",
    )
    near_proximity = next(s for s in near.subfactors if s.code == "PROXIMITY").points
    far_proximity = next(s for s in far.subfactors if s.code == "PROXIMITY").points
    assert near_proximity > far_proximity
