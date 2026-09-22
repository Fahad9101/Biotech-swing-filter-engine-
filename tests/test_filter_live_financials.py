"""Regressions for the live CASH_DILUTION facts builder.

Network access is always mocked, matching the SEC-XBRL scripts this
reuses.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from boe.contracts import load_scorecard
from boe.filter.live_financials import (
    ForeignPrivateIssuer,
    confirmed_zero_debt_evidence,
    is_foreign_private_issuer,
    live_cash_dilution_score,
)
from boe.financials import FinancialDataError
from boe.ingestion.http import PublicDataClient

ROOT = Path(__file__).resolve().parents[1]
RULES = load_scorecard(ROOT / "contracts/boe-scorecard.v1.0.0.json").contract


def _submissions(*, forms: list[str]) -> dict:
    return {"cik": "1", "filings": {"recent": {"form": forms}}}


def _instant(value: int, end: str, filed: str) -> dict:
    return {"val": value, "end": end, "filed": filed, "accn": "0001-26-000001", "form": "10-Q"}


def _quarter_fact(value: int, *, start: str, end: str, filed: str, fy: int, fp: str) -> dict:
    return {
        "val": value,
        "start": start,
        "end": end,
        "filed": filed,
        "accn": f"0001-26-{fp}",
        "form": "10-Q" if fp != "FY" else "10-K",
        "fy": fy,
        "fp": fp,
    }


def _companyfacts(*, debt_free: bool, shares_outstanding: int | None = 20_000_000) -> dict:
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {"USD": [_instant(10_000_000, "2026-06-30", "2026-08-01")]}
        },
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {
                "USD": [
                    _quarter_fact(
                        -2_000_000,
                        start="2026-01-01",
                        end="2026-03-31",
                        filed="2026-05-01",
                        fy=2026,
                        fp="Q1",
                    ),
                    _quarter_fact(
                        -4_000_000,
                        start="2026-01-01",
                        end="2026-06-30",
                        filed="2026-08-01",
                        fy=2026,
                        fp="Q2",
                    ),
                ]
            }
        },
    }
    if not debt_free:
        gaap["LongTermDebt"] = {"units": {"USD": [_instant(1_000_000, "2026-06-30", "2026-08-01")]}}
    payload: dict = {"facts": {"us-gaap": gaap}}
    if shares_outstanding is not None:
        payload["facts"]["dei"] = {
            "EntityCommonStockSharesOutstanding": {
                "units": {"shares": [_instant(shares_outstanding, "2026-08-01", "2026-08-01")]}
            }
        }
    return payload


def _client(*, forms: list[str], companyfacts: dict) -> PublicDataClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "submissions" in str(request.url):
            return httpx.Response(200, json=_submissions(forms=forms), request=request)
        return httpx.Response(200, json=companyfacts, request=request)

    return PublicDataClient("BOE test test@example.com", transport=httpx.MockTransport(handler))


def test_is_foreign_private_issuer_detects_20f_and_40f():
    assert is_foreign_private_issuer(_submissions(forms=["20-F"])) is True
    assert is_foreign_private_issuer(_submissions(forms=["40-F"])) is True
    assert is_foreign_private_issuer(_submissions(forms=["10-K"])) is False


def test_confirmed_zero_debt_evidence_deterministic_and_absence_based():
    debt_free = confirmed_zero_debt_evidence(_companyfacts(debt_free=True), "XYZ")
    has_debt = confirmed_zero_debt_evidence(_companyfacts(debt_free=False), "XYZ")
    assert debt_free is not None
    assert has_debt is None
    # deterministic: same ticker + same absence -> same id
    assert debt_free == confirmed_zero_debt_evidence(_companyfacts(debt_free=True), "XYZ")


def test_live_cash_dilution_score_real_debt_free_issuer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    as_of = datetime(2026, 9, 18, tzinfo=UTC)
    with _client(forms=["10-K", "10-Q"], companyfacts=_companyfacts(debt_free=True)) as client:
        factor_score, facts = live_cash_dilution_score(
            client=client,
            ticker="XYZ",
            cik="0000000001",
            as_of=as_of,
            catalyst_latest_date=date(2026, 11, 22),
            rules=RULES,
            candidate_id="test-candidate-1",
        )
    assert facts["debt_free_confirmed_by_absence"] is True
    assert 0 <= factor_score.points <= factor_score.max_points
    assert facts["shares_outstanding"] == "20000000"


def test_live_cash_dilution_score_shares_outstanding_missing_is_none_not_fabricated(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    companyfacts = _companyfacts(debt_free=True, shares_outstanding=None)
    with _client(forms=["10-K", "10-Q"], companyfacts=companyfacts) as client:
        _, facts = live_cash_dilution_score(
            client=client,
            ticker="XYZ",
            cik="0000000001",
            as_of=datetime(2026, 9, 18, tzinfo=UTC),
            catalyst_latest_date=date(2026, 11, 22),
            rules=RULES,
            candidate_id="test-candidate-shares-missing",
        )
    # a missing share count must not block the rest of the factor score -
    # it degrades to "unknown", it doesn't raise.
    assert facts["shares_outstanding"] is None


def test_live_cash_dilution_score_raises_for_foreign_private_issuer(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _client(forms=["20-F"], companyfacts=_companyfacts(debt_free=True)) as client:
        with pytest.raises(ForeignPrivateIssuer):
            live_cash_dilution_score(
                client=client,
                ticker="XYZ",
                cik="0000000001",
                as_of=datetime(2026, 9, 18, tzinfo=UTC),
                catalyst_latest_date=date(2026, 11, 22),
                rules=RULES,
                candidate_id="test-candidate-2",
            )


def test_live_cash_dilution_score_marks_flexibility_missing_when_debt_is_real(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _client(forms=["10-K"], companyfacts=_companyfacts(debt_free=False)) as client:
        _, facts = live_cash_dilution_score(
            client=client,
            ticker="XYZ",
            cik="0000000001",
            as_of=datetime(2026, 9, 18, tzinfo=UTC),
            catalyst_latest_date=date(2026, 11, 22),
            rules=RULES,
            candidate_id="test-candidate-3",
        )
    assert facts["debt_free_confirmed_by_absence"] is False


def test_live_cash_dilution_score_raises_financial_data_error_without_cash_fact(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _client(forms=["10-K"], companyfacts={"facts": {"us-gaap": {}}}) as client:
        with pytest.raises(FinancialDataError):
            live_cash_dilution_score(
                client=client,
                ticker="XYZ",
                cik="0000000001",
                as_of=datetime(2026, 9, 18, tzinfo=UTC),
                catalyst_latest_date=date(2026, 11, 22),
                rules=RULES,
                candidate_id="test-candidate-4",
            )
