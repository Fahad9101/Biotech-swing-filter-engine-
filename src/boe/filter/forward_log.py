"""FORWARD-LOG-1.0: measures how SHORTLIST-1.0 actually performs.

This is the machinery that turns "does the shortlist work?" from a guess
into a question with a real answer after 10-12 weeks of live data.

Design rules, all deliberate:
  - An entry is created once, the first time a candidate appears in the
    shortlist, and its entry_close / entry_xbi_close are frozen forever -
    never recomputed on a later run, even if the same candidate is still
    shortlisted next week. This is what makes "how did the shortlist do"
    answerable instead of a moving target.
  - Checkpoints (1, 2, 4, 8, 12 weeks after entry_date) are measured once,
    when due, from real daily bars fetched for that specific window -
    never estimated, never backfilled from a different date.
  - Nothing here is scored, ranked, or used to filter future runs. It
    exists to test SHORTLIST-1.0 itself against real outcomes over a
    genuinely non-repeatable window. "No edge found" is a legitimate,
    expected-to-be-possible result this log exists to surface honestly -
    same posture as the Milestone 7 historical validation.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from boe.market import MarketBar, MarketSeries

FORWARD_LOG_DEFINITION = "FORWARD-LOG-1.0"
CHECKPOINT_WEEKS: tuple[int, ...] = (1, 2, 4, 8, 12)
HIT_THRESHOLD_PCT = Decimal("20")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001 - any bad input degrades to "unknown"
        return None
    return parsed if parsed.is_finite() else None


def new_entry(
    row: dict[str, Any],
    *,
    as_of: datetime,
    benchmark_close: Decimal,
    shortlist_definition: str,
    shortlist_parameters: dict[str, Any],
) -> dict[str, Any]:
    """Build one frozen entry-day snapshot for a shortlisted candidate.

    Raises ValueError rather than logging a fabricated entry price when
    the candidate has no real close - same "never guess" posture as the
    rest of this tool.
    """
    entry_close = _decimal((row.get("technical_facts") or {}).get("close"))
    if entry_close is None:
        raise ValueError(f"cannot log a forward entry for {row['ticker']} without a real close")
    return {
        "candidate_id": row["candidate_id"],
        "ticker": row["ticker"],
        "company": row.get("company"),
        "catalyst_type": row["catalyst_type"],
        "window_start": row["window_start"],
        "window_end": row["window_end"],
        "date_precision": row["date_precision"],
        "tier": row["tier"],
        "source_url": row.get("source_url"),
        "forward_log_definition": FORWARD_LOG_DEFINITION,
        "shortlist_definition": shortlist_definition,
        "shortlist_parameters": shortlist_parameters,
        "entry_date": as_of.date().isoformat(),
        "entry_recorded_at": as_of.isoformat(),
        "entry_close": str(entry_close),
        "entry_xbi_close": str(benchmark_close),
        "checkpoints": {},
    }


def record_new_entries(
    existing: list[dict[str, Any]],
    shortlist_rows: list[dict[str, Any]],
    *,
    as_of: datetime,
    benchmark_close: Decimal,
    shortlist_definition: str,
    shortlist_parameters: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Append one entry per candidate_id not already logged. Existing
    entries are returned unmodified - re-running this on a candidate
    still in this week's shortlist must never touch its frozen entry
    price.

    SHORTLIST-1.0 deliberately keeps a candidate whose technicals are
    unavailable (flagged, not dropped - see boe.filter.shortlist), so a
    shortlisted row is not guaranteed to have a real close. Rather than
    fabricate an entry price for it (new_entry() correctly refuses to),
    that single candidate is skipped here - not logged this run, not
    excluded either: it will be picked up on a later run once real
    technical data is available for it, same as any other data gap
    elsewhere in this tool.
    """
    known_ids = {entry["candidate_id"] for entry in existing}
    added: list[str] = []
    skipped: list[dict[str, Any]] = []
    updated = list(existing)
    for row in shortlist_rows:
        if row["candidate_id"] in known_ids:
            continue
        try:
            entry = new_entry(
                row,
                as_of=as_of,
                benchmark_close=benchmark_close,
                shortlist_definition=shortlist_definition,
                shortlist_parameters=shortlist_parameters,
            )
        except ValueError as exc:
            skipped.append(
                {"candidate_id": row["candidate_id"], "ticker": row["ticker"], "reason": str(exc)}
            )
            continue
        updated.append(entry)
        known_ids.add(entry["candidate_id"])
        added.append(entry["candidate_id"])
    return updated, added, skipped


def due_checkpoints(entry: dict[str, Any], *, today: date) -> list[int]:
    """Weeks that are both due (entry_date + N weeks <= today) and not
    already measured."""
    entry_date = date.fromisoformat(entry["entry_date"])
    measured = {int(week) for week in entry.get("checkpoints", {})}
    return [
        week
        for week in CHECKPOINT_WEEKS
        if week not in measured and today >= entry_date + timedelta(weeks=week)
    ]


