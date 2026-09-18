import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMOTION = ROOT / "validation" / "m7" / "promotion"

TARGET_IDS = {
    "REG-2020-BMRN-VALROX-CRL",
    "REG-2020-ICPT-OCA-CRL",
    "P3-2020-CRBP-RESOLVE1",
    "REG-2021-ATNX-ORALPAC-CRL",
    "REG-2021-FGEN-ROXADUSTAT-CRL",
    "REG-2022-CHRS-TORIPALIMAB-CRL",
}


def _load(name: str) -> dict:
    return json.loads((PROMOTION / name).read_text(encoding="utf-8"))


def test_targeted_negative_security_identity_evidence_is_complete_and_outcome_blind() -> None:
    payload = _load("historical-security-identity-ledger-12.json")
    assert payload["rules_version"] == "BOE-1.0.0"
    assert payload["market_outcomes_inspected"] is False
    assert payload["cohort_frozen"] is False
    assert {row["candidate_id"] for row in payload["rows"]} == TARGET_IDS
    assert payload["summary"]["identity_confirmed"] == 6
    assert payload["summary"]["us_listing_confirmed"] == 6
    for row in payload["rows"]:
        assert row["identity_status"] == "IDENTITY_CONFIRMED"
        assert row["us_listing_status"] == "US_LISTING_CONFIRMED"
        assert row["historical_universe_eligible"] is True
        assert row["pre_event_share_count_reference"]["shares_outstanding"] > 0
        assert row["outcome_inspected_for_selection"] is False


def test_targeted_negative_universe_evidence_clears_all_frozen_investability_floors() -> None:
    payload = _load("historical-universe-ledger-20.json")
    assert payload["rules_version"] == "BOE-1.0.0"
    assert payload["market_outcomes_inspected"] is False
    assert payload["cohort_frozen"] is False
    assert {row["candidate_id"] for row in payload["rows"]} == TARGET_IDS
    assert payload["summary"]["historical_universe_pass"] == 6
    assert payload["summary"]["historical_universe_fail"] == 0
    for row in payload["rows"]:
        assert row["last_complete_pre_event_raw_close_usd"] >= 1.0
        assert row["median_daily_dollar_volume_close_x_volume_usd"] >= 2_000_000
        assert row["median_daily_dollar_volume_vwap_x_volume_usd"] >= 2_000_000
        assert row["pre_event_market_cap_proxy_usd"] >= 50_000_000
        assert row["valid_session_floor_pass"] is True
        assert row["historical_universe_eligible"] is True
        assert row["outcome_inspected_for_selection"] is False


def test_negative_reserve_deficit_is_repaired_only_at_universe_stage() -> None:
    payload = _load("negative-reserve-integration-02.json")
    summary = payload["post_repair_summary"]
    assert payload["market_outcomes_inspected"] is False
    assert payload["cohort_frozen"] is False
    assert payload["quota_requirement"] == 40
    assert payload["prior_state"]["maximum_known_not_yet_excluded_negative_reserve"] == 37
    assert payload["targeted_repair"]["targeted_negative_candidates_added"] == 6
    assert payload["targeted_repair"]["historical_universe_pass"] == 6
    assert summary["maximum_known_not_yet_excluded_negative_reserve"] == 43
    assert summary["universe_stage_buffer"] == 3
    assert summary["historical_universe_stage_deficit_repaired"] is True
    assert summary["final_negative_quota_satisfied"] is False
    assert summary["additional_targeted_negative_acquisition_required_now"] is False
    assert summary["broad_acquisition_reopened"] is False
