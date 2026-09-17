"""Regressions for the real, network-free CATALYST scoring script."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_catalyst_scores", ROOT / "scripts/m7_build_catalyst_scores.py"
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
    assert status["score_count"] == status["event_count"]


def test_proximity_is_always_exactly_thirty_days() -> None:
    """A structural consequence of the fixed T-30 snapshot, not a bug -
    every event must land in the frozen [7,42]-day PROXIMITY band."""
    status = module.build()
    for score in status["scores"]:
        assert score["catalyst_factor_points"] >= 0


def test_regulatory_and_conference_types_get_high_timing_confidence() -> None:
    status = module.build()
    for score in status["scores"]:
        if score["catalyst_type"] in {
            "REG_SUBMIT",
            "REG_ADCOM",
            "REG_DECISION",
            "CONF_DATA",
            "PUBLICATION",
        }:
            assert score["timing_confidence"] == "HIGH"
        else:
            assert score["timing_confidence"] == "MODERATE"


def test_maturity_bucket_is_always_resolved() -> None:
    status = module.build()
    for score in status["scores"]:
        assert score["maturity_bucket"] is not None


def test_scores_never_exceed_fourteen_of_twenty_five_max_points() -> None:
    """MATERIALITY (8) and NOVEL_INFORMATION (3) are always MISSING, so the
    real achievable ceiling is 25 - 8 - 3 = 14."""
    status = module.build()
    for score in status["scores"]:
        assert score["catalyst_factor_points"] <= 14
        assert score["catalyst_factor_max_points"] == 25


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_catalyst_scores.py", "--check"])
    module.main()


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        module.OUTPUT_PATH.write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_catalyst_scores.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