def measure_checkpoint(
    entry: dict[str, Any],
    week: int,
    *,
    security_series: MarketSeries,
    benchmark_series: MarketSeries,
    measured_on: date,
) -> dict[str, Any]:
    """Real return at the checkpoint date, plus the real intraweek peak
    (a stock can cross +20% mid-week and close back down - measuring only
    the checkpoint-day close would silently miss that)."""
    entry_date = date.fromisoformat(entry["entry_date"])
    checkpoint_target = entry_date + timedelta(weeks=week)
    security_through_checkpoint = tuple(
        bar for bar in security_series.bars if bar.session_date <= checkpoint_target
    )
    benchmark_through_checkpoint = tuple(
        bar for bar in benchmark_series.bars if bar.session_date <= checkpoint_target
    )
    if not security_through_checkpoint or not benchmark_through_checkpoint:
        raise ValueError(
            f"no bars available at or before checkpoint {checkpoint_target} for {entry['ticker']}"
        )
    security_latest = security_through_checkpoint[-1]
    benchmark_latest = benchmark_through_checkpoint[-1]
    entry_close = Decimal(entry["entry_close"])
    entry_xbi_close = Decimal(entry["entry_xbi_close"])

    return_pct = (security_latest.adjusted_close / entry_close - 1) * 100
    xbi_return_pct = (benchmark_latest.adjusted_close / entry_xbi_close - 1) * 100

    window_bars = tuple(
        bar for bar in security_series.bars if entry_date <= bar.session_date <= checkpoint_target
    )
    peak_bar: MarketBar = max(
        window_bars, key=lambda bar: bar.adjusted_close, default=security_latest
    )
    peak_return_pct = (peak_bar.adjusted_close / entry_close - 1) * 100

    return {
        "week": week,
        "measured_at": measured_on.isoformat(),
        "session_date": security_latest.session_date.isoformat(),
        "close": str(security_latest.adjusted_close),
        "xbi_close": str(benchmark_latest.adjusted_close),
        "return_pct": str(return_pct.quantize(Decimal("0.01"))),
        "xbi_return_pct": str(xbi_return_pct.quantize(Decimal("0.01"))),
        "relative_return_pct": str((return_pct - xbi_return_pct).quantize(Decimal("0.01"))),
        "hit_20pct_at_checkpoint": return_pct >= HIT_THRESHOLD_PCT,
        "peak_session_date": peak_bar.session_date.isoformat(),
        "peak_return_pct": str(peak_return_pct.quantize(Decimal("0.01"))),
        "peak_hit_20pct": peak_return_pct >= HIT_THRESHOLD_PCT,
    }


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate hit-rate/return stats per checkpoint week, among entries
    that have actually reached that checkpoint. Small samples are
    reported as-is (with their count) rather than hidden - this is meant
    to be read skeptically until the sample is large enough to mean
    anything, not dressed up as a verdict."""
    by_week: dict[int, dict[str, Any]] = {}
    for week in CHECKPOINT_WEEKS:
        measured = [
            entry["checkpoints"][str(week)]
            for entry in entries
            if str(week) in entry.get("checkpoints", {})
        ]
        if not measured:
            by_week[week] = {"measured_count": 0}
            continue
        returns = [Decimal(m["return_pct"]) for m in measured]
        relative = [Decimal(m["relative_return_pct"]) for m in measured]
        hits = sum(1 for m in measured if m["hit_20pct_at_checkpoint"])
        peak_hits = sum(1 for m in measured if m["peak_hit_20pct"])
        by_week[week] = {
            "measured_count": len(measured),
            "hit_20pct_count": hits,
            "hit_20pct_rate_pct": str(
                (Decimal(hits) / len(measured) * 100).quantize(Decimal("0.1"))
            ),
            "peak_hit_20pct_count": peak_hits,
            "peak_hit_20pct_rate_pct": str(
                (Decimal(peak_hits) / len(measured) * 100).quantize(Decimal("0.1"))
            ),
            "mean_return_pct": str(
                (sum(returns, Decimal("0")) / len(returns)).quantize(Decimal("0.01"))
            ),
            "mean_relative_return_pct": str(
                (sum(relative, Decimal("0")) / len(relative)).quantize(Decimal("0.01"))
            ),
        }
    return {
        "forward_log_definition": FORWARD_LOG_DEFINITION,
        "entry_count": len(entries),
        "by_checkpoint_week": {str(week): stats for week, stats in by_week.items()},
    }


__all__ = [
    "CHECKPOINT_WEEKS",
    "FORWARD_LOG_DEFINITION",
    "HIT_THRESHOLD_PCT",
    "due_checkpoints",
    "measure_checkpoint",
    "new_entry",
    "record_new_entries",
    "summarize",
]
