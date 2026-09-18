from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pydantic
import pytest

from boe.catalysts import (
    CatalystConflictError,
    CatalystObservation,
    HistoricalCatalystConfirmation,
    HumanCatalystConfirmation,
    HumanConfirmationRequired,
    normalize_catalyst,
    require_historical_catalyst_confirmation,
    require_human_confirmation,
)
from boe.enums import CatalystType, EvidenceTier, TimingConfidence
from boe.historical_validation import deterministic_record_hash
from boe.ingestion.clinicaltrials import ClinicalTrialsAdapter
from boe.ingestion.fda import FDAAdapter
from boe.ingestion.guidance import extract_catalyst_guidance
from boe.scientific import build_scientific_evidence_pack
from boe.validation import AuditLabel, audit_point_in_time, precision_recall

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "catalysts"
KNOWN_AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _observation(
    *,
    evidence_id: UUID | None = None,
    tier: EvidenceTier = EvidenceTier.SEC_FILING,
    start: date = date(2026, 10, 1),
    end: date = date(2026, 12, 31),
    known_at: datetime = KNOWN_AT,
    phase: str = "Phase 2",
) -> CatalystObservation:
    return CatalystObservation(
        issuer_id="issuer-1",
        asset="BOE-101",
        indication="Example disease",
        catalyst_type=CatalystType.CLIN_P2,
        clinical_phase=phase,
        title="Phase 2 topline readout",
        window_start=start,
        window_end=end,
        timing_confidence=TimingConfidence.MODERATE,
        evidence_id=evidence_id or uuid4(),
        source_tier=tier,
        known_at=known_at,
        source_statement="We expect Phase 2 topline data in Q4 2026.",
    )


def test_clinicaltrials_v2_parser_builds_scientific_inputs() -> None:
    fixture = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT01234567",
                "briefTitle": "BOE-101 in Example Disease",
                "officialTitle": "A Randomized Study of BOE-101",
            },
            "statusModule": {
                "overallStatus": "ACTIVE_NOT_RECRUITING",
                "primaryCompletionDateStruct": {"date": "2026-11"},
            },
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": ["PHASE2"],
                "enrollmentInfo": {"count": 120, "type": "ACTUAL"},
                "designInfo": {
                    "allocation": "RANDOMIZED",
                    "interventionModel": "PARALLEL",
                    "maskingInfo": {"masking": "DOUBLE"},
                },
            },
            "conditionsModule": {"conditions": ["Example disease"]},
            "armsInterventionsModule": {
                "interventions": [{"name": "BOE-101"}, {"name": "Placebo"}]
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Change in endpoint"}],
                "secondaryOutcomes": [{"measure": "Safety"}],
            },
        }
    }
    record = ClinicalTrialsAdapter.parse_study(json.dumps(fixture))
    assert record.nct_id == "NCT01234567"
    assert record.phases == ("PHASE2",)
    assert record.enrollment == 120
    assert record.primary_completion_date == date(2026, 11, 1)
    assert record.primary_endpoints == ("Change in endpoint",)


def test_fda_parser_extracts_application_action() -> None:
    fixture = {
        "results": [
            {
                "application_number": "NDA123456",
                "sponsor_name": "Example Bio",
                "products": [
                    {
                        "brand_name": "BOE-101",
                        "active_ingredients": [{"name": "boe-101"}],
                    }
                ],
                "submissions": [
                    {
                        "submission_status_date": "20261014",
                        "submission_type": "ORIG",
                        "submission_number": "1",
                        "submission_status": "AP",
                    }
                ],
            }
        ]
    }
    actions = FDAAdapter.parse_drugsfda(json.dumps(fixture))
    assert len(actions) == 1
    assert actions[0].application_number == "NDA123456"
    assert actions[0].action_date == date(2026, 10, 14)
    assert actions[0].active_ingredients == ("boe-101",)


