"""Regressions for FORWARD-LOG-1.0 - the shortlist forward-measurement log.

All pure logic, no network: exercises entry-freezing, checkpoint due-ness,
real return/peak computation from MarketBar series, and summary stats.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from boe.filter.forward_log import (
    CHECKPOINT_WEEKS,
    due_checkpoints,
    measure_checkpoint,
    new_entry,
    record_new_entries,
    summarize,
)
from boe.market import MarketBar, MarketSeries

AS_OF = datetime(2026, 9, 22, 20, 0, tzinfo=UTC)


def _shortlist_row(ticker: str, *, close: str = "10.00", tier: int = 1) -> dict:
    return {
        "candidate_id": f"{ticker}-REG_DECISION-2026-10-01",
        "ticker": ticker,
        "company": f"{ticker} Inc.",
        "catalyst_type": "REG_DECISION",
        "window_start": "2026-10-01",
        "window_end": "2026-10-01",
        "date_precision": "EXACT_DATE",
        "tier": tier,
        "source_url": "https://www.sec.gov/example.htm",
        "technical_facts": {"close": close},
    }


def _bars(symbol: str, entries: list[tuple[date, str]]) -> MarketSeries:
    bars = tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            adjusted_close=Decimal(close),
            volume=1_000_000,
        )
        for session, close in entries
    )
    return MarketSeries(
        symbol=symbol,
        provider="TEST",
        bars=bars,
        retrieved_at=AS_OF,
        available_at=AS_OF,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=AS_OF.date(),
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST",
    )


def test_new_entry_freezes_close_and_shortlist_context():
    row = _shortlist_row("AAA", close="12.50")
    entry = new_entry(
        row,
        as_of=AS_OF,
        benchmark_close=Decimal("95.00"),
        shortlist_definition="SHORTLIST-1.0",
        shortlist_parameters={"horizon_days": 56},
    )
    assert entry["entry_close"] == "12.50"
    assert entry["entry_xbi_close"] == "95.00"
    assert entry["entry_date"] == "2026-09-22"
    assert entry["checkpoints"] == {}
    assert entry["candidate_id"] == "AAA-REG_DECISION-2026-10-01"


def test_new_entry_refuses_to_fabricate_an_entry_price():
    row = _shortlist_row("AAA")
    row["technical_facts"] = None
    with pytest.raises(ValueError, match="without a real close"):
        new_entry(
            row,
            as_of=AS_OF,
            benchmark_close=Decimal("95.00"),
            shortlist_definition="SHORTLIST-1.0",
            shortlist_parameters={},
        )


def test_record_new_entries_adds_new_and_never_touches_existing():
    existing = [
        {
            "candidate_id": "AAA-REG_DECISION-2026-10-01",
            "entry_close": "9.99",  # deliberately different from what a re-run would compute
            "checkpoints": {},
        }
    ]
    rows = [_shortlist_row("AAA", close="50.00"), _shortlist_row("BBB", close="7.00")]
    updated, added, skipped = record_new_entries(
        existing,
        rows,
        as_of=AS_OF,
        benchmark_close=Decimal("95.00"),
        shortlist_definition="SHORTLIST-1.0",
        shortlist_parameters={},
    )
    assert added == ["BBB-REG_DECISION-2026-10-01"]
    assert skipped == []
    assert len(updated) == 2
    aaa = next(e for e in updated if e["candidate_id"] == "AAA-REG_DECISION-2026-10-01")
    assert aaa["entry_close"] == "9.99"  # untouched, not recomputed to 50.00


def test_record_new_entries_skips_a_candidate_with_no_real_close_without_crashing():
    # Real failure reproduced live: SHORTLIST-1.0 deliberately keeps a
    # candidate whose technicals are unavailable (flagged, not dropped),
    # so a shortlisted row is not guaranteed to have a real close. This
    # must not crash the whole run - it should be skipped and reported,
    # to be picked up again once real technical data exists.
    good = _shortlist_row("AAA", close="10.00")
    no_close = _shortlist_row("BRNS", close="10.00")
    no_close["technical_facts"] = None
    updated, added, skipped = record_new_entries(
        [],
        [good, no_close],
        as_of=AS_OF,
        benchmark_close=Decimal("95.00"),
        shortlist_definition="SHORTLIST-1.0",
        shortlist_parameters={},
    )
    assert added == ["AAA-REG_DECISION-2026-10-01"]
    assert len(updated) == 1
    assert len(skipped) == 1
    assert skipped[0]["ticker"] == "BRNS"
    assert "without a real close" in skipped[0]["reason"]


def test_due_checkpoints_only_returns_elapsed_unmeasured_weeks():
    entry = {"entry_date": "2026-07-01", "checkpoints": {"1": {}, "4": {}}}
    # 2026-07-01 + 2 weeks = 2026-07-15 (elapsed, unmeasured);
    # + 8 weeks = 2026-08-26 (elapsed, unmeasured);
    # + 12 weeks = 2026-09-23 (not yet elapsed).
    today = date(2026, 8, 30)
    assert due_checkpoints(entry, today=today) == [2, 8]


def test_due_checkpoints_returns_nothing_before_first_week_elapses():
    entry = {"entry_date": "2026-09-20", "checkpoints": {}}
    assert due_checkpoints(entry, today=date(2026, 9, 22)) == []


def test_due_checkpoints_covers_all_weeks_once_far_enough_out():
    entry = {"entry_date": "2026-01-01", "checkpoints": {}}
    assert due_checkpoints(entry, today=date(2027, 6, 1)) == list(CHECKPOINT_WEEKS)


def test_measure_checkpoint_computes_real_return_and_relative_return():
    entry = {
        "ticker": "AAA",
        "entry_date": "2026-09-01",
        "entry_close": "10.00",
        "entry_xbi_close": "100.00",
    }
    security = _bars(
        "AAA",
        [
            (date(2026, 9, 1), "10.00"),
            (date(2026, 9, 8), "12.00"),  # +20% at the checkpoint
        ],
    )
    benchmark = _bars(
        "XBI",
        [
            (date(2026, 9, 1), "100.00"),
            (date(2026, 9, 8), "105.00"),  # +5%
        ],
    )
    result = measure_checkpoint(
        entry, 1, security_series=security, benchmark_series=benchmark, measured_on=date(2026, 9, 8)
    )
    assert result["return_pct"] == "20.00"
    assert result["xbi_return_pct"] == "5.00"
    assert result["relative_return_pct"] == "15.00"
    assert result["hit_20pct_at_checkpoint"] is True


def test_measure_checkpoint_uses_last_session_at_or_before_the_target():
    # checkpoint target = 2026-09-08 (a Tuesday in this fixture), but the
    # only bars are 2026-09-04 and 2026-09-11 - must use 09-04, not leak
    # the 09-11 bar.
    entry = {
        "ticker": "AAA",
        "entry_date": "2026-09-01",
        "entry_close": "10.00",
        "entry_xbi_close": "100.00",
    }
    security = _bars(
        "AAA",
        [(date(2026, 9, 1), "10.00"), (date(2026, 9, 4), "11.00"), (date(2026, 9, 11), "99.00")],
    )
    benchmark = _bars(
        "XBI",
        [(date(2026, 9, 1), "100.00"), (date(2026, 9, 4), "101.00"), (date(2026, 9, 11), "500.00")],
    )
    result = measure_checkpoint(
        entry, 1, security_series=security, benchmark_series=benchmark, measured_on=date(2026, 9, 9)
    )
    assert result["session_date"] == "2026-09-04"
    assert result["close"] == "11.00"


def test_measure_checkpoint_captures_intraweek_peak_even_if_close_pulls_back():
    entry = {
        "ticker": "AAA",
        "entry_date": "2026-09-01",
        "entry_close": "10.00",
        "entry_xbi_close": "100.00",
    }
    security = _bars(
        "AAA",
        [
            (date(2026, 9, 1), "10.00"),
            (date(2026, 9, 3), "13.00"),  # +30% intraweek peak
            (date(2026, 9, 8), "10.50"),  # closes back down to +5%
        ],
    )
    benchmark = _bars("XBI", [(date(2026, 9, 1), "100.00"), (date(2026, 9, 8), "100.00")])
    result = measure_checkpoint(
        entry, 1, security_series=security, benchmark_series=benchmark, measured_on=date(2026, 9, 8)
    )
    assert result["return_pct"] == "5.00"
    assert result["hit_20pct_at_checkpoint"] is False
    assert result["peak_return_pct"] == "30.00"
    assert result["peak_hit_20pct"] is True
    assert result["peak_session_date"] == "2026-09-03"


def test_measure_checkpoint_raises_when_no_bars_available():
    # Simulates a live fetch window that started after the checkpoint
    # target (e.g. an entry old enough that the lookback no longer
    # covers it) - there is genuinely nothing to measure with, so this
    # must raise rather than silently use a later, wrong bar.
    entry = {
        "ticker": "AAA",
        "entry_date": "2026-09-01",
        "entry_close": "10.00",
        "entry_xbi_close": "100.00",
    }
    security = _bars("AAA", [(date(2026, 9, 15), "10.00")])
    benchmark = _bars("XBI", [(date(2026, 9, 15), "100.00")])
    with pytest.raises(ValueError, match="no bars available"):
        measure_checkpoint(
            entry,
            1,
            security_series=security,
            benchmark_series=benchmark,
            measured_on=date(2026, 9, 16),
        )


def test_summarize_reports_zero_measured_for_weeks_with_no_data():
    summary = summarize([])
    assert summary["entry_count"] == 0
    assert summary["by_checkpoint_week"]["1"]["measured_count"] == 0


def test_summarize_computes_hit_rate_and_mean_returns():
    entries = [
        {
            "checkpoints": {
                "1": {
                    "return_pct": "25.00",
                    "relative_return_pct": "20.00",
                    "hit_20pct_at_checkpoint": True,
                    "peak_hit_20pct": True,
                }
            }
        },
        {
            "checkpoints": {
                "1": {
                    "return_pct": "-5.00",
                    "relative_return_pct": "-8.00",
                    "hit_20pct_at_checkpoint": False,
                    "peak_hit_20pct": False,
                }
            }
        },
    ]
    summary = summarize(entries)
    week1 = summary["by_checkpoint_week"]["1"]
    assert week1["measured_count"] == 2
    assert week1["hit_20pct_count"] == 1
    assert week1["hit_20pct_rate_pct"] == "50.0"
    assert week1["mean_return_pct"] == "10.00"
    assert week1["mean_relative_return_pct"] == "6.00"
