import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGULATORY_BATCH = ROOT / "validation/m7/acquisition/regulatory-primary-batch-01.json"
PHASE2_BATCH = ROOT / "validation/m7/acquisition/phase2-primary-batch-01.json"
PHASE3_BATCH = ROOT / "validation/m7/acquisition/phase3-primary-batch-01.json"
EARLY_CLINICAL_BATCH = ROOT / "validation/m7/acquisition/early-clinical-primary-batch-01.json"

FORBIDDEN_OUTCOME_FIELDS = {
    "return_t1_pct",
    "return_t5_pct",
    "return_t20_pct",
    "xbi_relative_t20_pct",
    "mfe_t20_pct",
    "mae_t20_pct",
    "severe_loss",
    "swing_success",
}


def _canonical_sha256(payload: dict[str, object]) -> str:
    unhashed = dict(payload)
    unhashed.pop("registry_sha256", None)
    canonical = json.dumps(unhashed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _assert_common_prefreeze_integrity(payload: dict[str, object]) -> list[dict[str, object]]:
    events = payload["events"]
    assert isinstance(events, list)
    assert payload["rules_version"] == "BOE-1.0.0"
    assert payload["authoritative_events_frozen"] == 0
    assert payload["candidate_count"] == len(events)
    assert payload["exact_timestamp_count"] == sum(
        event["first_public_timestamp"] is not None for event in events
    )
    assert payload["date_only_count"] == sum(
        event["first_public_timestamp"] is None for event in events
    )
    assert payload["cik_resolved_count"] == sum(event["cik"] is not None for event in events)
    assert payload["registry_sha256"] == _canonical_sha256(payload)

    candidate_ids = [event["candidate_id"] for event in events]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert any(str(event["first_public_date"]).startswith("2018-") for event in events)
    assert any(str(event["first_public_date"]).startswith("2025-") for event in events)

    for event in events:
        assert event["cohort_frozen"] is False
        assert event["outcome_inspected_for_selection"] is False
        assert str(event["source_url"]).startswith("https://")
        assert event["promotion_blockers"]
        assert FORBIDDEN_OUTCOME_FIELDS.isdisjoint(event)
    return events


def test_regulatory_acquisition_batch_is_prefreeze_and_self_consistent() -> None:
    payload = json.loads(REGULATORY_BATCH.read_text(encoding="utf-8"))
    events = _assert_common_prefreeze_integrity(payload)

    assert payload["role"] == "PRIMARY_SOURCE_REGULATORY_CANDIDATES_NOT_FROZEN_COHORT"
    assert payload["candidate_count"] == 33
    assert payload["cik_resolved_count"] == 25
    for event in events:
        assert event["proposed_primary_stratum"] == "REGULATORY"


def test_phase2_acquisition_batch_is_prefreeze_and_outcome_blinded() -> None:
    payload = json.loads(PHASE2_BATCH.read_text(encoding="utf-8"))
    events = _assert_common_prefreeze_integrity(payload)

    assert payload["role"] == "PRIMARY_SOURCE_PHASE2_CANDIDATES_NOT_FROZEN_COHORT"
    assert payload["candidate_count"] == 36
    assert payload["candidate_count"] >= 30
    assert payload["negative_event_candidate_count"] == sum(
        event["negative_event_candidate"] is True for event in events
    )
    assert payload["negative_event_candidate_count"] == 13
    assert payload["exact_timestamp_count"] == 21
    assert payload["date_only_count"] == 15
    for event in events:
        assert event["proposed_primary_stratum"] == "PHASE_2_POC"
        assert event["clinical_phase"] == "PHASE_2"
        assert event["result_direction"]


def test_phase3_acquisition_batch_is_prefreeze_and_outcome_blinded() -> None:
    payload = json.loads(PHASE3_BATCH.read_text(encoding="utf-8"))
    events = _assert_common_prefreeze_integrity(payload)

    assert payload["role"] == "PRIMARY_SOURCE_PHASE3_CANDIDATES_NOT_FROZEN_COHORT"
    assert payload["candidate_count"] == 31
    assert payload["candidate_count"] >= 30
    assert payload["negative_event_candidate_count"] == sum(
        event["negative_event_candidate"] is True for event in events
    )
    assert payload["negative_event_candidate_count"] == 17
    assert payload["exact_timestamp_count"] == 27
    assert payload["date_only_count"] == 4
    for event in events:
        assert event["proposed_primary_stratum"] == "PHASE_3_PIVOTAL"
        assert event["clinical_phase"] == "PHASE_3"
        assert event["result_direction"]


def test_early_clinical_batch_is_prefreeze_and_outcome_blinded() -> None:
    payload = json.loads(EARLY_CLINICAL_BATCH.read_text(encoding="utf-8"))
    events = _assert_common_prefreeze_integrity(payload)

    assert payload["role"] == "PRIMARY_SOURCE_EARLY_CLINICAL_CANDIDATES_NOT_FROZEN_COHORT"
    assert payload["candidate_count"] == 31
    assert payload["candidate_count"] >= 15
    assert payload["negative_event_candidate_count"] == sum(
        event["negative_event_candidate"] is True for event in events
    )
    assert payload["negative_event_candidate_count"] == 5
    assert payload["exact_timestamp_count"] == 28
    assert payload["date_only_count"] == 3
    for event in events:
        assert event["proposed_primary_stratum"] == "EARLY_CLINICAL"
        assert event["clinical_phase"] in {"PHASE_1", "PHASE_1_2"}
        assert event["result_direction"]