def test_guidance_preselected_precision_recall_audit() -> None:
    cases = json.loads((FIXTURE_DIR / "milestone3_guidance_audit.json").read_text())
    labels: list[AuditLabel] = []
    for case in cases:
        observations = extract_catalyst_guidance(
            case["text"],
            issuer_id="issuer-1",
            asset="BOE-101",
            indication="Example disease",
            clinical_phase="Phase 2",
            evidence_id=uuid4(),
            source_tier=EvidenceTier.SEC_FILING,
            known_at=KNOWN_AT,
        )
        labels.append(
            AuditLabel(
                case_id=case["case_id"],
                expected_positive=case["expected"],
                predicted_positive=bool(observations),
            )
        )
    audit = precision_recall(tuple(labels))
    assert audit.total == 20
    assert audit.precision >= 0.95
    assert audit.recall >= 0.95


def test_source_precedence_conflict_and_versioning_are_deterministic() -> None:
    sec = _observation(start=date(2026, 10, 1), end=date(2026, 12, 31))
    ctgov = _observation(
        tier=EvidenceTier.CLINICAL_TRIALS_REGISTRY,
        start=date(2027, 1, 1),
        end=date(2027, 3, 31),
    )
    first = normalize_catalyst((ctgov, sec), cutoff=KNOWN_AT)
    again = normalize_catalyst((sec, ctgov), cutoff=KNOWN_AT)
    assert first.version == 1
    assert first.version_sha256 == again.version_sha256
    assert first.primary_evidence_id == sec.evidence_id
    assert first.has_unresolved_conflict
    assert any(item.code == "DISJOINT_TIMING_WINDOWS" for item in first.conflicts)

    later = _observation(
        evidence_id=sec.evidence_id,
        start=date(2026, 11, 1),
        end=date(2026, 11, 30),
        known_at=KNOWN_AT + timedelta(days=2),
    )
    second = normalize_catalyst(
        (later,), cutoff=KNOWN_AT + timedelta(days=2), prior_versions=(first,)
    )
    assert second.version == 2
    assert second.version_sha256 != first.version_sha256


def test_human_confirmation_is_mandatory_and_cutoff_bound() -> None:
    observation = _observation()
    catalyst = normalize_catalyst((observation,), cutoff=KNOWN_AT)
    with pytest.raises(HumanConfirmationRequired):
        require_human_confirmation(catalyst, None, cutoff=KNOWN_AT)

    confirmation = HumanCatalystConfirmation(
        catalyst_version_id=catalyst.id,
        reviewer="clinical-reviewer",
        confirmed_at=KNOWN_AT,
        decision="CONFIRMED",
        evidence_ids_reviewed=catalyst.supporting_evidence_ids,
        conflict_resolution_notes="No unresolved source conflict.",
    )
    decision = require_human_confirmation(catalyst, confirmation, cutoff=KNOWN_AT)
    assert decision.rankable is True

    future_confirmation = confirmation.model_copy(
        update={"confirmed_at": KNOWN_AT + timedelta(seconds=1)}
    )
    with pytest.raises(HumanConfirmationRequired):
        require_human_confirmation(catalyst, future_confirmation, cutoff=KNOWN_AT)


HIST_CUTOFF = datetime(2019, 11, 11, 20, 30, tzinfo=UTC)
REVIEW_LONG_AFTER = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)


def _historical_catalyst() -> tuple:
    observation = _observation(
        start=date(2019, 12, 1),
        end=date(2019, 12, 31),
        known_at=HIST_CUTOFF - timedelta(days=5),
    )
    catalyst = normalize_catalyst((observation,), cutoff=HIST_CUTOFF)
    return catalyst, observation


