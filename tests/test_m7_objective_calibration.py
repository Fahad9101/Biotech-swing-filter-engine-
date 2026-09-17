"""Regressions for the objective-PoS-vs-real-outcomes calibration script."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_objective_calibration", ROOT / "scripts/m7_build_objective_calibration.py"
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
    assert module.OUTPUT_PATH.read_text() == module.render(status)
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])


def test_calibration_ground_truth_is_the_real_negative_event_label() -> None:
    """The Brier score must be computable independently from the frozen
    cohort's own negative_event field, proving the script does not invent
    its own ground truth."""
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    pos = json.loads((ROOT / "validation/m7/objective-pos-assessments.json").read_bytes())
    pos_by_id = {a["event_id"]: float(a["mid_pct"]) for a in pos["assessments"]}
    predicted = tuple(pos_by_id[e["event_id"]] for e in manifest["events"])
    observed = tuple(not e["negative_event"] for e in manifest["events"])

    from boe.historical_validation import brier_score

    status = module.build()
    assert status["brier_score"] == pytest.approx(brier_score(predicted, observed))


def test_band_calibration_covers_every_event_once() -> None:
    status = module.build()
    total = sum(band["n"] for band in status["pos_band_calibration"])
    assert total == status["event_count"]


def test_validation_periods_partition_the_full_cohort() -> None:
    """VALIDATION-AND-MILESTONES.md section 6: 2018-2022 diagnostic,
    2023-2024 temporal validation, 2025 holdout - every event must fall in
    exactly one period, and the three must sum to the full cohort."""
    status = module.build()
    periods = status["brier_score_by_validation_period"]
    assert set(periods) <= {"DIAGNOSTIC_2018_2022", "TEMPORAL_2023_2024", "HOLDOUT_2025"}
    assert sum(p["n"] for p in periods.values()) == status["event_count"]
    for period in periods.values():
        assert period["n"] > 0


def test_holdout_period_brier_is_computed_but_not_prescriptive() -> None:
    status = module.build()
    joined = " ".join(status["limitations"])
    assert "not used to justify any change" in joined


def test_limitations_disclose_outcome_awareness_and_scope() -> None:
    status = module.build()
    joined = " ".join(status["limitations"])
    assert "already seen this cohort's aggregate outcome rates" in joined
    assert "cannot be compared to BOE-1.0.0's own acceptance criteria" in joined


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_objective_calibration.py", "--check"])
    module.main()


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        module.OUTPUT_PATH.write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_objective_calibration.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
