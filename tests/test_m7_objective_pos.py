"""Regressions for the review-free objective PoS script."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_objective_pos", ROOT / "scripts/m7_build_objective_pos.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_refuses_without_a_frozen_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_committed_output_is_derived_and_current() -> None:
    status = module.build()
    assert module.OUTPUT_PATH.read_text() == module.render(status)
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    assert status["assessment_count"] == status["event_count"]
    assert {a["event_id"] for a in status["assessments"]} == {
        e["event_id"] for e in manifest["events"]
    }


def test_every_assessment_uses_low_confidence_and_valid_bounds() -> None:
    status = module.build()
    for assessment in status["assessments"]:
        assert 5 <= float(assessment["low_pct"]) <= float(assessment["mid_pct"])
        assert float(assessment["mid_pct"]) <= float(assessment["high_pct"]) <= 95
        # Exactly 30pp wide (2x the frozen LOW-confidence half-width) unless
        # clamped against the 5/95 bound, in which case it is narrower.
        assert float(assessment["high_pct"]) - float(assessment["low_pct"]) <= 30


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_objective_pos.py", "--check"])
    module.main()


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        module.OUTPUT_PATH.write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_objective_pos.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
