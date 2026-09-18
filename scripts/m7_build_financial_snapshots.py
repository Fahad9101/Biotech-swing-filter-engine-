"""Build real point-in-time CashPosition snapshots at T-30 for the frozen
Milestone 7 cohort, using SEC XBRL data (boe.ingestion.sec_financials).

This follows a 10-event pilot (not committed - a scratch investigation) that
found: SEC XBRL data works cleanly for some issuers out of the box, but two
real, structural patterns block most of the rest. Both are resolved here per
the project owner's explicit choices, not silently:

1. Foreign private issuers (confirmed by a real 20-F or 40-F annual-report
   filing in SEC submissions history - the form only foreign private issuers
   use) often have no pre-cutoff XBRL facts at all, or report under IFRS
   rather than US-GAAP. Building IFRS/20-F-aware parsing is a separate, much
   larger undertaking. These events are excluded here and reported by name,
   not dropped silently.

2. Most clinical-stage biotechs are genuinely debt-free - equity-funded, no
   loans. build_cash_position() correctly refuses to assume zero debt
   without an explicit confirmation rather than guess. Here, if NO
   debt-related XBRL concept (see DEBT_CONCEPT_CHECK below) appears anywhere
   in an issuer's full SEC filing history - not just before the cutoff, the
   complete history, so a company that only started reporting debt after
   this event wouldn't be misread as always debt-free - debt is treated as
   confirmed zero, and the absence itself is recorded as the evidence via a
   deterministic evidence id documenting exactly what was checked. This is a
   documented, consistently-applied rule, not a per-event guess: every
   issuer is checked the same way, and the reasoning is inspectable in this
   script and in the output artifact below.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.financials import (  # noqa: E402
    DEBT_AGGREGATE_CONCEPTS,
    DEBT_CURRENT_CONCEPTS,
    DEBT_NONCURRENT_CONCEPTS,
    FinancialDataError,
    build_cash_position,
)
from boe.historical_validation import CohortManifest  # noqa: E402
from boe.ingestion.http import PublicDataClient  # noqa: E402
from boe.ingestion.sec_financials import parse_companyfacts, sec_companyfacts_url  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/financial-snapshots.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
USER_AGENT = "BOE Milestone-7 historical validation research@example.com"
SNAPSHOT_LOOKBACK_DAYS = 30  # T-30, the primary validation snapshot

DEBT_CONCEPT_CHECK = DEBT_AGGREGATE_CONCEPTS + DEBT_CURRENT_CONCEPTS + DEBT_NONCURRENT_CONCEPTS
_ZERO_DEBT_NAMESPACE = uuid5(NAMESPACE_URL, "https://boe.internal/m7/confirmed-zero-debt")


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _is_foreign_private_issuer(submissions: dict[str, Any]) -> bool:
    forms = submissions.get("filings", {}).get("recent", {}).get("form", [])
    return any(str(f).strip().upper() in {"20-F", "40-F"} for f in forms)


def _confirmed_zero_debt_evidence(companyfacts: dict[str, Any], ticker: str) -> UUID | None:
    """Deterministic, reproducible - not a random guess pretending to be
    sourced evidence. Same ticker + same absence always yields the same id,
    and what it represents is fully documented in this file's docstring."""
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    for concept in DEBT_CONCEPT_CHECK:
        if concept in gaap:
            return None
    return uuid5(_ZERO_DEBT_NAMESPACE, ticker)


