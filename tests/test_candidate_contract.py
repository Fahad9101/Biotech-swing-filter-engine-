import json

import pytest
from pydantic import ValidationError

from boe.contracts import (
    ContractViolation,
    load_candidate,
    load_scorecard,
    validate_candidate_against_scorecard,
)
from boe.models import CandidateOutput


def read_payload(candidate_path):
    return json.loads(candidate_path.read_text())


def test_valid_candidate_round_trips(candidate_path, scorecard_path):
    candidate = load_candidate(candidate_path)
    loaded = load_scorecard(scorecard_path)

    validate_candidate_against_scorecard(candidate, loaded)
    assert CandidateOutput.model_validate_json(candidate.model_dump_json()) == candidate
    assert candidate.score.raw_total == 73


def test_raw_total_must_reconcile(candidate_path):
    payload = read_payload(candidate_path)
    payload["score"]["raw_total"] = 74

    with pytest.raises(ValidationError, match="raw_total"):
        CandidateOutput.model_validate(payload)


def test_missing_subfactor_must_score_zero(candidate_path):
    payload = read_payload(candidate_path)
    subfactor = payload["score"]["factors"][0]["subfactors"][0]
    subfactor["data_state"] = "MISSING"

    with pytest.raises(ValidationError, match="missing subfactor"):
        CandidateOutput.model_validate(payload)


def test_future_evidence_is_rejected(candidate_path):
    payload = read_payload(candidate_path)
    payload["provenance"]["sources"][0]["available_at"] = "2026-09-15T00:00:00Z"
    payload["provenance"]["sources"][0]["retrieved_at"] = "2026-09-15T00:01:00Z"

    with pytest.raises(ValidationError, match="available after evidence cutoff"):
        CandidateOutput.model_validate(payload)


def test_factor_maximum_must_match_scorecard(candidate_path, scorecard_path):
    payload = read_payload(candidate_path)
    payload["score"]["factors"][0]["max_points"] = 26
    payload["score"]["factors"][0]["subfactors"][0]["max_points"] = 9
    candidate = CandidateOutput.model_validate(payload)

    with pytest.raises(ContractViolation, match="factor maximum"):
        validate_candidate_against_scorecard(candidate, load_scorecard(scorecard_path))


def test_coverage_must_reconcile(candidate_path, scorecard_path):
    payload = read_payload(candidate_path)
    payload["meta"]["data_coverage_pct"] = 99
    candidate = CandidateOutput.model_validate(payload)

    with pytest.raises(ContractViolation, match="coverage"):
        validate_candidate_against_scorecard(candidate, load_scorecard(scorecard_path))


def test_scorecard_checksum_must_match(candidate_path, scorecard_path):
    payload = read_payload(candidate_path)
    payload["meta"]["rules_checksum"] = "0" * 64
    candidate = CandidateOutput.model_validate(payload)

    with pytest.raises(ContractViolation, match="checksum"):
        validate_candidate_against_scorecard(candidate, load_scorecard(scorecard_path))


def test_scored_evidence_must_exist_in_provenance(candidate_path):
    payload = read_payload(candidate_path)
    payload["score"]["factors"][0]["subfactors"][0]["evidence_ids"] = ["unknown"]

    with pytest.raises(ValidationError, match="absent from provenance"):
        CandidateOutput.model_validate(payload)
