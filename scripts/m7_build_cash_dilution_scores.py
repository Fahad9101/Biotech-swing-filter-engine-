"""Build real point-in-time CASH_DILUTION factor scores at T-30 for the
frozen Milestone 7 cohort, extending scripts/m7_build_financial_snapshots.py's
real cash/debt data with real burn rate and runway, using the same already-
built, already-tested Milestone 4 machinery (src/boe/financials.py) and the
same foreign-issuer/zero-debt rules already established there.

CASH_DILUTION has three subfactors (contracts/boe-scorecard.v1.0.0.json):
RUNWAY, FINANCING_OVERHANG, BALANCE_SHEET_FLEXIBILITY.

- RUNWAY is fully computable: real liquidity (already sourced) divided by a
  real normalized quarterly burn rate (derived from real operating-cash-flow
  XBRL facts via derive_quarterly_operating_cash_flow()/normalize_cash_burn()
  - the same frozen Milestone 4 methodology, not new logic).
- FINANCING_OVERHANG is a genuine forward-looking judgment about the
  likelihood of near-term dilutive financing - not the same as "does an
  active shelf/ATM registration exist" (a fact) versus "will they actually
  draw on it soon" (a judgment blending market conditions and management
  intent this project cannot assess objectively). Left MISSING throughout,
  like SCIENCE and TECHNICAL's STRUCTURE subfactor - not fabricated.
- BALANCE_SHEET_FLEXIBILITY needs restrictive_obligations (loan covenant
  restrictions). For confirmed debt-free issuers this is objectively False
  (no debt, no debt covenants); for issuers with real debt, this project has
  no covenant data, so it is left unknown and the subfactor is MISSING for
  them specifically - not assumed favorable or unfavorable.

Live network calls: real SEC EDGAR fetches, re-run per unique issuer already
covered by financial-snapshots.json (companyfacts and, for
zero-debt-confirmed issuers, the same absence check) - not exercised by CI,
same reasoning as scripts/m7_build_financial_snapshots.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m7_build_financial_snapshots import (  # noqa: E402
    SUBMISSIONS_URL,
    USER_AGENT,
    _confirmed_zero_debt_evidence,
    _is_foreign_private_issuer,
)

from boe.contracts import load_scorecard  # noqa: E402
from boe.enums import DataState  # noqa: E402
from boe.financials import (  # noqa: E402
    FinancialDataError,
    build_cash_position,
    calculate_survival,
    derive_quarterly_operating_cash_flow,
    normalize_cash_burn,
)
from boe.historical_validation import CohortManifest, HistoricalEvent  # noqa: E402
from boe.ingestion.http import PublicDataClient  # noqa: E402
from boe.ingestion.sec_financials import parse_companyfacts, sec_companyfacts_url  # noqa: E402
from boe.scoring import CashDilutionScoreInput, SubfactorEvidence, score_cash_dilution  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/cash-dilution-scores.json"
SCORECARD_PATH = ROOT / "contracts/boe-scorecard.v1.0.0.json"
SNAPSHOT_LOOKBACK_DAYS = 30

CASH_DILUTION_SUBFACTORS = ("RUNWAY", "FINANCING_OVERHANG", "BALANCE_SHEET_FLEXIBILITY")


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _evidence(rationale: str, evidence_id_seed: str, *, missing: bool) -> SubfactorEvidence:
    if missing:
        return SubfactorEvidence(data_state=DataState.MISSING, rationale=rationale, evidence_ids=())
    return SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=rationale,
        evidence_ids=(uuid5(NAMESPACE_URL, evidence_id_seed),),
    )


def build(client: PublicDataClient | None = None) -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))
    rules = load_scorecard(SCORECARD_PATH).contract

    events_by_ticker: dict[str, list[HistoricalEvent]] = {}
    cik_by_ticker: dict[str, str] = {}
    for event in manifest.events:
        events_by_ticker.setdefault(event.ticker, []).append(event)
        cik_by_ticker[event.ticker] = event.cik

    scores: list[dict[str, Any]] = []
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
                as_of_iso = t_minus_30.date().isoformat()
                try:
                    facts = parse_companyfacts(
                        companyfacts_payload.content,
                        issuer_id=ticker,
                        as_of=t_minus_30,
                        default_evidence_id=uuid5(
                            NAMESPACE_URL, f"m7-cashdilution-{event.event_id}"
                        ),
                    )
                    cash_position = build_cash_position(
                        issuer_id=ticker,
                        facts=facts,
                        as_of=t_minus_30,
                        confirmed_zero_debt_evidence_id=zero_debt_evidence,
                    )
                    quarterly_cash_flow = derive_quarterly_operating_cash_flow(facts, t_minus_30)
                    burn = normalize_cash_burn(
                        issuer_id=ticker, quarterly_cash_flow=quarterly_cash_flow, as_of=t_minus_30
                    )
                    survival = calculate_survival(
                        cash_position=cash_position,
                        burn=burn,
                        catalyst_latest_date=event.event_at.date(),
                        as_of=t_minus_30,
                    )
                except FinancialDataError as exc:
                    data_gaps.append(
                        {"event_id": event.event_id, "ticker": ticker, "reason": str(exc)}
                    )
                    continue

                debt_free_confirmed = zero_debt_evidence is not None
                restrictive_obligations = False if debt_free_confirmed else None

                score_input = CashDilutionScoreInput(
                    runway_months=survival.runway_months,
                    burn_confidence=burn.confidence,
                    financing_overhang=None,
                    cash_and_securities=cash_position.cash + cash_position.marketable_securities,
                    debt=cash_position.debt,
                    runway_at_catalyst_months=survival.runway_at_catalyst_months,
                    restrictive_obligations=restrictive_obligations,
                    evidence={
                        "RUNWAY": _evidence(
                            f"runway_months={survival.runway_months} from real SEC XBRL cash/debt "
                            f"and burn data as of {as_of_iso} (method={burn.method}, "
                            f"confidence={burn.confidence}).",
                            f"m7-runway-{event.event_id}",
                            missing=False,
                        ),
                        "FINANCING_OVERHANG": _evidence(
                            "Not assessed: distinguishing a real active-shelf fact from a "
                            "genuine near-term-financing-likelihood judgment is out of scope "
                            "for this project's objective-only methodology.",
                            f"m7-overhang-{event.event_id}",
                            missing=True,
                        ),
                        "BALANCE_SHEET_FLEXIBILITY": _evidence(
                            (
                                "Confirmed debt-free (no debt XBRL concept in full filing "
                                "history), so restrictive_obligations=False is an objective "
                                "inference, not a guess."
                                if debt_free_confirmed
                                else "Issuer carries real debt and this project has no loan "
                                "covenant data - restrictive_obligations is genuinely unknown."
                            ),
                            f"m7-flexibility-{event.event_id}",
                            missing=restrictive_obligations is None,
                        ),
                    },
                )
                factor_score = score_cash_dilution(score_input, rules)
                scores.append(
                    {
                        "event_id": event.event_id,
                        "ticker": ticker,
                        "t_minus_30": as_of_iso,
                        "liquidity": str(cash_position.liquidity),
                        "debt": str(cash_position.debt),
                        "debt_free_confirmed_by_absence": debt_free_confirmed,
                        "normalized_quarterly_burn": str(burn.normalized_quarterly_burn),
                        "burn_method": burn.method,
                        "burn_confidence": burn.confidence,
                        "runway_months": str(survival.runway_months),
                        "runway_at_catalyst_months": str(survival.runway_at_catalyst_months),
                        "cash_dilution_factor_points": factor_score.points,
                        "cash_dilution_factor_max_points": factor_score.max_points,
                    }
                )
    finally:
        if owns_client:
            active_client.close()

    scores.sort(key=lambda r: str(r["event_id"]))
    excluded_foreign_issuer.sort(key=lambda r: str(r["event_id"]))
    data_gaps.sort(key=lambda r: str(r["event_id"]))
    fetch_failures.sort(key=lambda r: str(r["event_id"]))

    return {
        "generator": "python scripts/m7_build_cash_dilution_scores.py",
        "cohort_sha256": manifest.cohort_sha256,
        "snapshot_label": "T_MINUS_30",
        "event_count": len(manifest.events),
        "score_count": len(scores),
        "excluded_foreign_issuer_count": len(excluded_foreign_issuer),
        "data_gap_count": len(data_gaps),
        "fetch_failure_count": len(fetch_failures),
        "scores": scores,
        "excluded_foreign_issuer": excluded_foreign_issuer,
        "data_gaps": data_gaps,
        "fetch_failures": fetch_failures,
        "methodology_notes": [
            "Uses the same foreign-private-issuer exclusion and zero-debt-by-"
            "absence inference already established and documented in "
            "scripts/m7_build_financial_snapshots.py - not repeated logic, "
            "the same rule applied consistently.",
            "RUNWAY is fully real: liquidity / a normalized quarterly burn "
            "rate derived from real operating-cash-flow XBRL facts via the "
            "frozen Milestone 4 methodology (median of up to the latest four "
            "comparable negative-cash-flow quarters).",
            "FINANCING_OVERHANG is always MISSING: it is a forward-looking "
            "judgment about near-term dilutive-financing likelihood, not an "
            "objective fact this project can assess without guessing.",
            "BALANCE_SHEET_FLEXIBILITY is available only for confirmed "
            "debt-free issuers (restrictive_obligations=False is then an "
            "objective inference from the absence of any debt); issuers "
            "with real debt have unknown covenant terms and are left "
            "MISSING for this one subfactor rather than assumed either way.",
            "data_gaps beyond the shared foreign-issuer/zero-debt rules are "
            "genuine: real domestic filers whose burn rate could not be "
            "derived (e.g. no comparable negative operating-cash-flow "
            "quarter as of T-30) or whose cash facts remain ambiguous.",
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
                "score_count": status["score_count"],
                "excluded_foreign_issuer_count": status["excluded_foreign_issuer_count"],
                "data_gap_count": status["data_gap_count"],
                "fetch_failure_count": status["fetch_failure_count"],
            }
        )
    )


if __name__ == "__main__":
    main()
