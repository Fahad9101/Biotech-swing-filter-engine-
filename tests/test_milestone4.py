from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from boe.contracts import load_scorecard
from boe.financials import (
    BurnAdjustment,
    FinancingFacility,
    ReconciliationItem,
    ShareComponent,
    audit_reconciliation,
    build_capital_structure_snapshot,
    build_cash_position,
    build_financing_risk_inputs,
    calculate_survival,
    derive_quarterly_operating_cash_flow,
    financial_facts_as_of,
    normalize_cash_burn,
)
from boe.ingestion.sec_financials import (
    extract_financing_disclosures,
    parse_companyfacts,
    parse_financing_filings,
    sec_companyfacts_url,
)

FROZEN_SCORECARD_SHA256 = "11cffb776ffd6bbd943b1d23dfcf6541ab02fcbfec753f13d00a7f4acee8b569"


def _as_of() -> datetime:
    return datetime(2026, 9, 30, 21, 0, tzinfo=UTC)


def _evidence_id() -> UUID:
    return UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _fact(
    concept: str,
    value: int,
    unit: str,
    end: str,
    *,
    accession: str,
    filed: str,
    start: str | None = None,
    fy: int | None = None,
    fp: str | None = None,
    form: str = "10-Q",
) -> dict[str, object]:
    output: dict[str, object] = {
        "val": value,
        "end": end,
        "accn": accession,
        "filed": filed,
        "form": form,
    }
    if start is not None:
        output["start"] = start
    if fy is not None:
        output["fy"] = fy
    if fp is not None:
        output["fp"] = fp
    return output


def _companyfacts() -> bytes:
    cash = [
        _fact(
            "CashAndCashEquivalentsAtCarryingValue",
            500_000_000,
            "USD",
            "2026-06-30",
            accession="0000000001-26-000020",
            filed="2026-08-05",
        ),
        _fact(
            "CashAndCashEquivalentsAtCarryingValue",
            600_000_000,
            "USD",
            "2026-09-30",
            accession="0000000001-26-000030",
            filed="2026-10-15",
        ),
    ]
    securities = [
        _fact(
            "ShortTermInvestments",
            25_000_000,
            "USD",
            "2026-06-30",
            accession="0000000001-26-000020",
            filed="2026-08-05",
        )
    ]
    debt = [
        _fact(
            "LongTermDebtCurrentAndNoncurrent",
            20_000_000,
            "USD",
            "2026-06-30",
            accession="0000000001-26-000020",
            filed="2026-08-05",
        )
    ]
    ocf = [
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -30_000_000,
            "USD",
            "2025-03-31",
            start="2025-01-01",
            accession="0000000001-25-000010",
            filed="2025-05-05",
            fy=2025,
            fp="Q1",
        ),
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -70_000_000,
            "USD",
            "2025-06-30",
            start="2025-01-01",
            accession="0000000001-25-000020",
            filed="2025-08-05",
            fy=2025,
            fp="Q2",
        ),
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -115_000_000,
            "USD",
            "2025-09-30",
            start="2025-01-01",
            accession="0000000001-25-000030",
            filed="2025-11-05",
            fy=2025,
            fp="Q3",
        ),
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -165_000_000,
            "USD",
            "2025-12-31",
            start="2025-01-01",
            accession="0000000001-26-000001",
            filed="2026-02-20",
            fy=2025,
            fp="FY",
            form="10-K",
        ),
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -55_000_000,
            "USD",
            "2026-03-31",
            start="2026-01-01",
            accession="0000000001-26-000010",
            filed="2026-05-05",
            fy=2026,
            fp="Q1",
        ),
        _fact(
            "NetCashProvidedByUsedInOperatingActivities",
            -115_000_000,
            "USD",
            "2026-06-30",
            start="2026-01-01",
            accession="0000000001-26-000020",
            filed="2026-08-05",
            fy=2026,
            fp="Q2",
        ),
    ]
    shares = [
        _fact(
            "EntityCommonStockSharesOutstanding",
            100_000_000,
            "shares",
            "2026-06-30",
            accession="0000000001-26-000020",
            filed="2026-08-05",
        )
    ]
    payload = {
        "cik": 1,
        "entityName": "Synthetic Biotech",
        "facts": {
            "us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": cash}},
                "ShortTermInvestments": {"units": {"USD": securities}},
                "LongTermDebtCurrentAndNoncurrent": {"units": {"USD": debt}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {"units": {"shares": shares}},
            },
        },
    }
    return json.dumps(payload).encode()


