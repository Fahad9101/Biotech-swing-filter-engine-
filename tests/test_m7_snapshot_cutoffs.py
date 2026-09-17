"""Regressions for the real, frozen-cohort snapshot-cutoff computation."""

import importlib.util
import json
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "snapshot_cutoffs", ROOT / "scripts/m7_build_snapshot_cutoffs.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_no_manifest_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_committed_output_is_derived_and_current() -> None:
    status = module.build()
    assert module.OUTPUT_PATH.read_text() == module.render(status)
    assert status["event_count"] == 120
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]


def test_every_event_has_four_ordered_cutoffs_before_its_own_timestamp() -> None:
    status = module.build()
    for record in status["events"]:
        event_at = datetime.fromisoformat(record["event_at"])
        cutoffs = {
            label: datetime.fromisoformat(value)
            for label, value in record["snapshot_cutoffs"].items()
        }
        assert set(cutoffs) == {
            "T_MINUS_60",
            "T_MINUS_30",
            "T_MINUS_10",
            "LAST_COMPLETE_SESSION",
        }
        assert cutoffs["T_MINUS_60"] < cutoffs["T_MINUS_30"] < cutoffs["T_MINUS_10"]
        for cutoff in cutoffs.values():
            assert cutoff < event_at


def test_last_complete_session_precedes_event_calendar_date() -> None:
    status = module.build()
    for record in status["events"]:
        event_date = datetime.fromisoformat(record["event_at"]).date()
        last_complete = date.fromisoformat(record["last_complete_session"])
        assert last_complete < event_date


def test_t0_session_is_on_or_after_event_calendar_date() -> None:
    status = module.build()
    for record in status["events"]:
        event_date = datetime.fromisoformat(record["event_at"]).date()
        t0_session = date.fromisoformat(record["t0_session"])
        assert t0_session >= event_date


def test_declares_what_remains_incomplete() -> None:
    status = module.build()
    joined = " ".join(status["not_yet_complete"])
    assert "price-data source" in joined
    assert "human reviewer" in joined


def test_check_flag_passes_when_committed_output_is_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setattr(sys, "argv", ["m7_build_snapshot_cutoffs.py", "--check"])
    module.main()


def test_check_flag_fails_when_committed_output_is_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    original = module.OUTPUT_PATH.read_bytes()
    try:
        module.OUTPUT_PATH.write_text("{}\n")
        monkeypatch.setattr(sys, "argv", ["m7_build_snapshot_cutoffs.py", "--check"])
        with pytest.raises(SystemExit, match="Stale generated artifact"):
            module.main()
    finally:
        module.OUTPUT_PATH.write_bytes(original)
