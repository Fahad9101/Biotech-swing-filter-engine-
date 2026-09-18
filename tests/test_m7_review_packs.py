"""Milestone 7 Section 13 review-pack generator: outcome-blindness and determinism."""

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from boe.catalysts import (
    CatalystObservation,
    CatalystVersion,
    require_historical_catalyst_confirmation,
)
from boe.scientific import ScientificEvidencePack

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "review_packs", ROOT / "scripts/m7_build_review_packs.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Any of these substrings appearing in a pack's JSON would indicate market
# outcome leakage into a supposedly outcome-blind evidence pack.
_OUTCOME_LEAKAGE_MARKERS = (
    "return_t1_pct",
    "return_t5_pct",
    "return_t20_pct",
    "swing_success",
    "severe_loss",
    "mfe_t20_pct",
    "mae_t20_pct",
    "brier",
    "xbi_relative",
)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys = list(value.keys())
        nested = [s for v in value.values() for s in _flatten_strings(v)]
        return keys + nested
    if isinstance(value, list):
        return [s for item in value for s in _flatten_strings(item)]
    return [str(value)]


def test_packs_are_contract_valid_and_outcome_blind() -> None:
    packs, manifest, worklist, deferred = module.build()
    assert packs, "expected at least one review pack from the current PASS pool"
    assert manifest["pack_count"] == len(packs)
    assert manifest["deferred_count"] == len(deferred)

    for pack in packs:
        assert pack["market_outcomes_inspected"] is False
        assert pack["outcome_inspected_for_selection"] is False
        observation = CatalystObservation(**pack["catalyst_observation"])
        version = CatalystVersion(**pack["catalyst_version"])
        ScientificEvidencePack(**pack["scientific_evidence_pack"])
        assert version.resolved_at_cutoff == observation.known_at
        assert pack["scientific_evidence_pack"]["manual_review_required"] is True
        assert pack["review"]["historical_catalyst_confirmation_status"] == "NOT_YET_REVIEWED"
        assert pack["review"]["manual_science_review_status"] == "NOT_YET_REVIEWED"
        assert pack["review"]["reviewer"] is None
        assert pack["review"]["reviewed_at"] is None

        tokens = " ".join(_flatten_strings(pack)).lower()
        for marker in _OUTCOME_LEAKAGE_MARKERS:
            assert marker not in tokens, f"{pack['candidate_id']} leaks outcome marker {marker!r}"

        # No real HistoricalCatalystConfirmation exists yet (none is fabricated
        # here), so the rankability gate must still refuse this catalyst version.
        with pytest.raises(Exception):  # noqa: B017 - HumanConfirmationRequired
            require_historical_catalyst_confirmation(version, None)


def test_deferred_candidates_are_excluded_and_explained() -> None:
    packs, _, _, deferred = module.build()
    packed_ids = {pack["candidate_id"] for pack in packs}
    for item in deferred:
        assert item["candidate_id"] not in packed_ids
        assert item["reason"].strip()
    deferred_ids = [item["candidate_id"] for item in deferred]
    assert deferred_ids == sorted(deferred_ids)


def test_worklist_covers_every_pack_exactly_once_in_stratum_order() -> None:
    packs, _, worklist, _ = module.build()
    pack_ids = {pack["candidate_id"] for pack in packs}
    worklist_ids = [entry["candidate_id"] for entry in worklist["entries"]]
    assert set(worklist_ids) == pack_ids
    assert len(worklist_ids) == len(set(worklist_ids))
    strata_seen = [entry["stratum"] for entry in worklist["entries"]]
    stratum_positions = {stratum: i for i, stratum in enumerate(module.STRATUM_ORDER)}
    ordinals = [stratum_positions[s] for s in strata_seen]
    assert ordinals == sorted(ordinals)
    assert [entry["sequence"] for entry in worklist["entries"]] == list(
        range(1, len(worklist_ids) + 1)
    )


def test_manifest_hash_is_deterministic_across_reruns() -> None:
    _, manifest_a, _, _ = module.build()
    _, manifest_b, _, _ = module.build()
    assert manifest_a["manifest_sha256"] == manifest_b["manifest_sha256"]
    assert manifest_a["packs"] == manifest_b["packs"]


def test_generated_artifacts_on_disk_match_a_fresh_build() -> None:
    packs, manifest, worklist, _ = module.build()
    assert module.MANIFEST_OUTPUT.read_text() == module.render(manifest)
    assert module.WORKLIST_OUTPUT.read_text() == module.render(worklist)
    for pack in packs:
        path = ROOT / "validation/m7/review_packs" / f"{pack['candidate_id']}.json"
        assert path.read_text() == module.render(pack)


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "validation/m7", tmp_path / "validation/m7")
    return tmp_path


def test_missing_required_field_defers_instead_of_raising(copied: Path) -> None:
    acquisition = copied / "validation/m7/acquisition/newly-sourced-batch-07.json"
    data = json.loads(acquisition.read_text())
    for event in data["events"]:
        if event["candidate_id"] == "CO-2025-CRVS-SOQUELITINIBASH":
            del event["indication"]
    acquisition.write_text(json.dumps(data))
    packs, _, _, deferred = module.build(copied)
    assert "CO-2025-CRVS-SOQUELITINIBASH" not in {p["candidate_id"] for p in packs}
    deferred_ids = {item["candidate_id"] for item in deferred}
    assert "CO-2025-CRVS-SOQUELITINIBASH" in deferred_ids