def test_companyfacts_adapter_enforces_point_in_time_cutoff() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=_as_of(),
        default_evidence_id=_evidence_id(),
    )

    cash_values = {
        fact.value
        for fact in facts
        if fact.concept == "CashAndCashEquivalentsAtCarryingValue"
    }
    assert cash_values == {Decimal("500000000")}
    assert all(fact.source_available_at <= _as_of() for fact in facts)
    assert sec_companyfacts_url(1).endswith("CIK0000000001.json")


def test_financial_survival_and_dilution_inputs_reconcile() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=_as_of(),
        default_evidence_id=_evidence_id(),
    )
    cash = build_cash_position(issuer_id="issuer-1", facts=facts, as_of=_as_of())
    quarterly = derive_quarterly_operating_cash_flow(facts, _as_of())
    burn = normalize_cash_burn(
        issuer_id="issuer-1",
        quarterly_cash_flow=quarterly,
        as_of=_as_of(),
    )
    components = (
        ShareComponent(
            kind="OPTIONS",
            shares=Decimal("5000000"),
            as_of=date(2026, 6, 30),
            evidence_ids=(_evidence_id(),),
            rationale="Reviewed option table.",
        ),
        ShareComponent(
            kind="WARRANTS",
            shares=Decimal("2000000"),
            as_of=date(2026, 6, 30),
            evidence_ids=(_evidence_id(),),
            rationale="Reviewed warrant table.",
        ),
    )
    capital = build_capital_structure_snapshot(
        issuer_id="issuer-1",
        facts=facts,
        as_of=_as_of(),
        share_components=components,
        expected_financing_shares=Decimal("10000000"),
        expected_financing_evidence_ids=(_evidence_id(),),
    )
    survival = calculate_survival(
        cash_position=cash,
        burn=burn,
        catalyst_latest_date=date(2026, 12, 31),
        as_of=_as_of(),
    )
    facility = FinancingFacility(
        issuer_id="issuer-1",
        kind="ATM",
        active=True,
        opened_at=date(2026, 8, 1),
        capacity_usd=Decimal("75000000"),
        used_usd=Decimal("20000000"),
        remaining_usd=Decimal("55000000"),
        observed_issuance_dependence=True,
        management_guided_use_before_catalyst=False,
        evidence_ids=(_evidence_id(),),
        reviewer="offline-reviewer",
        confirmed_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )
    risk_inputs = build_financing_risk_inputs(
        survival=survival,
        capital_structure=capital,
        facilities=(facility,),
        as_of=_as_of(),
    )

    assert cash.liquidity == Decimal("525000000")
    assert cash.debt == Decimal("20000000")
    assert burn.normalized_quarterly_burn == Decimal("52500000")
    assert burn.confidence == "HIGH"
    assert capital.fully_diluted_shares == Decimal("107000000")
    assert capital.projected_fully_diluted_shares == Decimal("117000000")
    assert survival.runway_months == Decimal("30")
    assert Decimal("26.9") < survival.runway_at_catalyst_months < Decimal("27.1")
    assert risk_inputs.active_atm is True
    assert risk_inputs.observed_issuance_dependence is True
    assert risk_inputs.runway_below_18_months is False
    assert Decimal("9.34") < risk_inputs.modeled_pre_catalyst_dilution_pct < Decimal("9.35")


def test_short_history_burn_uses_conservative_higher_value() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=datetime(2025, 8, 31, 21, 0, tzinfo=UTC),
        default_evidence_id=_evidence_id(),
    )
    quarterly = derive_quarterly_operating_cash_flow(
        facts,
        datetime(2025, 8, 31, 21, 0, tzinfo=UTC),
    )
    burn = normalize_cash_burn(
        issuer_id="issuer-1",
        quarterly_cash_flow=quarterly,
        as_of=datetime(2025, 8, 31, 21, 0, tzinfo=UTC),
    )

    assert burn.method == "CONSERVATIVE_SHORT_HISTORY"
    assert burn.confidence == "LOW"
    assert burn.normalized_quarterly_burn == Decimal("40000000")


