from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from boe.catalysts import (
    CatalystObservation,
    HumanCatalystConfirmation,
    HumanConfirmationRequired,
    normalize_catalyst,
    require_human_confirmation,
)
from boe.enums import CatalystType, EvidenceTier, TimingConfidence
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