def build(client: PublicDataClient | None = None) -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))

    events_by_ticker: dict[str, list[Any]] = {}
    cik_by_ticker: dict[str, str] = {}
    for event in manifest.events:
        events_by_ticker.setdefault(event.ticker, []).append(event)
        cik_by_ticker[event.ticker] = event.cik

    snapshots: list[dict[str, Any]] = []
    excluded_foreign_issuer: list[dict[str, Any]] = []
    data_gaps: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, Any]] = []

    owns_client = client is None
    active_client = client or PublicDataClient(USER_AGENT)
    try:
        for ticker in sorted(events_by_ticker):
            cik10 = str(int(cik_by_ticker[ticker])).zfill(10)
            events = events_by_ticker[ticker]
            try:
                submissions_payload = active_client.fetch(SUBMISSIONS_URL.format(cik=cik10))
                submissions = json.loads(submissions_payload.content)
                companyfacts_payload = active_client.fetch(sec_companyfacts_url(cik10))
                companyfacts = json.loads(companyfacts_payload.content)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                for event in events:
                    fetch_failures.append(
                        {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                    )
                continue

            if _is_foreign_private_issuer(submissions):
                for event in events:
                    excluded_foreign_issuer.append(
                        {
                            "event_id": event.event_id,
                            "ticker": ticker,
                            "reason": "confirmed 20-F/40-F filer (foreign private issuer); "
                            "XBRL coverage/taxonomy not handled by this pipeline",
                        }
                    )
                continue

            zero_debt_evidence = _confirmed_zero_debt_evidence(companyfacts, ticker)

            for event in events:
                t_minus_30 = event.event_at - timedelta(days=SNAPSHOT_LOOKBACK_DAYS)
                try:
                    facts = parse_companyfacts(
                        companyfacts_payload.content,
                        issuer_id=ticker,
                        as_of=t_minus_30,
                        default_evidence_id=uuid5(NAMESPACE_URL, f"m7-{event.event_id}"),
                    )
                    cash_position = build_cash_position(
                        issuer_id=ticker,
                        facts=facts,
                        as_of=t_minus_30,
                        confirmed_zero_debt_evidence_id=zero_debt_evidence,
                    )
                except FinancialDataError as exc:
                    data_gaps.append(
                        {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                    )
                    continue
                snapshots.append(
                    {
                        "event_id": event.event_id,
                        "ticker": ticker,
                        "t_minus_30": t_minus_30.date().isoformat(),
                        "balance_sheet_date": cash_position.balance_sheet_date.isoformat(),
                        "cash": str(cash_position.cash),
                        "marketable_securities": str(cash_position.marketable_securities),
                        "debt": str(cash_position.debt),
                        "liquidity": str(cash_position.liquidity),
                        "debt_confirmed_zero_by_absence": zero_debt_evidence is not None,
                    }
                )
    finally:
        if owns_client:
            active_client.close()

    snapshots.sort(key=lambda r: str(r["event_id"]))
    excluded_foreign_issuer.sort(key=lambda r: str(r["event_id"]))
    data_gaps.sort(key=lambda r: str(r["event_id"]))
    fetch_failures.sort(key=lambda r: str(r["event_id"]))

    return {
        "generator": "python scripts/m7_build_financial_snapshots.py",
        "cohort_sha256": manifest.cohort_sha256,
        "snapshot_label": "T_MINUS_30",
        "event_count": len(manifest.events),
        "snapshot_count": len(snapshots),
        "excluded_foreign_issuer_count": len(excluded_foreign_issuer),
        "data_gap_count": len(data_gaps),
        "fetch_failure_count": len(fetch_failures),
        "snapshots": snapshots,
        "excluded_foreign_issuer": excluded_foreign_issuer,
        "data_gaps": data_gaps,
        "fetch_failures": fetch_failures,
        "methodology_notes": [
            "Foreign-private-issuer exclusion is confirmed by a real 20-F/40-F "
            "annual-report filing in SEC submissions history for that issuer, "
            "not inferred from name, ticker, or guesswork.",
            "Zero-debt confirmation requires NO debt-related XBRL concept "
            "(LongTermDebt*, NotesPayable*, ShortTermBorrowings, etc.) to "
            "appear anywhere in the issuer's full SEC filing history, not "
            "just before the cutoff - checked once per issuer, applied "
            "identically to every event for that issuer.",
            "Remaining data_gaps are genuine: real domestic XBRL filers "
            "whose cash facts are still missing or ambiguous as of T-30 for "
            "reasons other than the two rules above - not excluded, not "
            "guessed at, left as an open gap.",
        ],
    }


def main() -> None:
    # No --check flag: unlike this repo's other M7 scripts, this one
    # requires ~180 live SEC requests to re-verify (one submissions + one
    # companyfacts fetch per unique issuer), which is impractical to run
    # inside a fast test suite or CI even though the underlying historical
    # XBRL facts are themselves stable (see scripts/m7_build_outcomes.py for
    # the same reasoning applied to live price data).
    argparse.ArgumentParser().parse_args()
    status = build()
    OUTPUT_PATH.write_text(render(status))
    print(
        json.dumps(
            {
                "event_count": status["event_count"],
                "snapshot_count": status["snapshot_count"],
                "excluded_foreign_issuer_count": status["excluded_foreign_issuer_count"],
                "data_gap_count": status["data_gap_count"],
                "fetch_failure_count": status["fetch_failure_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