def _historical_confirmation(catalyst, **overrides) -> HistoricalCatalystConfirmation:
    fields = {
        "catalyst_version_id": catalyst.id,
        "reviewer": "historical-reviewer",
        "evidence_cutoff": HIST_CUTOFF,
        "reviewed_at": REVIEW_LONG_AFTER,
        "decision": "CONFIRMED",
        "evidence_ids_reviewed": catalyst.supporting_evidence_ids,
        "conflict_resolution_notes": "No unresolved source conflict.",
    }
    fields.update(overrides)
    return HistoricalCatalystConfirmation(**fields)


def test_historical_confirmation_permits_review_long_after_evidence_cutoff() -> None:
    """A real human reviewing 2019 evidence in 2026 is retrospective review
    working as intended, not a stale/late confirmation - the opposite of what
    the live control (require_human_confirmation) would say about the same
    reviewed_at value.
    """
    catalyst, _ = _historical_catalyst()
    confirmation = _historical_confirmation(catalyst)
    decision = require_historical_catalyst_confirmation(catalyst, confirmation)
    assert decision.rankable is True

    # The same wall-clock review time is illegal for the live control, proving
    # the two paths are genuinely different, not one silently reusing the other.
    live_confirmation = HumanCatalystConfirmation(
        catalyst_version_id=catalyst.id,
        reviewer="historical-reviewer",
        confirmed_at=REVIEW_LONG_AFTER,
        decision="CONFIRMED",
        evidence_ids_reviewed=catalyst.supporting_evidence_ids,
        conflict_resolution_notes="No unresolved source conflict.",
    )
    with pytest.raises(HumanConfirmationRequired):
        require_human_confirmation(catalyst, live_confirmation, cutoff=HIST_CUTOFF)


def test_historical_confirmation_requires_exact_evidence_cutoff_match() -> None:
    """A reviewer cannot claim a looser or different evidence boundary than the
    catalyst version's own frozen resolved_at_cutoff - this is what keeps only
    evidence available by the historical cutoff visible to the reviewer.
    """
    catalyst, _ = _historical_catalyst()
    wrong_cutoff = _historical_confirmation(
        catalyst, evidence_cutoff=HIST_CUTOFF + timedelta(days=1)
    )
    with pytest.raises(HumanConfirmationRequired):
        require_historical_catalyst_confirmation(catalyst, wrong_cutoff)


def test_historical_confirmation_rejects_outcome_data_shown() -> None:
    """Outcome data must be inaccessible before decision lock; a confirmation
    that admits outcome data was shown cannot even be constructed.
    """
    catalyst, _ = _historical_catalyst()
    with pytest.raises(pydantic.ValidationError):
        _historical_confirmation(catalyst, outcome_data_shown=True)


def test_historical_confirmation_rejects_backdated_review() -> None:
    """reviewed_at before evidence_cutoff would mean the reviewer judged
    evidence before it was even locked in - a backdated timestamp.
    """
    catalyst, _ = _historical_catalyst()
    with pytest.raises(pydantic.ValidationError):
        _historical_confirmation(catalyst, reviewed_at=HIST_CUTOFF - timedelta(seconds=1))


def test_historical_confirmation_records_reviewer_identity_and_is_immutable_and_hashable() -> None:
    catalyst, _ = _historical_catalyst()
    confirmation = _historical_confirmation(catalyst, reviewer="dr-jane-reviewer")
    assert confirmation.reviewer == "dr-jane-reviewer"

    with pytest.raises(pydantic.ValidationError):
        confirmation.reviewer = "someone-else"  # type: ignore[misc]

    digest_a = deterministic_record_hash(confirmation)
    digest_b = deterministic_record_hash(
        _historical_confirmation(catalyst, reviewer="dr-jane-reviewer")
    )
    assert digest_a == digest_b
    digest_different_reviewer = deterministic_record_hash(
        _historical_confirmation(catalyst, reviewer="dr-jane-reviewer-2")
    )
    assert digest_a != digest_different_reviewer


