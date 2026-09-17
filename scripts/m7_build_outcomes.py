"""Compute real point-in-time outcome/return records for the frozen
Milestone 7 cohort.

VALIDATION-AND-MILESTONES.md section 4 ("Outcome definitions") needs only
real historical price data, not a human scientific/catalyst reviewer - this
is objective post-event price math, computed by the already-frozen
calculate_outcome() in boe.historical_validation from real daily bars fetched
through the Alpaca Market Data API adapter (src/boe/ingestion/alpaca.py,
license-tracked and live-verified separately).

This says nothing about whether BOE-1.0.0 would have ranked these events
well - that requires a HistoricalDecisionLock, which requires a real human
scientific/catalyst reviewer this repository still does not have (see
docs/M7-HUMAN-REVIEW-BLOCKER.md). This script only records what actually
happened to price afterward.

Live network calls are unavoidable here (one per unique cohort ticker plus
the XBI benchmark) - unlike the rest of this repository's tests, this script
is not exercised by CI and is meant to be run manually with real credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.historical_validation import (  # noqa: E402
    CohortManifest,
    HistoricalEvent,
    PriceObservation,
    calculate_outcome,
)
from boe.ingestion.alpaca import MarketSeries, credentials_from_env, fetch_daily_bars  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/historical-outcomes.json"

BENCHMARK_SYMBOL = "XBI"
# Wide enough to comfortably cover T-1 before and 20 trading sessions after,
# through weekends and holiday clusters, without narrowly special-casing them.
PRE_EVENT_BUFFER_DAYS = 15
POST_EVENT_BUFFER_DAYS = 45
REQUEST_PACING_SECONDS = 0.15


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _observations(series: MarketSeries) -> tuple[PriceObservation, ...]:
    return tuple(
        PriceObservation(session_date=bar.session_date, adjusted_close=bar.adjusted_close)
        for bar in series.bars
    )


def _provenance_row(series: MarketSeries) -> dict[str, Any]:
    return {
        "symbol": series.symbol,
        "provider": series.provider,
        "raw_blob_sha256": series.raw_blob_sha256,
        "bar_count": len(series.bars),
        "first_session": series.bars[0].session_date.isoformat(),
        "last_session": series.bars[-1].session_date.isoformat(),
    }


def _fetch(
    symbol: str,
    events: list[HistoricalEvent],
    *,
    api_key_id: str,
    api_secret_key: str,
    data_url: str,
    retrieved_at: datetime,
) -> MarketSeries:
    start = min(e.event_at.date() for e in events) - timedelta(days=PRE_EVENT_BUFFER_DAYS)
    end = max(e.event_at.date() for e in events) + timedelta(days=POST_EVENT_BUFFER_DAYS)
    return fetch_daily_bars(
        symbol,
        start=start,
        end=end,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
        retrieved_at=retrieved_at,
    )


def build() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))
    api_key_id, api_secret_key, data_url = credentials_from_env()
    retrieved_at = datetime.now(UTC)

    events_by_ticker: dict[str, list[HistoricalEvent]] = {}
    for event in manifest.events:
        events_by_ticker.setdefault(event.ticker, []).append(event)

    provenance: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    benchmark_series = _fetch(
        BENCHMARK_SYMBOL,
        list(manifest.events),
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
        retrieved_at=retrieved_at,
    )
    provenance.append(_provenance_row(benchmark_series))
    benchmark_obs = _observations(benchmark_series)

    security_series_by_ticker: dict[str, MarketSeries] = {}
    for ticker, events in sorted(events_by_ticker.items()):
        time.sleep(REQUEST_PACING_SECONDS)
        try:
            series = _fetch(
                ticker,
                events,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                data_url=data_url,
                retrieved_at=retrieved_at,
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            failures.append(
                {
                    "ticker": ticker,
                    "event_ids": ",".join(sorted(e.event_id for e in events)),
                    "stage": "fetch",
                    "reason": str(exc),
                }
            )
            continue
        security_series_by_ticker[ticker] = series
        provenance.append(_provenance_row(series))

    outcomes: list[dict[str, Any]] = []
    for event in manifest.events:
        series = security_series_by_ticker.get(event.ticker)
        if series is None:
            continue
        try:
            outcome = calculate_outcome(
                event_id=event.event_id,
                event_at=event.event_at,
                security=_observations(series),
                benchmark=benchmark_obs,
                financing_through_t30=event.financing_t_minus_90_to_t_plus_30,
            )
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            failures.append(
                {
                    "ticker": event.ticker,
                    "event_ids": event.event_id,
                    "stage": "calculate_outcome",
                    "reason": str(exc),
                }
            )
            continue
        outcomes.append(outcome.model_dump(mode="json"))

    outcomes.sort(key=lambda o: str(o["event_id"]))
    failures.sort(key=lambda f: f["ticker"])
    return {
        "generator": "python scripts/m7_build_outcomes.py",
        "cohort_sha256": manifest.cohort_sha256,
        "benchmark_symbol": BENCHMARK_SYMBOL,
        "retrieved_at": retrieved_at.isoformat(),
        "event_count": len(manifest.events),
        "outcome_count": len(outcomes),
        "failed_count": len(failures),
        "failures": failures,
        "outcomes": outcomes,
        "market_data_provenance": provenance,
    }


def main() -> None:
    # No --check flag: unlike this repo's other M7 scripts, this one depends
    # on a live, time-of-fetch external price feed rather than purely on
    # already-frozen, already-committed inputs, so byte-exact reproducibility
    # is not a meaningful property to enforce here. Re-running always
    # re-fetches and overwrites with a fresh retrieval, which is the correct
    # behavior for live market data.
    argparse.ArgumentParser().parse_args()
    status = build()
    OUTPUT_PATH.write_text(render(status))
    print(
        f"computed {status['outcome_count']} of {status['event_count']} outcomes "
        f"({status['failed_count']} failed)"
    )
    for failure in status["failures"]:
        print(f"  FAILED {failure['ticker']} ({failure['event_ids']}): {failure['reason']}")


if __name__ == "__main__":
    main()
