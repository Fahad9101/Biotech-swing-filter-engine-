"""Regressions for the live TECHNICAL facts builder."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from boe.contracts import load_scorecard
from boe.filter.live_technical import benchmark_facts, live_technical_score
from boe.market import MarketBar, MarketSeries

ROOT = Path(__file__).resolve().parents[1]
RULES = load_scorecard(ROOT / "contracts/boe-scorecard.v1.0.0.json").contract
AS_OF = datetime(2026, 9, 18, 20, 0, tzinfo=UTC)


def _sessions(count: int, end: date) -> list[date]:
    sessions: list[date] = []
    current = end
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current -= timedelta(days=1)
    return list(reversed(sessions))


def _series(symbol: str, *, base: Decimal, drift: Decimal, count: int = 90) -> MarketSeries:
    sessions = _sessions(count, AS_OF.date())
    bars = []
    for index, session in enumerate(sessions):
        close = (base + drift * index).quantize(Decimal("0.01"))
        bars.append(
            MarketBar(
                symbol=symbol,
                session_date=session,
                open=close - Decimal("0.05"),
                high=close + Decimal("0.20"),
                low=close - Decimal("0.20"),
                close=close,
                adjusted_close=close,
                volume=1_000_000 + (index % 5) * 10_000,
            )
        )
    return MarketSeries(
        symbol=symbol,
        provider="TEST",
        bars=tuple(bars),
        retrieved_at=AS_OF,
        available_at=AS_OF,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=AS_OF.date(),
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST",
    )


def test_live_technical_score_computes_real_factor_score_from_real_bars():
    security = _series("XYZ", base=Decimal("10.00"), drift=Decimal("0.05"))
    benchmark = _series("XBI", base=Decimal("100.00"), drift=Decimal("0.02"))
    factor_score, facts = live_technical_score(
        security_series=security, benchmark_series=benchmark, as_of=AS_OF, rules=RULES
    )
    assert 0 <= factor_score.points <= factor_score.max_points
    assert facts["stale"] is False
    assert Decimal(facts["close"]) > 0
    assert Decimal(facts["sma20"]) > 0


def test_live_technical_score_structure_subfactor_is_missing_not_fabricated():
    security = _series("XYZ", base=Decimal("10.00"), drift=Decimal("0.05"))
    benchmark = _series("XBI", base=Decimal("100.00"), drift=Decimal("0.02"))
    factor_score, _ = live_technical_score(
        security_series=security, benchmark_series=benchmark, as_of=AS_OF, rules=RULES
    )
    structure = next(s for s in factor_score.subfactors if s.code == "STRUCTURE")
    assert structure.data_state.value == "MISSING"


def test_live_technical_score_includes_real_median_dollar_volume():
    security = _series("XYZ", base=Decimal("10.00"), drift=Decimal("0.05"))
    benchmark = _series("XBI", base=Decimal("100.00"), drift=Decimal("0.02"))
    _, facts = live_technical_score(
        security_series=security, benchmark_series=benchmark, as_of=AS_OF, rules=RULES
    )
    # last 20 sessions all have volume 1,000,000 + (index % 5) * 10,000 at a
    # close near $10.90 - a real median of close*volume, not a placeholder.
    assert Decimal(facts["median_dollar_volume_20d"]) > Decimal("9000000")


def test_benchmark_facts_returns_the_latest_point_in_time_close():
    benchmark = _series("XBI", base=Decimal("100.00"), drift=Decimal("0.02"))
    facts = benchmark_facts(benchmark, as_of=AS_OF)
    assert facts["symbol"] == "XBI"
    assert facts["session_date"] == benchmark.bars[-1].session_date.isoformat()
    assert Decimal(facts["close"]) == benchmark.bars[-1].adjusted_close


def test_benchmark_facts_raises_when_no_bars_exist_yet():
    # A series with only bars strictly after the cutoff (e.g. a fresh
    # listing) must not silently report a future close - point_in_time_
    # series() itself catches this, benchmark_facts must propagate it.
    early_adjustment = date(2026, 9, 1)
    benchmark = MarketSeries(
        symbol="XBI",
        provider="TEST",
        bars=(
            MarketBar(
                symbol="XBI",
                session_date=date(2026, 9, 10),
                open=Decimal("100.00"),
                high=Decimal("101.00"),
                low=Decimal("99.00"),
                close=Decimal("100.00"),
                adjusted_close=Decimal("100.00"),
                volume=1_000_000,
            ),
        ),
        retrieved_at=AS_OF,
        available_at=AS_OF,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=early_adjustment,
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST",
    )
    cutoff = datetime(2026, 9, 5, tzinfo=UTC)
    with pytest.raises(ValueError, match="no complete market bars exist"):
        benchmark_facts(benchmark, as_of=cutoff)
