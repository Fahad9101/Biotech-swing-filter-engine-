"""Status drift, alias binding and reserve accounting regressions."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "readiness", ROOT / "scripts/m7_reconcile_readiness.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_committed_status_is_derived_and_pending_is_not_pass() -> None:
    status, rows = module.build()
    assert (ROOT / module.OUTPUT).read_text() == module.render(status)
    assert (ROOT / module.ROWS_OUTPUT).read_text() == module.render(rows)
    assert status["candidate_counts"] == {
        "total": 179,
        "pass": 50,
        "fail": 16,
        "pending": 113,
        "not_yet_excluded": 163,
    }
    negative = status["negative_reserve"]
    assert negative["not_yet_excluded"] == 38
    assert negative["pass"] == 15
    assert negative["pending"] == 23
    assert negative["maximum_provisional_buffer"] == -2
    assert negative["final_negative_quota_satisfied"] is False
    assert status["financing_reserve"]["pass"] == 20
    assert status["single_asset_reserve"]["pass"] == 20
    assert status["audit_findings"]
    by_id = {r["candidate_id"]: r for r in rows["rows"]}
    assert by_id["P3-2023-RAIN-MANTRA"]["universe_status"] == "FAIL"
    assert by_id["P2-2025-ACTU-ELRAGLUSIB-TOPLINE"]["universe_status"] == "FAIL"
    assert "P2-2025-ACTU-ELRAGLUSIB" not in by_id


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "validation/m7", tmp_path / "validation/m7")
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    return tmp_path


def test_new_evidence_changes_status_without_manual_counts(copied: Path) -> None:
    before, rows = module.build(copied)
    candidate = next(
        r["candidate_id"]
        for r in rows["rows"]
        if r["negative_label_recorded"] and r["universe_status"] == "PENDING"
    )
    before_reserve = before["negative_reserve"]
    # A reserved, never-sequentially-issued filename: real batches use
    # historical-universe-ledger-01, -02, ... in order, so this cannot
    # collide with a committed ledger and silently overwrite real evidence.
    path = copied / "validation/m7/promotion/historical-universe-ledger-999-test-only.json"
    path.write_text(
        json.dumps({"rows": [{"candidate_id": candidate, "historical_universe_eligible": False}]})
    )
    after, _ = module.build(copied)
    assert after["negative_reserve"]["not_yet_excluded"] == before_reserve["not_yet_excluded"] - 1
    assert after["negative_reserve"]["pending"] == before_reserve["pending"] - 1
    assert after["negative_reserve"]["fail"] == before_reserve["fail"] + 1
    assert before["source_sha256"] != after["source_sha256"]


def test_conflicting_universe_determination_is_not_silently_overwritten(copied: Path) -> None:
    path = copied / "validation/m7/promotion/historical-universe-ledger-999-test-only.json"
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {"candidate_id": "P3-2023-RAIN-MANTRA", "historical_universe_eligible": True}
                ]
            }
        )
    )
    with pytest.raises(ValueError, match="Conflicting/repeated"):
        module.build(copied)


def test_manifest_presence_cannot_automatically_mark_complete(copied: Path) -> None:
    (copied / "validation/m7/cohort-manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="authoritative frozen validation"):
        module.build(copied)
