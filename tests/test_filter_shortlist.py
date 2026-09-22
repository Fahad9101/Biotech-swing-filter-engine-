"""Regressions for SHORTLIST-1.0 - the fit filter over the raw watchlist.

Every rule here is a structural fact (time fit, size, tradeability), never
a predictive score: these tests exist to pin the thresholds and the
dedupe/unknown-handling behavior, not to claim any edge.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from boe.filter.shortlist import (
    LIQUIDITY_BELOW_MIN,
    MARKET_CAP_ABOVE_MAX,
    MARKET_CAP_BELOW_MIN,
    MARKET_CAP_UNKNOWN,
    OUTSIDE_TIME_WINDOW,
    PRICE_BELOW_MIN,
    TECHNICALS_UNAVAILABLE,
    ShortlistParameters,
    apply_shortlist,
    dedupe_catalysts,
    market_cap,
    time_tier,
)

TODAY = date(2026, 9, 22)


def _row(
    ticker: str,
    *,
    window_start: str,
    window_end: str,
    precision: str,
    close: str | None = "10.00",
    shares: str | None = "50000000",
    dollar_volume: str | None = "500000",
    stale: bool = False,
    filing_date: str = "2026-09-01",
    source_url: str = "https://www.sec.gov/example.htm",
    catalyst_type: str = "REG_DECISION",
) -> dict:
    return {
        "candidate_id": f"{ticker}-{catalyst_type}-{window_start}",
        "ticker": ticker,
        "company": f"{ticker} Inc.",
        "catalyst_type": catalyst_type,
        "window_start": window_start,
        "window_end": window_end,
        "date_precision": precision,
        "filing_date": filing_date,
        "source_url": source_url,
        "source_sentence": "example",
        "cash_dilution_facts": {"shares_outstanding": shares} if shares is not None else None,
        "technical_facts": (
            {
                "close": close,
                "median_dollar_volume_20d": dollar_volume,
                "stale": stale,
            }
            if close is not None
            else None
        ),
    }


def test_time_tier_exact_date_inside_horizon_is_tier_one():
    row = _row("AAA", window_start="2026-10-01", window_end="2026-10-01", precision="EXACT_DATE")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 1


def test_time_tier_exact_date_before_today_is_tier_zero():
    row = _row("AAA", window_start="2026-09-01", window_end="2026-09-01", precision="EXACT_DATE")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 0


def test_time_tier_exact_date_beyond_horizon_is_tier_zero():
    row = _row("AAA", window_start="2027-01-01", window_end="2027-01-01", precision="EXACT_DATE")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 0


def test_time_tier_quarter_overlapping_horizon_is_tier_two():
    row = _row("AAA", window_start="2026-10-01", window_end="2026-12-31", precision="QUARTER")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 2


def test_time_tier_quarter_entirely_past_is_tier_zero():
    row = _row("AAA", window_start="2026-01-01", window_end="2026-03-31", precision="QUARTER")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 0


def test_time_tier_year_only_is_always_tier_zero():
    row = _row("AAA", window_start="2026-01-01", window_end="2026-12-31", precision="YEAR")
    assert time_tier(row, today=TODAY, parameters=ShortlistParameters()) == 0


def test_market_cap_computes_from_close_times_shares():
    row = _row(
        "AAA",
        window_start="2026-10-01",
        window_end="2026-10-01",
        precision="EXACT_DATE",
        close="20.00",
        shares="1000000",
    )
    assert market_cap(row) == Decimal("20000000")


def test_market_cap_is_none_when_shares_missing():
    row = _row(
        "AAA",
        window_start="2026-10-01",
        window_end="2026-10-01",
        precision="EXACT_DATE",
        shares=None,
    )
    assert market_cap(row) is None


def test_dedupe_catalysts_keeps_latest_filing_and_counts_sources():
    older = _row(
        "AAA",
        window_start="2026-10-01",
        window_end="2026-10-01",
        precision="EXACT_DATE",
        filing_date="2026-08-01",
        source_url="https://www.sec.gov/old.htm",
    )
    newer = _row(
        "AAA",
        window_start="2026-10-01",
        window_end="2026-10-01",
        precision="EXACT_DATE",
        filing_date="2026-09-01",
        source_url="https://www.sec.gov/new.htm",
    )
    merged = dedupe_catalysts([older, newer])
    assert len(merged) == 1
    assert merged[0]["source_url"] == "https://www.sec.gov/new.htm"
    assert merged[0]["source_count"] == 2
    assert merged[0]["all_source_urls"] == [
        "https://www.sec.gov/new.htm",
        "https://www.sec.gov/old.htm",
    ]


def test_dedupe_catalysts_keeps_distinct_catalysts_separate():
    same_ticker_different_window = [
        _row("AAA", window_start="2026-10-01", window_end="2026-10-01", precision="EXACT_DATE"),
        _row("AAA", window_start="2026-11-01", window_end="2026-11-01", precision="EXACT_DATE"),
    ]
    merged = dedupe_catalysts(same_ticker_different_window)
    assert len(merged) == 2


def test_apply_shortlist_includes_a_well_formed_tier_one_row():
    rows = [
        _row("GOOD", window_start="2026-10-01", window_end="2026-10-01", precision="EXACT_DATE")
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is True
    assert result[0]["tier"] == 1
    assert result[0]["exclusion_reasons"] == []


def test_apply_shortlist_excludes_outside_time_window():
    rows = [
        _row("LATE", window_start="2027-06-01", window_end="2027-06-01", precision="EXACT_DATE")
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is False
    assert OUTSIDE_TIME_WINDOW in result[0]["exclusion_reasons"]


def test_apply_shortlist_excludes_price_below_minimum():
    rows = [
        _row(
            "PENNY",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            close="0.50",
        )
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is False
    assert PRICE_BELOW_MIN in result[0]["exclusion_reasons"]


def test_apply_shortlist_excludes_illiquid_names():
    rows = [
        _row(
            "THIN",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            dollar_volume="1000",
        )
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is False
    assert LIQUIDITY_BELOW_MIN in result[0]["exclusion_reasons"]


def test_apply_shortlist_excludes_market_cap_below_minimum():
    rows = [
        _row(
            "TINY",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            close="1.00",
            shares="1000000",
        )
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is False
    assert MARKET_CAP_BELOW_MIN in result[0]["exclusion_reasons"]


def test_apply_shortlist_excludes_mega_cap():
    rows = [
        _row(
            "MEGA",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            close="150.00",
            shares="2000000000",
        )
    ]
    result = apply_shortlist(rows, today=TODAY)
    assert result[0]["shortlisted"] is False
    assert MARKET_CAP_ABOVE_MAX in result[0]["exclusion_reasons"]


def test_apply_shortlist_flags_unknown_technicals_without_excluding():
    rows = [
        _row(
            "NODATA",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            close=None,
        )
    ]
    result = apply_shortlist(rows, today=TODAY)
    # cannot verify price/liquidity floors without technicals, so this
    # can't be excluded on those grounds either - it stays shortlisted
    # (kept, not silently dropped) but visibly flagged as unverified,
    # per this module's "unknown is not a failure" rule.
    assert TECHNICALS_UNAVAILABLE in result[0]["flags"]
    assert MARKET_CAP_UNKNOWN in result[0]["flags"]
    assert result[0]["shortlisted"] is True
    assert result[0]["exclusion_reasons"] == []


def test_apply_shortlist_sorts_shortlisted_first_then_tier_then_soonest():
    rows = [
        _row("QTR", window_start="2026-10-01", window_end="2026-12-31", precision="QUARTER"),
        _row(
            "EXCLUDED", window_start="2027-06-01", window_end="2027-06-01", precision="EXACT_DATE"
        ),
        _row("SOON", window_start="2026-09-25", window_end="2026-09-25", precision="EXACT_DATE"),
    ]
    result = apply_shortlist(rows, today=TODAY)
    tickers = [r["ticker"] for r in result]
    assert tickers == ["SOON", "QTR", "EXCLUDED"]


def test_apply_shortlist_respects_custom_parameters():
    rows = [
        _row(
            "MIDCAP",
            window_start="2026-10-01",
            window_end="2026-10-01",
            precision="EXACT_DATE",
            close="5.00",
            shares="2000000",
        )
    ]
    default_result = apply_shortlist(rows, today=TODAY)
    assert MARKET_CAP_BELOW_MIN in default_result[0]["exclusion_reasons"]

    lenient = ShortlistParameters(min_market_cap=Decimal("1000000"))
    lenient_result = apply_shortlist(rows, today=TODAY, parameters=lenient)
    assert lenient_result[0]["shortlisted"] is True
