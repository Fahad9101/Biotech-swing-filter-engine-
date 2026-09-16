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
        "total": 188,
        "pass": 136,
        "fail": 48,
        "pending": 4,
        "not_yet_excluded": 140,
    }
    negative = status["negative_reserve"]
    assert negative["not_yet_excluded"] == 40
    assert negative["pass"] == 38
    assert negative["pending"] == 2
    assert negative["maximum_provisional_buffer"] == 0
    assert negative["final_negative_quota_satisfied"] is False
    assert status["financing_reserve"]["pass"] == 20
    assert status["single_asset_reserve"]["pass"] == 20
    strata = status["strata"]
    assert strata["PHASE_3_PIVOTAL"]["requirement"] == 30
    assert strata["PHASE_3_PIVOTAL"]["pending"] == 0
    assert strata["PHASE_3_PIVOTAL"]["pass"] == 31
    assert strata["PHASE_3_PIVOTAL"]["maximum_provisional_buffer"] == 1
    assert strata["REGULATORY"]["pass"] == 38
    assert strata["REGULATORY"]["pending"] == 2
    assert strata["REGULATORY"]["maximum_provisional_buffer"] == 10
    assert strata["PHASE_2_POC"]["pass"] == 38
    assert strata["PHASE_2_POC"]["pending"] == 2
    assert strata["PHASE_2_POC"]["maximum_provisional_buffer"] == 10
    assert strata["EARLY_CLINICAL"]["pass"] == 17
    assert strata["EARLY_CLINICAL"]["pending"] == 0
    assert strata["EARLY_CLINICAL"]["maximum_provisional_buffer"] == 2
    assert strata["CONFERENCE_OTHER"]["pass"] == 12
    assert strata["CONFERENCE_OTHER"]["pending"] == 0
    assert strata["CONFERENCE_OTHER"]["maximum_provisional_buffer"] == -3
    for key, requirement in module.STRATUM_REQUIREMENTS.items():
        assert strata[key]["requirement"] == requirement
        assert strata[key]["maximum_provisional_buffer"] == (
            strata[key]["not_yet_excluded"] - requirement
        )
    assert status["audit_findings"]
    concentration = {f["ticker"]: f for f in status["issuer_concentration_findings"]}
    overall_biib = next(
        f
        for f in status["issuer_concentration_findings"]
        if f["ticker"] == "BIIB" and f["scope"] == "OVERALL"
    )
    assert overall_biib["pass_count"] == 6
    assert overall_biib["cap"] == 5
    stratum_biib = next(
        f
        for f in status["issuer_concentration_findings"]
        if f["ticker"] == "BIIB" and f["scope"] == "PHASE_2_POC"
    )
    assert stratum_biib["pass_count"] == 4
    kros = concentration["KROS"]
    assert kros["scope"] == "CONFERENCE_OTHER"
    assert kros["pass_count"] == 2
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


def test_stratum_buffer_reacts_to_a_new_failure(copied: Path) -> None:
    """A stratum's maximum_provisional_buffer must fall when a pending candidate in
    that stratum is newly excluded, so a stratum going mathematically infeasible
    (not_yet_excluded < requirement) is always caught by --check, not just noticed
    by accident (as happened for PHASE_3_PIVOTAL before this check existed).
    """
    before, rows = module.build(copied)
    candidate = next(r for r in rows["rows"] if r["universe_status"] == "PENDING" and r["stratum"])
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
