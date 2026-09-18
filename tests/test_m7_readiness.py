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


def test_real_root_now_refuses_because_the_cohort_is_frozen() -> None:
    """The cohort was frozen this session (validation/m7/cohort-manifest.json
    now exists for real). build() against the real, unmodified repo root must
    therefore refuse rather than silently re-derive a pre-freeze status - see
    scripts/m7_build_authoritative_status.py for the post-freeze counterpart,
    and tests/test_m7_authoritative_status.py for its own coverage.
    """
    with pytest.raises(ValueError, match="authoritative frozen validation"):
        module.build()


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "validation/m7", tmp_path / "validation/m7")
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    # The real repo now has a frozen cohort-manifest.json (validation/m7 was
    # just copied wholesale above), but every test in this file below is
    # specifically exercising build()'s pre-freeze derivation logic in
    # isolation - a still-correct, still-tested code path even though the
    # live repo has moved past needing it. Strip the copy's manifest so these
    # tests keep testing that logic rather than immediately hitting the
    # freeze guard themselves.
    (tmp_path / "validation/m7/cohort-manifest.json").unlink(missing_ok=True)
    return tmp_path


def test_new_evidence_changes_status_without_manual_counts(copied: Path) -> None:
    before, rows = module.build(copied)
    # Pick a PENDING candidate with no existing universe determination on file
    # (so the injected override below cannot collide with a committed
    # real determination - see test_conflicting_universe_determination_...
    # elsewhere in this file for why that guard exists and must not be
    # tripped by accident here) and mark it negative in its own copied
    # acquisition file, simulating a newly recorded negative label arriving
    # alongside new universe evidence in the same batch.
    row = next(
        r
        for r in rows["rows"]
        if r["universe_status"] == "PENDING" and r["universe_evidence_path"] is None
    )
    candidate = row["candidate_id"]
    acquisition_path = copied / row["acquisition_path"]
    data = json.loads(acquisition_path.read_text())
    (event,) = (e for e in data["events"] if e["candidate_id"] == candidate)
    event["negative_event_candidate"] = True
    acquisition_path.write_text(json.dumps(data))

    before, rows = module.build(copied)
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


def test_stratum_buffer_reacts_to_a_new_failure(copied: Path) -> None:
    """A stratum's maximum_provisional_buffer must fall when a pending candidate in
    that stratum is newly excluded, so a stratum going mathematically infeasible
    (not_yet_excluded < requirement) is always caught by --check, not just noticed
    by accident (as happened for PHASE_3_PIVOTAL before this check existed).
    """
    before, rows = module.build(copied)
    candidate = next(
        r
        for r in rows["rows"]
        if r["universe_status"] == "PENDING"
        and r["stratum"]
        and r["universe_evidence_path"] is None
    )
    stratum = candidate["stratum"]
    before_buffer = before["strata"][stratum]["maximum_provisional_buffer"]
    path = copied / "validation/m7/promotion/historical-universe-ledger-999-test-only.json"
    path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "historical_universe_eligible": False,
                    }
                ]
            }
        )
    )
    after, _ = module.build(copied)
    assert after["strata"][stratum]["maximum_provisional_buffer"] == before_buffer - 1


def test_issuer_concentration_finding_clears_when_below_cap(copied: Path) -> None:
    """BIIB is committed at 6 PASS candidates, one over the frozen 5-event cap.
    Turning one of those PASS rows into a FAIL (simulating a corrected
    determination) must drop BIIB below the cap and remove the OVERALL
    finding - proving the check is live-derived from current PASS rows, not
    a stale snapshot. Edits the row in place (rather than adding a new
    ledger file) since this candidate already has a real determination, and
    a second row for the same candidate_id in a different file would
    correctly trip the conflicting-determination guard tested elsewhere.
    """
    before, rows = module.build(copied)
    before_findings = {
        (f["ticker"], f["scope"]): f for f in before["issuer_concentration_findings"]
    }
    assert ("BIIB", "OVERALL") in before_findings
    assert before_findings[("BIIB", "OVERALL")]["pass_count"] == 6
    one_biib_id = before_findings[("BIIB", "OVERALL")]["candidate_ids"][0]
    path = copied / "validation/m7/promotion/historical-universe-ledger-26.json"
    data = json.loads(path.read_text())
    (row,) = (r for r in data["rows"] if r["candidate_id"] == one_biib_id)
    row["historical_universe_eligible"] = False
    path.write_text(json.dumps(data))
    after, _ = module.build(copied)
    after_findings = {(f["ticker"], f["scope"]): f for f in after["issuer_concentration_findings"]}
    assert ("BIIB", "OVERALL") not in after_findings


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
