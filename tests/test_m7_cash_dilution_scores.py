"""Regressions for the real, SEC-XBRL-backed CASH_DILUTION scoring script.

Network access is always mocked - see scripts/m7_build_cash_dilution_scores.py
for why this script is not exercised live by CI.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_cash_dilution_scores", ROOT / "scripts/m7_build_cash_dilution_scores.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from boe.ingestion.http import PublicDataClient  # noqa: E402


def _submissions(*, forms: list[str]) -> dict:
    return {"cik": "1", "filings": {"recent": {"form": forms}}}


def _instant(value: int, end: str, filed: str) -> dict:
    return {"val": value, "end": end, "filed": filed, "accn": "0001-25-000001", "form": "10-Q"}


def _quarter_fact(value: int, *, start: str, end: str, filed: str, fy: int, fp: str) -> dict:
    return {
        "val": value,
        "start": start,
        "end": end,
        "filed": filed,
        "accn": f"0001-25-{fp}",
        "form": "10-Q" if fp != "FY" else "10-K",
        "fy": fy,
        "fp": fp,
    }


def _companyfacts_with_real_burn(*, debt_free: bool) -> dict:
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {"USD": [_instant(10_000_000, "2024-06-30", "2024-08-01")]}
        },
        # Cumulative fiscal-year-to-date operating cash flow, real XBRL
        # convention: Q1 stands alone, Q2/Q3/FY are YTD cumulative.
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {
                "USD": [
                    _quarter_fact(
                        -2_000_000,
                        start="2024-01-01",
                        end="2024-03-31",
                        filed="2024-05-01",
                        fy=2024,
                        fp="Q1",
                    ),
                    _quarter_fact(
                        -4_000_000,
                        start="2024-01-01",
                        end="2024-06-30",
                        filed="2024-08-01",
                        fy=2024,
                        fp="Q2",
                    ),
                ]
            }
        },
    }
    if not debt_free:
        gaap["LongTermDebt"] = {"units": {"USD": [_instant(1_000_000, "2024-06-30", "2024-08-01")]}}
    return {"facts": {"us-gaap": gaap}}


def _fake_client(*, forms: list[str], companyfacts: dict) -> PublicDataClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if "submissions" in str(request.url):
            return httpx.Response(200, json=_submissions(forms=forms), request=request)
        return httpx.Response(200, json=companyfacts, request=request)

    return PublicDataClient("BOE test test@example.com", transport=httpx.MockTransport(handler))


def test_refuses_without_a_frozen_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_evidence_helper_marks_missing_correctly() -> None:
    missing = module._evidence("no data", "seed-1", missing=True)
    assert missing.data_state.value == "MISSING"
    assert missing.evidence_ids == ()

    present = module._evidence("real data", "seed-2", missing=False)
    assert present.data_state.value == "DERIVED"
    assert len(present.evidence_ids) == 1


def test_build_scores_real_manifest_events_with_debt_free_issuers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _fake_client(
        forms=["10-K", "10-Q"], companyfacts=_companyfacts_with_real_burn(debt_free=True)
    ) as client:
        status = module.build(client=client)

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["event_count"] == len(manifest["events"])
    assert status["excluded_foreign_issuer_count"] == 0
    assert status["score_count"] > 0
    for score in status["scores"]:
        assert score["debt_free_confirmed_by_absence"] is True
        assert 0 <= score["cash_dilution_factor_points"] <= score["cash_dilution_factor_max_points"]


def test_build_marks_balance_sheet_flexibility_missing_when_debt_is_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _fake_client(
        forms=["10-K", "10-Q"], companyfacts=_companyfacts_with_real_burn(debt_free=False)
    ) as client:
        status = module.build(client=client)

    assert status["score_count"] > 0
    for score in status["scores"]:
        assert score["debt_free_confirmed_by_absence"] is False


def test_build_excludes_foreign_private_issuers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _fake_client(
        forms=["20-F"], companyfacts=_companyfacts_with_real_burn(debt_free=True)
    ) as client:
        status = module.build(client=client)

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["excluded_foreign_issuer_count"] == len(manifest["events"])
    assert status["score_count"] == 0


def test_build_reports_fetch_failures_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    with PublicDataClient(
        "BOE test test@example.com", max_attempts=1, transport=httpx.MockTransport(handler)
    ) as client:
        status = module.build(client=client)

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["fetch_failure_count"] == len(manifest["events"])
    assert status["score_count"] == 0


def test_committed_cash_dilution_scores_file_is_structurally_current() -> None:
    """Real committed artifact regression: does not re-fetch live data, but
    checks the last real run is still consistent with the frozen cohort and
    accounts for every event exactly once."""
    status = json.loads(module.OUTPUT_PATH.read_bytes())
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    total = (
        status["score_count"]
        + status["excluded_foreign_issuer_count"]
        + status["data_gap_count"]
        + status["fetch_failure_count"]
    )
    assert total == status["event_count"]
    seen = {s["event_id"] for s in status["scores"]}
    seen |= {r["event_id"] for r in status["excluded_foreign_issuer"]}
    seen |= {r["event_id"] for r in status["data_gaps"]}
    seen |= {r["event_id"] for r in status["fetch_failures"]}
    assert seen == {e["event_id"] for e in manifest["events"]}