def test_confirmed_adjustment_removes_one_time_restructuring_cash_flow() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=_as_of(),
        default_evidence_id=_evidence_id(),
    )
    quarterly = derive_quarterly_operating_cash_flow(facts, _as_of())
    adjustment = BurnAdjustment(
        quarter_end=date(2026, 6, 30),
        category="RESTRUCTURING",
        cash_flow_effect=Decimal("-10000000"),
        rationale="Reviewed filing separately identifies restructuring cash payment.",
        evidence_ids=(_evidence_id(),),
        reviewer="offline-reviewer",
        confirmed_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )
    burn = normalize_cash_burn(
        issuer_id="issuer-1",
        quarterly_cash_flow=quarterly,
        as_of=_as_of(),
        adjustments=(adjustment,),
    )

    latest = burn.quarters[-1]
    assert latest.reported_operating_cash_flow == Decimal("-60000000")
    assert latest.normalized_operating_cash_flow == Decimal("-50000000")
    assert latest.normalized_burn == Decimal("50000000")


def test_financing_filing_and_atm_extraction_are_primary_source_bounded() -> None:
    submissions = {
        "cik": "1",
        "filings": {
            "recent": {
                "form": ["S-3", "424B5", "424B5"],
                "accessionNumber": [
                    "0000000001-26-000040",
                    "0000000001-26-000041",
                    "0000000001-26-000050",
                ],
                "filingDate": ["2026-08-01", "2026-08-06", "2026-10-01"],
                "acceptanceDateTime": [
                    "2026-08-01T18:00:00Z",
                    "2026-08-06T18:00:00Z",
                    "2026-10-01T18:00:00Z",
                ],
                "primaryDocument": ["s3.htm", "424b5.htm", "future.htm"],
            }
        },
    }
    filings = parse_financing_filings(
        json.dumps(submissions).encode(),
        issuer_id="issuer-1",
        as_of=_as_of(),
    )

    assert [item.form for item in filings] == ["S-3", "424B5"]
    assert filings[0].category == "SHELF"
    observations = extract_financing_disclosures(
        "Under the sales agreement, we may sell shares in an at-the-market offering "
        "having an aggregate offering price of up to $75 million.",
        filing=filings[1],
        evidence_id=_evidence_id(),
    )
    assert len(observations) == 1
    assert observations[0].kind == "ATM"
    assert observations[0].capacity_usd == Decimal("75000000")


def test_financial_facts_as_of_excludes_post_cutoff_objects() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=datetime(2026, 12, 31, 21, 0, tzinfo=UTC),
        default_evidence_id=_evidence_id(),
    )
    cutoff = _as_of()
    filtered = financial_facts_as_of(facts, cutoff)

    assert all(fact.source_available_at <= cutoff for fact in filtered)
    assert all(fact.instant is None or fact.instant <= cutoff.date() for fact in filtered)
    assert Decimal("600000000") not in {
        fact.value
        for fact in filtered
        if fact.concept == "CashAndCashEquivalentsAtCarryingValue"
    }


def test_offline_reconciliation_fixture_passes(repository_root) -> None:
    payload = json.loads(
        (repository_root / "tests/fixtures/financials/milestone4_reconciliation.json").read_text()
    )
    items = tuple(ReconciliationItem.model_validate(item) for item in payload)
    audit = audit_reconciliation(items)

    assert audit.failed == 0
    assert audit.passed == audit.total == 3


def test_scorecard_checksum_remains_frozen(scorecard_path) -> None:
    assert load_scorecard(scorecard_path).raw_sha256 == FROZEN_SCORECARD_SHA256


def test_future_burn_adjustment_is_rejected() -> None:
    facts = parse_companyfacts(
        _companyfacts(),
        issuer_id="issuer-1",
        as_of=_as_of(),
        default_evidence_id=_evidence_id(),
    )
    quarterly = derive_quarterly_operating_cash_flow(facts, _as_of())
    adjustment = BurnAdjustment(
        quarter_end=date(2026, 6, 30),
        category="ACQUISITION",
        cash_flow_effect=Decimal("-5000000"),
        rationale="Future review must not enter a historical snapshot.",
        evidence_ids=(uuid4(),),
        reviewer="future-reviewer",
        confirmed_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="not confirmed by as_of"):
        normalize_cash_burn(
            issuer_id="issuer-1",
            quarterly_cash_flow=quarterly,
            as_of=_as_of(),
            adjustments=(adjustment,),
        )
