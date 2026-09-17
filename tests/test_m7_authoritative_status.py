"""Post-freeze authoritative status regressions."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "authoritative_status", ROOT / "scripts/m7_build_authoritative_status.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_no_manifest_refuses_pre_freeze_status(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build(tmp_path)


def test_committed_authoritative_status_is_derived_and_self_consistent() -> None:
    status = module.build()
    assert (ROOT / module.OUTPUT).read_text() == module.render(status)
    assert status["authoritative_cohort_manifest_present"] is True
    assert status["authoritative_events_frozen"] == 120
    assert status["registry_unchanged_since_freeze"] is True
    assert status["manifest_registry_sha256"] == status["rebuilt_registry_sha256"]
    assert status["frozen_cohort_negative_count"] >= 40
    assert status["frozen_cohort_financing_count"] >= 20
    assert status["frozen_cohort_single_asset_count"] >= 20
    assert status["frozen_cohort_max_issuer_count"] <= 5
    for stratum, requirement in module.STRATUM_REQUIREMENTS.items():
        assert status["frozen_cohort_strata"][stratum] >= requirement
    # Snapshot cutoffs and real price outcomes are genuine, real, completed
    # work - neither needs a human scientific/catalyst reviewer.
    assert status["snapshot_cutoffs_computed"] == 120
    assert status["snapshot_cutoffs_current"] is True
    assert status["real_outcomes_complete"] == 120
    assert status["real_outcomes_current"] is True
    assert status["real_outcomes_failed_count"] == 0
    # The review-free objective PoS substitute methodology is real and
    # complete for all 120 events, but it is explicitly not BOE-1.0.0 and
    # its own calibration report says it should not inform live decisions.
    assert status["objective_pos_assessments_complete"] == 120
    assert status["objective_pos_current"] is True
    assert status["objective_calibration_current"] is True
    assert status["objective_calibration_brier_beats_naive_prior"] is False
    assert status["objective_validation_report_current"] is True
    assert "RECALIBRATION" in status["objective_validation_report_recommendation"]
    # Real, objectively-computed CATALYST/CASH_DILUTION/TECHNICAL factor
    # scores - also real, also not BOE-1.0.0 itself. CASH_DILUTION's real
    # SEC coverage (88/120) is genuinely narrower than the others (120/120).
    assert status["catalyst_scores_complete"] == 120
    assert status["catalyst_scores_current"] is True
    assert status["cash_dilution_scores_complete"] == 88
    assert status["cash_dilution_scores_current"] is True
    assert status["technical_scores_complete"] == 120
    assert status["technical_scores_current"] is True
    assert status["partial_scorecard_calibration_current"] is True
    # Milestone 7 is still not complete: BOE-1.0.0 itself (score,
    # classification, gates, a real HistoricalDecisionLock) was never run for
    # any event, because that requires a real human reviewer this project
    # does not have, and no automated agent may supply one.
    assert status["real_four_snapshot_reconstructions_complete"] == 0
    assert status["decision_locks_complete"] == 0
    assert status["holdout_2025_locked_events"] == 0
    assert status["accepted_final_state_without_reviewer"] is True
    assert status["merge_ready"] is False
    assert status["milestone_complete"] is False
    assert status["milestone_8_allowed"] is False


def test_manifest_is_reparsed_and_revalidated_not_trusted_blindly(tmp_path: Path) -> None:
    """build() must re-run every CohortManifest validator against the
    committed file, not just check that it parses as JSON. A manifest edited
    to violate a frozen investment rule (here: dropping below the 40-event
    negative floor by relabeling every event as non-negative) must be
    rejected, proving the check is live re-validation, not a cached flag.
    """
    validation_dir = tmp_path / "validation/m7"
    (validation_dir / "promotion").mkdir(parents=True)
    manifest_path = validation_dir / "cohort-manifest.json"
    real_manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    tampered = json.loads(json.dumps(real_manifest))
    for event in tampered["events"]:
        event["negative_event"] = False
    manifest_path.write_text(json.dumps(tampered))
    with pytest.raises(Exception, match="negative"):
        module.build(tmp_path)


def test_authoritative_status_blocks_milestone_8_and_merge() -> None:
    status = module.build()
    assert any("Milestone 8" in finding for finding in status["required_action"].split(";"))
    assert status["milestone_8_allowed"] is False
    assert status["merge_ready"] is False


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_authoritative_status.py", "--check"])
    module.main()  # must not raise: the committed cohort-readiness.json is current


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = (ROOT / module.OUTPUT).read_bytes()
    try:
        (ROOT / module.OUTPUT).write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_authoritative_status.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        (ROOT / module.OUTPUT).write_bytes(original)
