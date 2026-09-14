from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGULATORY_BATCH = ROOT / "validation/m7/acquisition/regulatory-primary-batch-01.json"


def _canonical_sha256(payload: dict[str, object]) -> str:
    unhashed = dict(payload)
    unhashed.pop("registry_sha256", None)
    canonical = json.dumps(unhashed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def test_regulatory_acquisition_batch_is_prefreeze_and_self_consistent() -> None:
    payload = json.loads(REGULATORY_BATCH.read_text(encoding="utf-8"))
    events = payload["events"]

    assert payload["role"] == "PRIMARY_SOURCE_REGULATORY_CANDIDATES_NOT_FROZEN_COHORT"
    assert payload["rules_version"] == "BOE-1.0.0"
    assert payload["authoritative_events_frozen"] == 0
    assert payload["candidate_count"] == len(events) == 33
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
    assert any(event["first_public_date"].startswith("2018-") for event in events)
    assert any(event["first_public_date"].startswith("2025-") for event in events)

    forbidden_outcome_fields = {
        "return_t1_pct",
        "return_t5_pct",
        "return_t20_pct",
        "xbi_relative_t20_pct",
        "mfe_t20_pct",
        "mae_t20_pct",
        "severe_loss",
        "swing_success",
    }
    for event in events:
        assert event["proposed_primary_stratum"] == "REGULATORY"
        assert event["cohort_frozen"] is False
        assert event["outcome_inspected_for_selection"] is False
        assert event["source_url"].startswith("https://")
        assert event["promotion_blockers"]
        assert forbidden_outcome_fields.isdisjoint(event)
