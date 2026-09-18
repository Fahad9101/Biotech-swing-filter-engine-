from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from boe.enums import CatalystType
from boe.objective_pos_methodology import (
    BASE_MIDPOINT_PCT,
    LOW_CONFIDENCE_HALF_WIDTH_PP,
    estimate_objective_pos,
)

ROOT = Path(__file__).resolve().parents[1]


def test_base_midpoints_match_the_frozen_scorecard_exactly() -> None:
    """This methodology must reuse BOE-1.0.0's own frozen prior verbatim, not
    a hand-copied value that could silently drift."""
    scorecard = json.loads((ROOT / "contracts/boe-scorecard.v1.0.0.json").read_bytes())
    frozen = scorecard["pos"]["base_midpoint_pct"]
    assert {k: str(v) for k, v in BASE_MIDPOINT_PCT.items()} == {
        k: str(Decimal(str(v))) for k, v in frozen.items()
    }


def test_clinical_catalyst_uses_its_own_prior_at_low_confidence() -> None:
    result = estimate_objective_pos(event_id="EV-1", catalyst_type=CatalystType.CLIN_P2)
    assert result.prior_pct == Decimal("40")
    assert result.mid_pct == Decimal("40")
    assert result.low_pct == Decimal("40") - LOW_CONFIDENCE_HALF_WIDTH_PP
    assert result.high_pct == Decimal("40") + LOW_CONFIDENCE_HALF_WIDTH_PP


def test_conference_event_requires_and_uses_underlying_phase() -> None:
    with pytest.raises(ValueError, match="underlying clinical phase"):
        estimate_objective_pos(event_id="EV-2", catalyst_type=CatalystType.CONF_DATA)

    result = estimate_objective_pos(
        event_id="EV-2",
        catalyst_type=CatalystType.CONF_DATA,
        underlying_phase=CatalystType.CLIN_P3,
    )
    assert result.catalyst_type == CatalystType.CONF_DATA
    assert result.prior_pct == Decimal("55")


def test_regulatory_decision_prior_matches_frozen_table() -> None:
    result = estimate_objective_pos(event_id="EV-3", catalyst_type=CatalystType.REG_DECISION)
    assert result.prior_pct == Decimal("75")


def test_bounds_never_exceed_the_frozen_clamp() -> None:
    for catalyst_type in (CatalystType.REG_SUBMIT, CatalystType.CLIN_P1):
        result = estimate_objective_pos(event_id="EV-4", catalyst_type=catalyst_type)
        assert Decimal("5") <= result.low_pct <= result.mid_pct <= result.high_pct <= Decimal("95")
        assert Decimal("10") <= result.mid_pct <= Decimal("90")