def test_historical_confirmation_cannot_reference_wrong_catalyst_version() -> None:
    catalyst, _ = _historical_catalyst()
    other_observation = _observation(
        evidence_id=uuid4(),
        start=date(2020, 1, 1),
        end=date(2020, 1, 31),
        known_at=HIST_CUTOFF - timedelta(days=5),
    )
    other_catalyst = normalize_catalyst((other_observation,), cutoff=HIST_CUTOFF)
    mismatched = _historical_confirmation(other_catalyst)
    with pytest.raises(HumanConfirmationRequired):
        require_historical_catalyst_confirmation(catalyst, mismatched)


def test_historical_confirmation_requires_all_supporting_evidence_reviewed() -> None:
    """Later information cannot leak into the reconstructed state via a
    reviewer who attests to less evidence than the frozen catalyst version
    actually used - the reviewed set must be a superset.
    """
    catalyst, _ = _historical_catalyst()
    partial = _historical_confirmation(catalyst, evidence_ids_reviewed=(uuid4(),))
    with pytest.raises(HumanConfirmationRequired):
        require_historical_catalyst_confirmation(catalyst, partial)


def test_historical_confirmation_missing_or_rejected_is_not_rankable() -> None:
    catalyst, _ = _historical_catalyst()
    with pytest.raises(HumanConfirmationRequired):
        require_historical_catalyst_confirmation(catalyst, None)

    rejected = _historical_confirmation(catalyst, decision="REJECTED")
    decision = require_historical_catalyst_confirmation(catalyst, rejected)
    assert decision.rankable is False


def test_historical_confirmation_unresolved_conflict_requires_notes() -> None:
    sec = _observation(
        start=date(2019, 12, 1),
        end=date(2019, 12, 31),
        known_at=HIST_CUTOFF - timedelta(days=5),
    )
    ctgov = _observation(
        tier=EvidenceTier.CLINICAL_TRIALS_REGISTRY,
        start=date(2020, 1, 1),
        end=date(2020, 1, 31),
        known_at=HIST_CUTOFF - timedelta(days=5),
    )
    catalyst = normalize_catalyst((sec, ctgov), cutoff=HIST_CUTOFF)
    assert catalyst.has_unresolved_conflict
    blank_notes = _historical_confirmation(catalyst, conflict_resolution_notes=" ")
    with pytest.raises(CatalystConflictError):
        require_historical_catalyst_confirmation(catalyst, blank_notes)


def test_scientific_pack_is_manual_review_only_and_point_in_time() -> None:
    observation = _observation()
    catalyst = normalize_catalyst((observation,), cutoff=KNOWN_AT)
    pack = build_scientific_evidence_pack(
        catalyst_version_id=catalyst.id,
        asset="BOE-101",
        indication="Example disease",
        clinical_phase="Phase 2",
        trial_ids=("NCT01234567",),
        study_design="Randomized double-blind placebo-controlled",
        enrollment=120,
        randomized=True,
        blinded=True,
        comparator="Placebo",
        primary_endpoints=("Change in endpoint",),
        secondary_endpoints=("Safety",),
        primary_completion_date=date(2026, 11, 1),
        study_status="ACTIVE_NOT_RECRUITING",
        safety_signals=(),
        regulatory_context=(),
        evidence_ids=(observation.evidence_id,),
        evidence_cutoff=KNOWN_AT,
        generated_at=KNOWN_AT,
    )
    assert pack.manual_review_required is True
    assert pack.catalyst_version_id == catalyst.id


def test_point_in_time_audit_detects_post_cutoff_leakage() -> None:
    in_cutoff = _observation()
    future = _observation(known_at=KNOWN_AT + timedelta(days=1))
    passed = audit_point_in_time(cutoff=KNOWN_AT, observations=(in_cutoff,))
    assert passed.passed is True
    failed = audit_point_in_time(cutoff=KNOWN_AT, observations=(in_cutoff, future))
    assert failed.passed is False
    assert len(failed.findings) == 1
