"""Live catalyst filter scan.

Discovers real, company-self-disclosed forward biotech catalysts (SEC
EDGAR full-text search - see boe.filter.discovery) and attaches real
CATALYST, CASH_DILUTION, TECHNICAL, and objective-PoS facts to each one,
all computed "as of now" using the same already-tested factor-scoring
machinery as BOE-1.0.0.

This is explicitly NOT a recommendation: no SCIENCE review, no VALUATION,
no gates, no classification, no buy/sell signal. It narrows a universe of
real, timely, structurally-sane catalyst setups for a human's own chart
and science research - nothing here should be read as a verdict. The
watchlist is sorted chronologically (soonest real catalyst first), not
by any combined score: the historical validation of these same combined
factors (see the milestone-7-historical-validation branch) found ~0
correlation with actual returns, so ranking by a "combined score" here
would imply predictive power this tool has not demonstrated.

Live network calls throughout (EDGAR full-text search, SEC XBRL,
Alpaca). Not exercised by CI; run manually with real credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.contracts import load_scorecard  # noqa: E402
from boe.filter.discovery import discover_candidates_from_hit, discover_filing_hits  # noqa: E402
from boe.filter.extraction import DiscoveredCatalyst  # noqa: E402
from boe.filter.live_catalyst import live_catalyst_score  # noqa: E402
from boe.filter.live_financials import ForeignPrivateIssuer, live_cash_dilution_score  # noqa: E402
from boe.filter.live_technical import fetch_live_series, live_technical_score  # noqa: E402
from boe.financials import FinancialDataError  # noqa: E402
from boe.ingestion.alpaca import credentials_from_env  # noqa: E402
from boe.ingestion.http import PublicDataClient  # noqa: E402
from boe.objective_pos_methodology import estimate_objective_pos  # noqa: E402

SCORECARD_PATH = ROOT / "contracts/boe-scorecard.v1.0.0.json"
OUTPUT_PATH = ROOT / "screening/watchlist.json"
SUMMARY_PATH = ROOT / "screening/watchlist-summary.json"

USER_AGENT = (
    "BOE-Filter live-screening research https://github.com/Fahad9101/Biotech-swing-filter-engine-"
)
BENCHMARK_SYMBOL = "XBI"
DEFAULT_LOOKBACK_DAYS = 90
REQUEST_PACING_SECONDS = 0.15


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def _group_by_ticker(
    candidates: list[DiscoveredCatalyst],
) -> dict[str, list[DiscoveredCatalyst]]:
    grouped: dict[str, list[DiscoveredCatalyst]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.ticker, []).append(candidate)
    return grouped


def build(
    *,
    start_date: date,
    end_date: date,
    as_of: datetime | None = None,
    client: PublicDataClient | None = None,
    api_key_id: str | None = None,
    api_secret_key: str | None = None,
    data_url: str | None = None,
) -> dict[str, Any]:
    as_of = as_of or datetime.now(UTC)
    rules = load_scorecard(SCORECARD_PATH).contract
    if api_key_id is None or api_secret_key is None or data_url is None:
        api_key_id, api_secret_key, data_url = credentials_from_env()

    owns_client = client is None
    active_client = client or PublicDataClient(USER_AGENT)

    watchlist: list[dict[str, Any]] = []
    excluded_foreign_issuer: list[dict[str, Any]] = []
    discovery_failures: list[dict[str, Any]] = []
    financial_data_gaps: list[dict[str, Any]] = []
    technical_data_gaps: list[dict[str, Any]] = []

    try:
        hits = discover_filing_hits(active_client, start_date=start_date, end_date=end_date)
        all_candidates: list[DiscoveredCatalyst] = []
        for hit in hits:
            time.sleep(REQUEST_PACING_SECONDS)
            try:
                all_candidates.extend(discover_candidates_from_hit(active_client, hit))
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                discovery_failures.append(
                    {"ticker": hit.ticker, "source_url": hit.document_url, "reason": str(exc)}
                )

        candidates_by_ticker = _group_by_ticker(all_candidates)
        if not candidates_by_ticker:
            return _result(
                start_date,
                end_date,
                as_of,
                watchlist,
                excluded_foreign_issuer,
                discovery_failures,
                financial_data_gaps,
                technical_data_gaps,
            )

        benchmark_series = fetch_live_series(
            BENCHMARK_SYMBOL,
            as_of=as_of,
            api_key_id=api_key_id,
            api_secret_key=api_secret_key,
            data_url=data_url,
        )

        for ticker, candidates in sorted(candidates_by_ticker.items()):
            cik = candidates[0].cik
            company = candidates[0].company
            latest_catalyst_date = max(c.window_end for c in candidates)

            cash_facts: dict[str, Any] | None = None
            try:
                time.sleep(REQUEST_PACING_SECONDS)
                _, cash_facts = live_cash_dilution_score(
                    client=active_client,
                    ticker=ticker,
                    cik=cik,
                    as_of=as_of,
                    catalyst_latest_date=latest_catalyst_date,
                    rules=rules,
                    candidate_id=ticker,
                )
            except ForeignPrivateIssuer as exc:
                excluded_foreign_issuer.append({"ticker": ticker, "reason": str(exc)})
                continue
            except FinancialDataError as exc:
                financial_data_gaps.append({"ticker": ticker, "reason": str(exc)})

            tech_facts: dict[str, Any] | None = None
            try:
                time.sleep(REQUEST_PACING_SECONDS)
                security_series = fetch_live_series(
                    ticker,
                    as_of=as_of,
                    api_key_id=api_key_id,
                    api_secret_key=api_secret_key,
                    data_url=data_url,
                )
                _, tech_facts = live_technical_score(
                    security_series=security_series,
                    benchmark_series=benchmark_series,
                    as_of=as_of,
                    rules=rules,
                )
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                technical_data_gaps.append({"ticker": ticker, "reason": str(exc)})

            for candidate in candidates:
                candidate_id = (
                    f"{ticker}-{candidate.catalyst_type.value}-{candidate.window_start.isoformat()}"
                )
                catalyst_score = live_catalyst_score(
                    candidate, as_of=as_of, rules=rules, candidate_id=candidate_id
                )
                pos = estimate_objective_pos(
                    event_id=candidate_id, catalyst_type=candidate.catalyst_type
                )
                watchlist.append(
                    {
                        "candidate_id": candidate_id,
                        "ticker": ticker,
                        "company": company,
                        "catalyst_type": candidate.catalyst_type.value,
                        "window_start": candidate.window_start.isoformat(),
                        "window_end": candidate.window_end.isoformat(),
                        "date_precision": candidate.precision.value,
                        "trigger_phrase": candidate.trigger_phrase,
                        "source_sentence": candidate.source_sentence,
                        "source_url": candidate.source_url,
                        "filing_date": (
                            candidate.filing_date.isoformat() if candidate.filing_date else None
                        ),
                        "catalyst_factor_points": catalyst_score.points,
                        "catalyst_factor_max_points": catalyst_score.max_points,
                        "objective_pos_low_pct": str(pos.low_pct),
                        "objective_pos_mid_pct": str(pos.mid_pct),
                        "objective_pos_high_pct": str(pos.high_pct),
                        "cash_dilution_facts": cash_facts,
                        "technical_facts": tech_facts,
                    }
                )
    finally:
        if owns_client:
            active_client.close()

    watchlist.sort(key=lambda r: (r["window_start"], r["ticker"]))
    return _result(
        start_date,
        end_date,
        as_of,
        watchlist,
        excluded_foreign_issuer,
        discovery_failures,
        financial_data_gaps,
        technical_data_gaps,
    )


def _result(
    start_date: date,
    end_date: date,
    as_of: datetime,
    watchlist: list[dict[str, Any]],
    excluded_foreign_issuer: list[dict[str, Any]],
    discovery_failures: list[dict[str, Any]],
    financial_data_gaps: list[dict[str, Any]],
    technical_data_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generator": "python scripts/filter_scan.py",
        "role": "SCREENING_FACTS_NOT_A_RECOMMENDATION",
        "as_of": as_of.isoformat(),
        "search_window": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "watchlist_count": len(watchlist),
        "watchlist": watchlist,
        "excluded_foreign_issuer": excluded_foreign_issuer,
        "discovery_failures": discovery_failures,
        "financial_data_gaps": financial_data_gaps,
        "technical_data_gaps": technical_data_gaps,
        "disclaimer": (
            "Every fact here is real and traceable to its source (source_url, "
            "source_sentence). Sorted chronologically, not by a combined score: "
            "the historical validation of these same combined factors found ~0 "
            "correlation with actual returns, so a ranked score here would imply "
            "predictive power that has not been demonstrated. No SCIENCE review, "
            "VALUATION, gates, or classification exist - this is not a "
            "recommendation, and the user is expected to do their own research "
            "(trial design, competitive landscape, charts) before acting on anything."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args()

    end_date = args.end_date or datetime.now(UTC).date()
    start_date = args.start_date or (end_date - timedelta(days=args.lookback_days))

    status = build(start_date=start_date, end_date=end_date)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(status))
    summary = {
        "as_of": status["as_of"],
        "search_window": status["search_window"],
        "watchlist_count": status["watchlist_count"],
        "excluded_foreign_issuer_count": len(status["excluded_foreign_issuer"]),
        "discovery_failure_count": len(status["discovery_failures"]),
        "financial_data_gap_count": len(status["financial_data_gaps"]),
        "technical_data_gap_count": len(status["technical_data_gaps"]),
    }
    SUMMARY_PATH.write_text(render(summary))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
