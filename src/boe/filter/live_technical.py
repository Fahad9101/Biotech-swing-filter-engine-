"""Real, live (as-of-today) TECHNICAL facts for filter candidates.

Reuses the already-tested Milestone 6 technical engine
(src/boe/technicals.py) unchanged. Unlike the Milestone 7 historical
scripts, this uses fully split/dividend-adjusted bars (Alpaca
`adjustment=all` via fetch_daily_bars) rather than the point-in-time
unadjusted variant: the M7 scripts avoided adjusted bars specifically
because they leak knowledge of FUTURE corporate actions into a historical
T-30 cutoff. That concern does not apply here - "today" has no future to
leak, and using fully-adjusted closes gives a materially more accurate
trend/support read for a live snapshot.

base_success_target is always None (STRUCTURE subfactor partially
zeroed): it is a valuation-derived price target, and VALUATION is out of
scope for this tool for the same reason it is out of scope for BOE-1.0.0
here - no objectively-sourceable peak-sales/TAM assumption at this scale.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from boe.enums import DataState
from boe.ingestion.alpaca import fetch_daily_bars
from boe.market import MarketSeries
from boe.market_calendar import expected_latest_session_as_of
from boe.models import FactorScore, ScorecardContract
from boe.scoring import SubfactorEvidence
from boe.technicals import (
    MIN_REQUIRED_SESSIONS,
    build_technical_snapshot,
    score_snapshot_technicals,
)

FETCH_WINDOW_DAYS = 150
TECHNICAL_SUBFACTORS = ("TREND", "RELATIVE_STRENGTH", "ACCUMULATION", "STRUCTURE", "EXTENSION")


def fetch_live_series(
    symbol: str,
    *,
    as_of: datetime,
    api_key_id: str,
    api_secret_key: str,
    data_url: str,
) -> MarketSeries:
    """feed="iex": Alpaca's free plan rejects the full consolidated tape
    ("sip") for recent dates (confirmed live: 403 "subscription does not
    permit querying recent SIP data"). IEX is real but single-exchange -
    genuinely narrower volume coverage than SIP, not a fabricated
    substitute; M7's historical reconstruction used "sip" because it only
    ever queried old, non-recent dates where that restriction doesn't
    apply."""
    start = (as_of - timedelta(days=FETCH_WINDOW_DAYS)).date()
    end = as_of.date()
    return fetch_daily_bars(
        symbol,
        start=start,
        end=end,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
        feed="iex",
    )


def _evidence(series: MarketSeries, as_of_iso: str) -> dict[str, SubfactorEvidence]:
    evidence_id = uuid5(NAMESPACE_URL, f"filter-technical-{series.symbol}-{as_of_iso}")
    derived = SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=(
            f"Computed from real, live, fully-adjusted Alpaca daily bars for {series.symbol} "
            f"(raw_blob_sha256={series.raw_blob_sha256}) as of {as_of_iso}."
        ),
        evidence_ids=(evidence_id,),
    )
    missing = SubfactorEvidence(
        data_state=DataState.MISSING,
        rationale="base_success_target is not computed - VALUATION is out of scope.",
        evidence_ids=(),
    )
    return {code: (missing if code == "STRUCTURE" else derived) for code in TECHNICAL_SUBFACTORS}


def live_technical_score(
    *,
    security_series: MarketSeries,
    benchmark_series: MarketSeries,
    as_of: datetime,
    rules: ScorecardContract,
) -> tuple[FactorScore, dict[str, Any]]:
    expected_latest_session = expected_latest_session_as_of(as_of)
    snapshot = build_technical_snapshot(
        security_series,
        benchmark_series,
        as_of=as_of,
        expected_latest_session=expected_latest_session,
    )
    evidence = _evidence(security_series, as_of.isoformat())
    factor_score = score_snapshot_technicals(
        snapshot, base_success_target=None, evidence=evidence, rules=rules
    )
    facts = {
        "close": str(snapshot.close),
        "sma20": str(snapshot.sma20),
        "sma50": str(snapshot.sma50),
        "rsi14": str(snapshot.rsi14),
        "xbi_relative_return_20d_pct": str(snapshot.xbi_relative_return_20d_pct),
        "stale": snapshot.stale,
        "latest_session": snapshot.session_date.isoformat(),
    }
    return factor_score, facts


__all__ = [
    "FETCH_WINDOW_DAYS",
    "MIN_REQUIRED_SESSIONS",
    "fetch_live_series",
    "live_technical_score",
]
