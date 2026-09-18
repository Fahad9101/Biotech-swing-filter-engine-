"""Build real point-in-time TECHNICAL factor scores at T-30 for the frozen
Milestone 7 cohort, using real Alpaca price data and the already-built,
already-tested Milestone 6 technical engine (src/boe/technicals.py,
src/boe/scoring.py::score_technicals). No new data source, no new scoring
logic - this wires up existing, frozen machinery with real inputs for the
first time at this historical scale.

TECHNICAL is fully computable from objective OHLCV data alone (SMA20/SMA50,
RSI14, XBI-relative return, up/down dollar-volume ratio, OBV slope,
SMA-based support) - no human review, no commercial/valuation assumption
needed, unlike SCIENCE or VALUATION. The one input this script does NOT
supply is base_success_target (a valuation-derived price target used only by
the STRUCTURE subfactor's "room to target" check): VALUATION is out of scope
for this project (see docs/M7-OBJECTIVE-METHODOLOGY.md and this script's own
methodology notes below), so it is passed as None, which conservatively
zeroes that one specific structure check rather than fabricating a target.

Two real bugs were caught and fixed while building this, not by inspection
but by running against live data and checking a surprising result against
what actually happened:

1. scripts/m7_build_outcomes.py's fetch_daily_bars() (adjustment=all)
   reflects every split and dividend known TODAY, including ones after any
   historical T-30 cutoff - correct for computing real total returns after
   the fact, but exactly the look-ahead leakage
   boe.market.point_in_time_series() exists to catch, and it correctly
   rejected it here. Fixed by fetch_point_in_time_bars() (boe.ingestion.
   alpaca), which requests genuinely unadjusted (adjustment=raw) bars.

2. A first version flagged 6 events as "possible splits" using a price-ratio
   heuristic (a close-to-close move near a round ratio). Checking two of
   them against real data found they were not splits at all: SRPT's
   ~51% one-day move (Jan 2021, ratio ~0.4871) was a genuine, real ~5x-
   volume crash - unrelated to either of SRPT's two cohort events, whose
   real T-30 windows sit in 2019 and 2023, nowhere near it (the heuristic
   was also, separately, scanning each ticker's whole multi-event fetch
   range instead of each event's own window). IMMU's ~2x move (April 2020)
   coincides with a real, well-documented positive Trodelvy data rally, not
   a split. Both are exactly the kind of large, genuine, catalyst-driven
   move this project studies - wrongly excluding them would have been a
   real cost, not a safe default.

   Replaced with an authoritative check: fetch_split_adjusted_closes()
   (adjustment=split) for the same range, compare pointwise against the
   genuinely unadjusted closes already fetched, and find where the ratio
   between them actually steps - that is a real split's effective date,
   not a guess. Checked per event, against only that event's own relevant
   window, not the ticker's whole fetch range. See _split_boundary_dates()
   below.

Live network calls: real Alpaca fetches, one per unique ticker plus XBI -
not exercised by CI, same reasoning as scripts/m7_build_outcomes.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.contracts import load_scorecard  # noqa: E402
from boe.enums import DataState  # noqa: E402
from boe.historical_validation import CohortManifest, HistoricalEvent  # noqa: E402
from boe.ingestion.alpaca import (  # noqa: E402
    MarketSeries,
    credentials_from_env,
    fetch_point_in_time_bars,
    fetch_split_adjusted_closes,
)
from boe.market_calendar import trading_sessions  # noqa: E402
from boe.scoring import SubfactorEvidence  # noqa: E402
from boe.technicals import (  # noqa: E402
    MIN_REQUIRED_SESSIONS,
    build_technical_snapshot,
    score_snapshot_technicals,
)

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/technical-snapshots.json"
SCORECARD_PATH = ROOT / "contracts/boe-scorecard.v1.0.0.json"

BENCHMARK_SYMBOL = "XBI"
SNAPSHOT_LOOKBACK_DAYS = 30  # T-30, the primary validation snapshot
# Wide enough to comfortably clear the 60-aligned-session floor even around
# holiday-heavy stretches (60 sessions is roughly 85-90 calendar days).
FETCH_WINDOW_DAYS = 150
REQUEST_PACING_SECONDS = 0.15

TECHNICAL_SUBFACTORS = ("TREND", "RELATIVE_STRENGTH", "ACCUMULATION", "STRUCTURE", "EXTENSION")

# A real split's ratio step is exact to the corporate action (e.g. exactly
# 0.5 for a 2-for-1); 1% comfortably clears floating-point/rounding noise
# while staying far below the smallest real split ratio step.
_SPLIT_RATIO_STEP_TOLERANCE = Decimal("0.01")


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _split_boundary_dates(
    raw_closes: dict[Any, Decimal], split_adjusted_closes: dict[Any, Decimal]
) -> tuple[Any, ...]:
    """Real split effective dates: where the split-adjusted/raw close ratio
    actually steps, not a price-move heuristic. Two adjustment styles for
    the same real trading days either agree (no split ever touches that
    date) or diverge by the real corporate-action ratio - nothing is
    guessed from price action alone."""
    common_dates = sorted(set(raw_closes) & set(split_adjusted_closes))
    boundaries = []
    previous_ratio: Decimal | None = None
    for session_date in common_dates:
        raw = raw_closes[session_date]
        if raw <= 0:
            continue
        ratio = split_adjusted_closes[session_date] / raw
        if previous_ratio is not None and abs(ratio - previous_ratio) > (
            previous_ratio * _SPLIT_RATIO_STEP_TOLERANCE
        ):
            boundaries.append(session_date)
        previous_ratio = ratio
    return tuple(boundaries)


def _evidence(series: MarketSeries, as_of_iso: str) -> dict[str, SubfactorEvidence]:
    evidence_id = uuid5(NAMESPACE_URL, f"m7-technical-{series.symbol}-{as_of_iso}")
    derived = SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=(
            f"Computed from real Alpaca daily bars for {series.symbol} "
            f"(raw_blob_sha256={series.raw_blob_sha256}), point-in-time filtered to {as_of_iso}."
        ),
        evidence_ids=(evidence_id,),
    )
    # STRUCTURE always scores 0/2: it needs base_success_target, a
    # valuation-derived price target this project does not compute (see
    # module docstring) - genuinely no value, not merely unobserved.
    missing = SubfactorEvidence(
        data_state=DataState.MISSING,
        rationale="base_success_target is not computed - VALUATION is out of scope.",
        evidence_ids=(),
    )
    return {code: (missing if code == "STRUCTURE" else derived) for code in TECHNICAL_SUBFACTORS}


def _fetch(
    symbol: str,
    events: list[HistoricalEvent],
    *,
    api_key_id: str,
    api_secret_key: str,
    data_url: str,
) -> MarketSeries:
    latest_t30 = max(e.event_at - timedelta(days=SNAPSHOT_LOOKBACK_DAYS) for e in events)
    earliest_t30 = min(e.event_at - timedelta(days=SNAPSHOT_LOOKBACK_DAYS) for e in events)
    start = (earliest_t30 - timedelta(days=FETCH_WINDOW_DAYS)).date()
    end = latest_t30.date()
    return fetch_point_in_time_bars(
        symbol,
        start=start,
        end=end,
        as_of=latest_t30,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
    )


def build() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))
    rules = load_scorecard(SCORECARD_PATH).contract
    api_key_id, api_secret_key, data_url = credentials_from_env()

    events_by_ticker: dict[str, list[HistoricalEvent]] = {}
    for event in manifest.events:
        events_by_ticker.setdefault(event.ticker, []).append(event)

    benchmark_series = _fetch(
        BENCHMARK_SYMBOL,
        list(manifest.events),
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
    )

    snapshots: list[dict[str, Any]] = []
    insufficient_history: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, Any]] = []
    possible_splits: list[dict[str, Any]] = []

    for ticker, events in sorted(events_by_ticker.items()):
        time.sleep(REQUEST_PACING_SECONDS)
        try:
            security_series = _fetch(
                ticker,
                events,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                data_url=data_url,
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            for event in events:
                fetch_failures.append(
                    {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                )
            continue

        time.sleep(REQUEST_PACING_SECONDS)
        try:
            fetch_start = min(bar.session_date for bar in security_series.bars)
            fetch_end = max(bar.session_date for bar in security_series.bars)
            split_adjusted_closes = fetch_split_adjusted_closes(
                ticker,
                start=fetch_start,
                end=fetch_end,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                data_url=data_url,
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            for event in events:
                fetch_failures.append(
                    {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                )
            continue

        raw_closes = {bar.session_date: bar.close for bar in security_series.bars}
        split_boundaries = _split_boundary_dates(raw_closes, split_adjusted_closes)

        for event in events:
            as_of = event.event_at - timedelta(days=SNAPSHOT_LOOKBACK_DAYS)
            window_end = as_of.date()
            window_start = as_of.date() - timedelta(days=FETCH_WINDOW_DAYS)

            in_window_boundaries = [d for d in split_boundaries if window_start <= d <= window_end]
            if in_window_boundaries:
                possible_splits.append(
                    {
                        "event_id": event.event_id,
                        "ticker": ticker,
                        "reason": (
                            f"real split effective date(s) {in_window_boundaries} fall within "
                            f"this event's [{window_start}, {window_end}] lookback window - "
                            "confirmed by comparing Alpaca's raw and split-adjusted closes, "
                            "not a price-move heuristic"
                        ),
                    }
                )
                continue

            expected_latest_session = trading_sessions(window_start, window_end)[-1]
            try:
                snapshot = build_technical_snapshot(
                    security_series,
                    benchmark_series,
                    as_of=as_of,
                    expected_latest_session=expected_latest_session,
                )
            except ValueError as exc:
                insufficient_history.append(
                    {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                )
                continue
            factor_score = score_snapshot_technicals(
                snapshot,
                base_success_target=None,
                evidence=_evidence(security_series, as_of.date().isoformat()),
                rules=rules,
            )
            snapshots.append(
                {
                    "event_id": event.event_id,
                    "ticker": ticker,
                    "t_minus_30": as_of.date().isoformat(),
                    "session_date": snapshot.session_date.isoformat(),
                    "close": str(snapshot.close),
                    "sma20": str(snapshot.sma20),
                    "sma50": str(snapshot.sma50),
                    "rsi14": str(snapshot.rsi14),
                    "xbi_relative_return_20d_pct": str(snapshot.xbi_relative_return_20d_pct),
                    "up_down_dollar_volume_ratio": str(snapshot.up_down_dollar_volume_ratio),
                    "obv_slope_positive": snapshot.obv_slope > 0,
                    "support": str(snapshot.support) if snapshot.support else None,
                    "technical_factor_points": factor_score.points,
                    "technical_factor_max_points": factor_score.max_points,
                }
            )

    snapshots.sort(key=lambda r: str(r["event_id"]))
    insufficient_history.sort(key=lambda r: str(r["event_id"]))
    fetch_failures.sort(key=lambda r: str(r["event_id"]))
    possible_splits.sort(key=lambda r: str(r["event_id"]))

    return {
        "generator": "python scripts/m7_build_technical_snapshots.py",
        "cohort_sha256": manifest.cohort_sha256,
        "snapshot_label": "T_MINUS_30",
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "event_count": len(manifest.events),
        "snapshot_count": len(snapshots),
        "insufficient_history_count": len(insufficient_history),
        "fetch_failure_count": len(fetch_failures),
        "possible_split_count": len(possible_splits),
        "snapshots": snapshots,
        "insufficient_history": insufficient_history,
        "fetch_failures": fetch_failures,
        "possible_splits": possible_splits,
        "methodology_notes": [
            f"Requires >= {MIN_REQUIRED_SESSIONS} aligned trading sessions before T-30 - "
            "the same frozen floor build_technical_snapshot() enforces for live ranking.",
            "base_success_target is always None: that field is a valuation-derived price "
            "target, and VALUATION (rNPV-based) is out of scope for this project - it needs "
            "real peak-sales/TAM assumptions per indication that cannot be objectively "
            "sourced at this scale without either extensive new per-indication market "
            "research or fabricated numbers, the same category of problem SCIENCE has. "
            "This conservatively zeroes only the STRUCTURE subfactor's target-room check, "
            "not the whole factor.",
            "Uses genuinely unadjusted (adjustment=raw) Alpaca bars, not the adjustment=all "
            "series scripts/m7_build_outcomes.py uses for real returns - that series reflects "
            "corporate actions known today, which would leak future information into a T-30 "
            "historical snapshot (boe.market.point_in_time_series() correctly rejects it).",
            "Real split effective dates are found by comparing Alpaca's raw and "
            "split-adjusted closes for the same sessions and locating where their ratio "
            "actually steps - not a price-move heuristic, which an earlier version of this "
            "script used and which produced real false positives (a genuine SRPT crash and a "
            "genuine IMMU rally, both wrongly flagged). Checked per event against only that "
            "event's own lookback window, not the ticker's whole multi-event fetch range - an "
            "unrelated real split elsewhere in a ticker's history no longer excludes an "
            "event whose own window never touches it.",
        ],
    }


def main() -> None:
    argparse.ArgumentParser().parse_args()
    status = build()
    OUTPUT_PATH.write_text(render(status))
    print(
        json.dumps(
            {
                "event_count": status["event_count"],
                "snapshot_count": status["snapshot_count"],
                "insufficient_history_count": status["insufficient_history_count"],
                "fetch_failure_count": status["fetch_failure_count"],
                "possible_split_count": status["possible_split_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
