"""Regressions for the SCIENCE-redesign feasibility pilot.

Network access is always mocked - see scripts/m7_pilot_science_redesign.py
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
    "m7_pilot_science_redesign", ROOT / "scripts/m7_pilot_science_redesign.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _csv(rows: list[dict[str, str]], fieldnames: list[str]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _client(mapping_csv: str, metadata_csv: str) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "labels_and_tickers" in url:
            return httpx.Response(200, text=mapping_csv, request=request)
        assert "human_labels_2020_2024" in url
        return httpx.Response(200, text=metadata_csv, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _manifest_ticker_and_asset() -> tuple[str, str]:
    manifest = json.loads(module.MANIFEST_PATH.read_bytes())
    event = manifest["events"][0]
    return event["ticker"], event["asset"]


def test_refuses_without_a_frozen_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_norm_and_asset_tokens() -> None:
    assert module._norm("Libtayo (cemiplimab)") == "libtayocemiplimab"
    tokens = module._asset_tokens("dalzanemdor (SAGE-718)")
    assert "dalzanemdor" in tokens
    assert "sage" in tokens
    assert "718" not in tokens  # below the 4-char floor


def test_generic_ticker_token_only_match_detects_company_prefix_collision() -> None:
    tokens = module._asset_tokens("bempegaldesleukin (BEMPEG, NKTR-214)")
    unrelated_title = module._norm("A Study of Etirinotecan Pegol (NKTR-102)")
    assert module._generic_ticker_token_only("NKTR", tokens, unrelated_title) is True

    specific_title = module._norm("A Study of Bempegaldesleukin Plus Nivolumab")
    assert module._generic_ticker_token_only("NKTR", tokens, specific_title) is False


def test_build_matches_a_real_event_by_asset_name(monkeypatch: pytest.MonkeyPatch) -> None:
    ticker, asset = _manifest_ticker_and_asset()
    asset_word = next(w for w in asset.replace("(", " ").split() if len(w) >= 4)
    mapping_csv = _csv([{"nct_id": "NCT01234567", "Ticker": ticker}], ["nct_id", "Ticker"])
    fields = [
        "nct_id",
        "brief_title",
        "official_title",
        "phase",
        "completion_year",
        "primary_completion_date",
        "completion_date",
        "study_type",
        "enrollment",
        "enrollment_type",
        "number_of_arms",
        "overall_status",
        "labels",
    ]
    metadata_csv = _csv(
        [
            {
                "nct_id": "NCT01234567",
                "brief_title": f"A Study of {asset_word} in Adults",
                "official_title": "",
                "phase": "PHASE2",
                "completion_year": "2022",
                "primary_completion_date": "2022-01-01",
                "completion_date": "2022-06-01",
                "study_type": "INTERVENTIONAL",
                "enrollment": "100",
                "enrollment_type": "ACTUAL",
                "number_of_arms": "2",
                "overall_status": "COMPLETED",
                "labels": "1",  # must never be read by the pilot
            }
        ],
        fields,
    )
    with _client(mapping_csv, metadata_csv) as client:
        status = module.build(client=client)

    result = next(r for r in status["results"] if r["ticker"] == ticker)
    assert result["stage"] == "ASSET_NAME_MATCHED"
    assert result["matched_ncts"][0]["nct_id"] == "NCT01234567"


def test_metadata_fields_never_include_the_outcome_labels_column() -> None:
    assert "labels" not in module.METADATA_FIELDS


def test_build_reports_no_ticker_coverage_when_mapping_is_empty() -> None:
    mapping_csv = _csv([], ["nct_id", "Ticker"])
    metadata_csv = _csv(
        [],
        [
            "nct_id",
            "brief_title",
            "official_title",
            "phase",
            "completion_year",
            "primary_completion_date",
            "completion_date",
            "study_type",
            "enrollment",
            "enrollment_type",
            "number_of_arms",
            "overall_status",
        ],
    )
    with _client(mapping_csv, metadata_csv) as client:
        status = module.build(client=client)

    manifest = json.loads(module.MANIFEST_PATH.read_bytes())
    assert status["stage_counts"] == {"NO_TICKER_COVERAGE": len(manifest["events"])}
    assert status["recommendation"] == "DO_NOT_PROCEED"


def test_committed_pilot_artifact_is_structurally_current() -> None:
    status = json.loads(module.OUTPUT_PATH.read_bytes())
    manifest = json.loads(module.MANIFEST_PATH.read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    assert sum(status["stage_counts"].values()) == status["event_count"]
    assert status["data_sources"]["outcome_label_column_read"] is False
    assert status["recommendation"] == "DO_NOT_PROCEED"
    seen = {r["event_id"] for r in status["results"]}
    assert seen == {e["event_id"] for e in manifest["events"]}
