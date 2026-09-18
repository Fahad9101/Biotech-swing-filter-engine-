"""Regressions for the real, SEC-XBRL-backed financial snapshot script.

Network access is always mocked - see scripts/m7_build_financial_snapshots.py
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
    "m7_financial_snapshots", ROOT / "scripts/m7_build_financial_snapshots.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from boe.ingestion.http import PublicDataClient  # noqa: E402


def _submissions(*, forms: list[str]) -> dict:
    return {"cik": "1", "filings": {"recent": {"form": forms}}}


def _companyfacts(*, cash: dict | None, debt: dict | None) -> dict:
    gaap = {}
    if cash is not None:
        gaap["CashAndCashEquivalentsAtCarryingValue"] = cash
    if debt is not None:
        gaap["LongTermDebtCurrentAndNoncurrent"] = debt
    return {"facts": {"us-gaap": gaap}}


def test_refuses_without_a_frozen_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_foreign_private_issuer_is_detected_and_excluded() -> None:
    submissions = _submissions(forms=["20-F", "6-K"])
    assert module._is_foreign_private_issuer(submissions) is True

    domestic = _submissions(forms=["10-K", "10-Q", "8-K"])
    assert module._is_foreign_private_issuer(domestic) is False


def test_zero_debt_evidence_is_none_when_any_debt_concept_exists() -> None:
    facts_with_debt = {"facts": {"us-gaap": {"LongTermDebt": {}}}}
    assert module._confirmed_zero_debt_evidence(facts_with_debt, "ZZZZ") is None


def test_zero_debt_evidence_is_deterministic_when_absent() -> None:
    facts_without_debt = {"facts": {"us-gaap": {"CashAndCashEquivalentsAtCarryingValue": {}}}}
    first = module._confirmed_zero_debt_evidence(facts_without_debt, "ZZZZ")
    second = module._confirmed_zero_debt_evidence(facts_without_debt, "ZZZZ")
    assert first is not None
    assert first == second  # same ticker, same absence -> same id, not a random guess
    other_ticker = module._confirmed_zero_debt_evidence(facts_without_debt, "YYYY")
    assert other_ticker != first


def test_build_accepts_an_injected_client_and_reports_every_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercises the full build() orchestration against the real, frozen
    120-event manifest, with every SEC request answered by a mocked
    transport that always reports a foreign-issuer filing - proving the
    injected client is actually wired through the whole per-ticker loop,
    not just used for a hand-picked subset."""
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if "submissions" in str(request.url):
            return httpx.Response(200, json=_submissions(forms=["20-F"]), request=request)
        return httpx.Response(200, json=_companyfacts(cash=None, debt=None), request=request)

    with PublicDataClient(
        "BOE test test@example.com", transport=httpx.MockTransport(handler)
    ) as client:
        status = module.build(client=client)

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["excluded_foreign_issuer_count"] == len(manifest["events"])
    assert status["snapshot_count"] == 0
    assert status["data_gap_count"] == 0
    assert status["fetch_failure_count"] == 0


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
    assert status["snapshot_count"] == 0


def test_committed_snapshots_file_is_structurally_current() -> None:
    """Real committed artifact regression: does not re-fetch live SEC data
    (that requires ~180 live requests - see scripts/m7_build_financial_
    snapshots.py's main() docstring for why this repo never does that inside
    a test), but checks the last real run is still consistent with the
    frozen cohort and accounts for every event exactly once."""
    status = json.loads(module.OUTPUT_PATH.read_bytes())
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    total = (
        status["snapshot_count"]
        + status["excluded_foreign_issuer_count"]
        + status["data_gap_count"]
        + status["fetch_failure_count"]
    )
    assert total == status["event_count"]
    seen_event_ids = {s["event_id"] for s in status["snapshots"]}
    seen_event_ids |= {r["event_id"] for r in status["excluded_foreign_issuer"]}
    seen_event_ids |= {r["event_id"] for r in status["data_gaps"]}
    seen_event_ids |= {r["event_id"] for r in status["fetch_failures"]}
    assert seen_event_ids == {e["event_id"] for e in manifest["events"]}
