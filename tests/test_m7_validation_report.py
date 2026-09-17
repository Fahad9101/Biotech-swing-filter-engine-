"""Regressions for the final M7 validation report assembly."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_validation_report", ROOT / "scripts/m7_build_validation_report.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_refuses_without_prerequisite_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="does not exist"):
        module.build()


def test_committed_report_is_derived_and_current() -> None:
    status = module.build()
    # code_sha reflects git HEAD at generation time and is expected to drift
    # by one commit once this very file is committed - excluded from the
    # byte-exact comparison, everything else must match exactly.
    committed = json.loads(module.OUTPUT_PATH.read_bytes())
    fresh = dict(status)
    committed_copy = dict(committed)
    fresh.pop("code_sha")
    committed_copy.pop("code_sha")
    assert fresh == committed_copy


def test_case_level_records_cover_the_full_cohort() -> None:
    status = module.build()
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert len(status["case_level_predictions_and_outcomes"]) == len(manifest["events"])
    assert {c["event_id"] for c in status["case_level_predictions_and_outcomes"]} == {
        e["event_id"] for e in manifest["events"]
    }


def test_recommendation_is_not_proceed() -> None:
    """This methodology's own calibration report shows it does not beat a
    naive baseline - the recommendation must reflect that honestly rather
    than default to a rosier claim."""
    status = module.build()
    assert "PROCEED" not in status["recommendation"].split(" - ")[0].split("-")[0] or status[
        "recommendation"
    ].startswith("PROPOSE RECALIBRATION")


def test_report_explicitly_lists_what_is_not_present() -> None:
    status = module.build()
    assert "NO FULL BOE-1.0.0 SCORE" in status["score_and_gate_distributions"]
    assert "real CATALYST factor score" in status["score_and_gate_distributions"]
    assert "NOT the full BOE-1.0.0 engine" in status["report_subject"]


def test_partial_scorecard_calibration_is_embedded() -> None:
    status = module.build()
    assert "partial_scorecard_calibration" in status
    assert status["partial_scorecard_calibration"]["cohort_sha256"] == status["cohort_sha256"]


def test_failure_register_uses_predefined_objective_thresholds() -> None:
    status = module.build()
    register = status["failure_register"]
    for fp in register["false_positives"]:
        assert fp["return_t20_pct"] <= module.FALSE_POSITIVE_RETURN_THRESHOLD_PCT
    for fn in register["false_negatives"]:
        assert fn["mfe_t20_pct"] >= module.FALSE_NEGATIVE_MFE_THRESHOLD_PCT


def test_structural_pattern_is_computed_from_real_catalyst_types() -> None:
    """The one root cause this project can support without new per-event
    research must be traceable to real, already-committed data - every
    false positive/negative's catalyst_type, cross-checked against the
    frozen manifest, not asserted without evidence."""
    status = module.build()
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    events_by_id = {e["event_id"]: e for e in manifest["events"]}
    register = status["failure_register"]
    for fp in register["false_positives"]:
        assert fp["catalyst_type"] == events_by_id[fp["event_id"]]["catalyst_type"]
    for fn in register["false_negatives"]:
        assert fn["catalyst_type"] == events_by_id[fn["event_id"]]["catalyst_type"]
    assert "structural" in register["structural_pattern"].lower()
    assert "not a coincidence" in register["structural_pattern"]


def test_main_regenerates_the_committed_report(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        monkeypatch.setattr(sys, "argv", ["m7_build_validation_report.py"])
        module.main()
        assert module.OUTPUT_PATH.exists()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
