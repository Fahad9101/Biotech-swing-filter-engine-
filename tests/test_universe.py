import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

from boe.enums import Exchange, LeadEconomicAssetType, SecurityKind
from boe.universe import (
    BusinessEvidence,
    ListingRecord,
    SecSubmissionProfile,
    UniverseClassificationInput,
    classify_universe,
)

FIXTURE = Path(__file__).parent / "fixtures" / "universe" / "universe_audit_cases.json"
AUDIT_REPORT = Path(__file__).parents[1] / "validation" / "milestone-2-universe-audit.json"
AS_OF = datetime(2026, 9, 14, 20, tzinfo=UTC)


def _decision(case):
    listing = ListingRecord(
        ticker="BOEX",
        security_name="BOE Example Common Stock",
        exchange=Exchange.NASDAQ if case.get("supported_exchange", True) else None,
        exchange_code="Q" if case.get("supported_exchange", True) else "P",
        security_kind=SecurityKind(case["security_kind"]),
        test_issue=case.get("test_issue", False),
        etf=case.get("etf", False),
        next_shares=False,
        financial_status=None,
        source_row=2,
    )
    profile = None
    if case.get("sec_profile", True):
        profile = SecSubmissionProfile(
            cik="0000000001",
            legal_name="BOE Example",
            sic="2834",
            sic_description="Pharmaceutical Preparations",
            entity_type="operating",
            filer_category="accelerated filer",
            country="DE",
            tickers=(case.get("profile_ticker", "BOEX"),),
            exchanges=(case.get("profile_exchange", "Nasdaq"),),
            latest_periodic_filing_date=date(2026, 8, 1),
            latest_periodic_form="10-Q",
            reporting_current=case.get("reporting_current"),
            source_available_at=AS_OF,
        )
    business = None
    if case.get("business_evidence", True):
        business = BusinessEvidence(
            lead_economic_asset_type=LeadEconomicAssetType(case["lead_type"]),
            active_therapeutic_assets=case["active_assets"],
            therapeutic_focus_share_pct=case["focus_pct"],
            mature_diversified_pharma=case.get("mature", False),
            supporting_claim_ids=tuple(case["claims"]),
            rationale=f"Audit case {case['id']}",
        )
    return classify_universe(
        UniverseClassificationInput(
            listing=listing,
            sec_profile=profile,
            business_evidence=business,
            as_of=AS_OF,
        )
    )


def test_universe_boundary_audit_is_exact_and_deterministic():
    cases = json.loads(FIXTURE.read_text())
    assert len(cases) == 19

    for case in cases:
        first = _decision(case)
        second = _decision(case)
        assert first == second
        assert first.status.value == case["expected_status"], case["id"]
        assert first.reason_codes == (case["expected_reason"],), case["id"]
        assert first.eligible is (first.status.value == "INCLUDED")


def test_committed_audit_report_matches_fixture():
    fixture_bytes = FIXTURE.read_bytes()
    cases = json.loads(fixture_bytes)
    report = json.loads(AUDIT_REPORT.read_text())

    assert report["fixture_sha256"] == hashlib.sha256(fixture_bytes).hexdigest()
    assert report["case_count"] == len(cases)
    assert report["matched_expected"] == len(cases)
    assert report["unexplained_classifications"] == 0
    assert report["result"] == "PASS"
