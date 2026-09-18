"""Regressions for the combined real-factor-score calibration script."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_partial_scorecard_calibration",
    ROOT / "scripts/m7_build_partial_scorecard_calibration.py",
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


def test_two_factor_tier_covers_the_full_cohort() -> None:
    status = module.build()
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["catalyst_technical"]["n"] == len(manifest["events"])


def test_three_factor_tier_is_a_subset_of_the_two_factor_tier() -> None:
    status = module.build()
    assert status["catalyst_cash_dilution_technical"]["n"] <= status["catalyst_technical"]["n"]


def test_ranking_metrics_are_reported_separately_not_collapsed() -> None:
    """The two ranking views (swing-success rate vs. median return) must
    each be present and independently computed - not merged into one
    metric that could hide a real disagreement between them."""
    status = module.build()
    for tier in (status["catalyst_technical"], status["catalyst_cash_dilution_technical"]):
        assert "swing_success_rate_ranks_correctly" in tier
        assert "median_return_ranks_correctly" in tier
        assert isinstance(tier["swing_success_rate_ranks_correctly"], bool)
        assert isinstance(tier["median_return_ranks_correctly"], bool)


def test_pearson_values_in_limitations_text_match_computed_values() -> None:
    """The limitations text embeds real computed Pearson values - this
    proves they are read from the actual tier summaries, not hardcoded."""
    status = module.build()
    joined = " ".join(status["limitations"])
    r1 = status["catalyst_technical"]["pearson_r_points_vs_xbi_relative_t20_return"]
    r2 = status["catalyst_cash_dilution_technical"]["pearson_r_points_vs_xbi_relative_t20_return"]
    assert f"{r1:.4f}" in joined
    assert f"{r2:.4f}" in joined


def test_factors_not_included_names_every_missing_factor() -> None:
    status = module.build()
    joined = " ".join(status["factors_not_included"])
    for factor in ("SCIENCE", "MARKET_IMPACT", "VALUATION", "OWNERSHIP", "SENTIMENT"):
        assert factor in joined


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_partial_scorecard_calibration.py", "--check"])
    module.main()


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        module.OUTPUT_PATH.write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_partial_scorecard_calibration.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
