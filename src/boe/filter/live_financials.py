"""Real, live (as-of-today) CASH_DILUTION facts for filter candidates.

Reuses the exact foreign-issuer and zero-debt rules established and
tested at scale in Milestone 7 (scripts/m7_build_financial_snapshots.py,
scripts/m7_build_cash_dilution_scores.py, on the milestone-7-historical-
validation branch): a confirmed 20-F/40-F filer is excluded (its XBRL
coverage/taxonomy is not handled by this pipeline), and debt is only
treated as confirmed-zero when no debt-related XBRL concept appears
anywhere in the issuer's full filing history - never assumed.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from boe.enums import DataState
from boe.financials import (
    DEBT_AGGREGATE_CONCEPTS,
    DEBT_CURRENT_CONCEPTS,
    DEBT_NONCURRENT_CONCEPTS,
    build_cash_position,
    calculate_survival,
    derive_quarterly_operating_cash_flow,
    latest_basic_shares_outstanding,
    normalize_cash_burn,
)
from boe.ingestion.http import PublicDataClient
from boe.ingestion.sec_financials import parse_companyfacts, sec_companyfacts_url
from boe.models import FactorScore, ScorecardContract
from boe.scoring import CashDilutionScoreInput, SubfactorEvidence, score_cash_dilution

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DEBT_CONCEPT_CHECK = DEBT_AGGREGATE_CONCEPTS + DEBT_CURRENT_CONCEPTS + DEBT_NONCURRENT_CONCEPTS
_ZERO_DEBT_NAMESPACE = uuid5(NAMESPACE_URL, "https://boe.internal/filter/confirmed-zero-debt")


class ForeignPrivateIssuer(Exception):
    """Raised when a ticker is a confirmed 20-F/40-F filer - excluded, same
    as Milestone 7, rather than silently mis-parsed under US-GAAP rules."""


def is_foreign_private_issuer(submissions: dict[str, Any]) -> bool:
    forms = submissions.get("filings", {}).get("recent", {}).get("form", [])
    return any(str(f).strip().upper() in {"20-F", "40-F"} for f in forms)


def confirmed_zero_debt_evidence(companyfacts: dict[str, Any], ticker: str) -> UUID | None:
    """Deterministic, reproducible - same ticker + same absence always
    yields the same id, not a random guess pretending to be evidence."""
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    for concept in DEBT_CONCEPT_CHECK:
        if concept in gaap:
            return None
    return uuid5(_ZERO_DEBT_NAMESPACE, ticker)


def _evidence(rationale: str, evidence_id_seed: str, *, missing: bool) -> SubfactorEvidence:
    if missing:
        return SubfactorEvidence(data_state=DataState.MISSING, rationale=rationale, evidence_ids=())
    return SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=rationale,
        evidence_ids=(uuid5(NAMESPACE_URL, evidence_id_seed),),
    )


def live_cash_dilution_score(
    *,
    client: PublicDataClient,
    ticker: str,
    cik: str,
    as_of: datetime,
    catalyst_latest_date: Any,
    rules: ScorecardContract,
    candidate_id: str,
) -> tuple[FactorScore, dict[str, Any]]:
    """Raises ForeignPrivateIssuer or FinancialDataError for real, honest
    reasons - never guesses to keep a candidate in the output."""
    cik10 = str(int(cik)).zfill(10)
    submissions_payload = client.fetch(SUBMISSIONS_URL.format(cik=cik10))
    submissions = json.loads(submissions_payload.content)
    if is_foreign_private_issuer(submissions):
        raise ForeignPrivateIssuer(
            f"{ticker} is a confirmed 20-F/40-F filer; XBRL coverage/taxonomy not handled"
        )

    companyfacts_payload = client.fetch(sec_companyfacts_url(cik10))
    companyfacts = json.loads(companyfacts_payload.content)
    zero_debt_evidence = confirmed_zero_debt_evidence(companyfacts, ticker)

    facts = parse_companyfacts(
        companyfacts_payload.content,
        issuer_id=ticker,
        as_of=as_of,
        default_evidence_id=uuid5(NAMESPACE_URL, f"filter-cashdilution-{candidate_id}"),
    )
    cash_position = build_cash_position(
        issuer_id=ticker,
        facts=facts,
        as_of=as_of,
        confirmed_zero_debt_evidence_id=zero_debt_evidence,
    )
    quarterly_cash_flow = derive_quarterly_operating_cash_flow(facts, as_of)
    burn = normalize_cash_burn(
        issuer_id=ticker, quarterly_cash_flow=quarterly_cash_flow, as_of=as_of
    )
    survival = calculate_survival(
        cash_position=cash_position,
        burn=burn,
        catalyst_latest_date=catalyst_latest_date,
        as_of=as_of,
    )

    shares_outstanding = latest_basic_shares_outstanding(facts, as_of)

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
                f"runway_months={survival.runway_months} from real SEC XBRL cash/debt and "
                f"burn data as of {as_of.date().isoformat()} (method={burn.method}, "
                f"confidence={burn.confidence}).",
                f"filter-runway-{candidate_id}",
                missing=False,
            ),
            "FINANCING_OVERHANG": _evidence(
                "Not assessed: distinguishing a real active-shelf fact from a genuine "
                "near-term-financing-likelihood judgment is out of scope here, same as M7.",
                f"filter-overhang-{candidate_id}",
                missing=True,
            ),
            "BALANCE_SHEET_FLEXIBILITY": _evidence(
                (
                    "Confirmed debt-free (no debt XBRL concept in full filing history)."
                    if debt_free_confirmed
                    else "Issuer carries real debt and this tool has no loan covenant data - "
                    "restrictive_obligations is genuinely unknown."
                ),
                f"filter-flexibility-{candidate_id}",
                missing=restrictive_obligations is None,
            ),
        },
    )
    factor_score = score_cash_dilution(score_input, rules)
    facts_out = {
        "liquidity": str(cash_position.liquidity),
        "debt": str(cash_position.debt),
        "debt_free_confirmed_by_absence": debt_free_confirmed,
        "runway_months": str(survival.runway_months),
        "runway_at_catalyst_months": str(survival.runway_at_catalyst_months),
        "burn_method": burn.method,
        "burn_confidence": burn.confidence,
        "shares_outstanding": str(shares_outstanding) if shares_outstanding is not None else None,
    }
    return factor_score, facts_out
