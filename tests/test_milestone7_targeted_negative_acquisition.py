import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETED_NEGATIVE_SUPPLEMENT = (
    ROOT / "validation/m7/acquisition/targeted-negative-supplement-02.json"
)
PROMOTION_BUILDER = ROOT / "scripts/m7_build_promotion_ledger.py"

FORBIDDEN_MARKET_OUTCOME_FIELDS = {
    "return_t1_pct",
    "return_t5_pct",
    "return_t20_pct",
    "xbi_relative_t1_pct",
    "xbi_relative_t5_pct",
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


def test_targeted_negative_supplement_is_narrow_outcome_blind_reserve_repair() -> None:
    payload = json.loads(TARGETED_NEGATIVE_SUPPLEMENT.read_text(encoding="utf-8"))
    events = payload["events"]

    assert payload["rules_version"] == "BOE-1.0.0"
    assert payload["role"] == "PRIMARY_SOURCE_TARGETED_NEGATIVE_SUPPLEMENT_NOT_FROZEN_COHORT"
    assert payload["authoritative_events_frozen"] == 0
    assert payload["candidate_count"] == len(events) == 6
    assert payload["negative_event_candidate_count"] == 6
    assert payload["exact_timestamp_count"] == 6
    assert payload["date_only_count"] == 0
    assert payload["cik_resolved_count"] == 6
    assert payload["registry_sha256"] == _canonical_sha256(payload)
    assert payload["source_boundary"]["broad_acquisition_reopened"] is False
    assert payload["source_boundary"]["market_outcome_inspection_permitted"] is False

    candidate_ids = [event["candidate_id"] for event in events]
    assert len(candidate_ids) == len(set(candidate_ids))
    assert {event["ticker"] for event in events} == {
        "ATNX",
        "BMRN",
        "CHRS",
        "CRBP",
        "FGEN",
        "ICPT",
    }

    for event in events:
        assert event["cohort_frozen"] is False
        assert event["negative_event_candidate"] is True
        assert event["outcome_inspected_for_selection"] is False
        assert event["timestamp_precision"] == "EXACT_TO_MINUTE"
        assert event["first_public_timestamp"] is not None
        assert str(event["result_direction"]).startswith("NEGATIVE")
        assert str(event["source_url"]).startswith("https://")
        assert event["promotion_blockers"]
        assert FORBIDDEN_MARKET_OUTCOME_FIELDS.isdisjoint(event)


def test_promotion_builder_ingests_targeted_negative_supplement() -> None:
    builder = PROMOTION_BUILDER.read_text(encoding="utf-8")
    assert '"targeted-negative-supplement-02.json"' in builder
