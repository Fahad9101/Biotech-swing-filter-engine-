"""Build real CATALYST factor scores at T-30 for the frozen Milestone 7
cohort, using the already-built, already-tested scorecard machinery
(src/boe/scoring.py::score_catalyst). Pure function of the already-frozen
manifest - no live network calls, no new evidence.

CATALYST has five subfactors (contracts/boe-scorecard.v1.0.0.json), of which
three are genuinely objective and two are not, for the same reason SCIENCE,
FINANCING_OVERHANG, and TECHNICAL's STRUCTURE subfactor are not: assessing
them honestly requires reading and judging the substance of a specific
catalyst, not just its structural facts.

Objectively computable, real, not fabricated:
- PROXIMITY: days from the T-30 snapshot to the event is always exactly 30
  by this project's own fixed-snapshot design (VALIDATION-AND-MILESTONES.md
  section 3 makes T-30 the primary snapshot) - every event lands in the same
  frozen 7-42-day band. Not a bug: a consequence of evaluating one fixed
  historical offset per event rather than a live rolling assessment.
- MATURITY: derived from clinical_phase/catalyst_type alone via the frozen
  _derived_maturity_bucket() (boe.scoring), already used for BOE-1.0.0 live
  ranking - the same underlying-phase resolution this project's objective
  PoS methodology already established for conference/publication events
  (scripts/m7_build_objective_pos.py:UNDERLYING_PHASE_BY_CLINICAL_PHASE).
- TIMING_CONFIDENCE: mapped by catalyst_type category below, grounded in a
  real, structural distinction, not a per-event guess: FDA regulatory
  target-action dates (REG_SUBMIT/REG_ADCOM/REG_DECISION) are set by
  statute/policy upon filing acceptance and are public record (HIGH).
  Conference/publication dates are fixed by the organizer/journal well in
  advance and are public (HIGH). Company-guided clinical trial readout
  timing is well documented industry-wide to be subject to real slippage
  (MODERATE) - this is a property of the catalyst type, not an opinion
  about any specific company.

Left MISSING throughout, not fabricated:
- MATERIALITY: how important this specific catalyst is to the company
  (e.g. pivotal/registration-enabling vs. secondary/exploratory) requires
  reading the actual trial protocol or filing - a real judgment call, the
  same category of problem as SCIENCE.
- NOVEL_INFORMATION: whether this specific disclosure represents genuinely
  new information versus an expected, pre-flagged update is likewise a
  judgment about the substance of the disclosure, not a structural fact.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.contracts import load_scorecard  # noqa: E402
from boe.enums import CatalystType, DataState, TimingConfidence  # noqa: E402
from boe.historical_validation import CohortManifest  # noqa: E402
from boe.scoring import (  # noqa: E402
    CatalystScoreInput,
    SubfactorEvidence,
    _derived_maturity_bucket,
    score_catalyst,
)

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/catalyst-scores.json"
SCORECARD_PATH = ROOT / "contracts/boe-scorecard.v1.0.0.json"
SNAPSHOT_LOOKBACK_DAYS = 30

# Structural, catalyst-type-level timing predictability - not a per-event
# judgment. See module docstring for the reasoning behind each grouping.
_HIGH_CONFIDENCE_TYPES = {
    CatalystType.REG_SUBMIT,
    CatalystType.REG_ADCOM,
    CatalystType.REG_DECISION,
    CatalystType.CONF_DATA,
    CatalystType.PUBLICATION,
}

# Underlying-phase resolution for conference/publication events, matching
# scripts/m7_build_objective_pos.py's mapping exactly - reused, not
# reinvented, so the two scripts never disagree about the same fact.
_UNDERLYING_PHASE_BY_CLINICAL_PHASE = {
    "PHASE_1": CatalystType.CLIN_P1,
    "PHASE_1A_1B": CatalystType.CLIN_P1,
    "PHASE_1B": CatalystType.CLIN_P1,
    "PHASE_1_2": CatalystType.CLIN_P1_2,
    "PHASE_2": CatalystType.CLIN_P2,
    "PHASE_2_3": CatalystType.CLIN_P2_3,
    "PHASE_3": CatalystType.CLIN_P3,
    "APPROVED_LIFECYCLE_DATA": CatalystType.REG_OTHER,
}
_NEEDS_UNDERLYING_PHASE = {CatalystType.CONF_DATA, CatalystType.PUBLICATION}

CATALYST_SUBFACTORS = (
    "MATERIALITY",
    "TIMING_CONFIDENCE",
    "PROXIMITY",
    "MATURITY",
    "NOVEL_INFORMATION",
)


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _timing_confidence(catalyst_type: CatalystType) -> TimingConfidence:
    return (
        TimingConfidence.HIGH
        if catalyst_type in _HIGH_CONFIDENCE_TYPES
        else TimingConfidence.MODERATE
    )


def _evidence(rationale: str, evidence_id_seed: str, *, missing: bool) -> SubfactorEvidence:
    if missing:
        return SubfactorEvidence(data_state=DataState.MISSING, rationale=rationale, evidence_ids=())
    return SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=rationale,
        evidence_ids=(uuid5(NAMESPACE_URL, evidence_id_seed),),
    )


def build() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))
    rules = load_scorecard(SCORECARD_PATH).contract

    scores: list[dict[str, Any]] = []
    for event in manifest.events:
        as_of = event.event_at - timedelta(days=SNAPSHOT_LOOKBACK_DAYS)
        timing_confidence = _timing_confidence(event.catalyst_type)

        maturity_bucket = None
        if event.catalyst_type in _NEEDS_UNDERLYING_PHASE:
            underlying = _UNDERLYING_PHASE_BY_CLINICAL_PHASE.get(event.clinical_phase)
            if underlying is None:
                raise ValueError(
                    f"{event.event_id}: no underlying-phase mapping for "
                    f"clinical_phase={event.clinical_phase!r}"
                )
            maturity_bucket = _derived_maturity_bucket(underlying)
        # For every other catalyst_type, score_catalyst() itself falls back
        # to _derived_maturity_bucket(event.catalyst_type) when
        # maturity_bucket is None (the same frozen BOE-1.0.0 live-ranking
        # behavior) - resolve it here too purely for transparent reporting,
        # not to change what gets scored.
        effective_maturity_bucket = maturity_bucket or _derived_maturity_bucket(event.catalyst_type)

        score_input = CatalystScoreInput(
            as_of=as_of,
            catalyst_type=event.catalyst_type,
            window_start=event.event_at.date(),
            timing_confidence=timing_confidence,
            materiality_points=None,
            novelty_points=None,
            maturity_bucket=maturity_bucket,
            evidence={
                "MATERIALITY": _evidence(
                    "How important this specific catalyst is to the company "
                    "requires reading the actual trial protocol/filing - a "
                    "real judgment call, not a structural fact.",
                    f"m7-materiality-{event.event_id}",
                    missing=True,
                ),
                "TIMING_CONFIDENCE": _evidence(
                    f"{timing_confidence.value}: {event.catalyst_type.value} dates are "
                    + (
                        "set by statute/policy or a conference/journal schedule and are "
                        "public record."
                        if timing_confidence is TimingConfidence.HIGH
                        else "company-guided and documented industry-wide to be subject to "
                        "real slippage."
                    ),
                    f"m7-timing-{event.event_id}",
                    missing=False,
                ),
                "PROXIMITY": _evidence(
                    "Exactly 30 days by this project's fixed T-30 snapshot design.",
                    f"m7-proximity-{event.event_id}",
                    missing=False,
                ),
                "MATURITY": _evidence(
                    f"Derived from catalyst_type={event.catalyst_type.value} "
                    f"(clinical_phase={event.clinical_phase}) via the frozen "
                    "_derived_maturity_bucket().",
                    f"m7-maturity-{event.event_id}",
                    missing=False,
                ),
                "NOVEL_INFORMATION": _evidence(
                    "Whether this disclosure was genuinely new versus an "
                    "expected, pre-flagged update is a judgment about its "
                    "substance, not a structural fact.",
                    f"m7-novelty-{event.event_id}",
                    missing=True,
                ),
            },
        )
        factor_score = score_catalyst(score_input, rules)
        scores.append(
            {
                "event_id": event.event_id,
                "catalyst_type": event.catalyst_type.value,
                "t_minus_30": as_of.date().isoformat(),
                "timing_confidence": timing_confidence.value,
                "maturity_bucket": effective_maturity_bucket,
                "catalyst_factor_points": factor_score.points,
                "catalyst_factor_max_points": factor_score.max_points,
            }
        )

    scores.sort(key=lambda r: str(r["event_id"]))
    return {
        "generator": "python scripts/m7_build_catalyst_scores.py",
        "cohort_sha256": manifest.cohort_sha256,
        "snapshot_label": "T_MINUS_30",
        "event_count": len(manifest.events),
        "score_count": len(scores),
        "scores": scores,
        "methodology_notes": [
            "PROXIMITY is a constant 4/4 for every event: this project "
            "evaluates one fixed T-30 snapshot per event rather than a live "
            "rolling assessment, so days-to-catalyst is always exactly 30.",
            "MATURITY is fully derived from catalyst_type/clinical_phase via "
            "the frozen _derived_maturity_bucket() - the same function "
            "BOE-1.0.0 live ranking uses, not new logic.",
            "TIMING_CONFIDENCE is mapped by catalyst_type category (HIGH for "
            "regulatory/conference/publication dates set externally and "
            "publicly; MODERATE for company-guided clinical readouts), not "
            "assessed per event.",
            "MATERIALITY and NOVEL_INFORMATION are always MISSING: both "
            "require judging the substance of a specific catalyst, not just "
            "its structural facts - the same category of problem SCIENCE "
            "has. Real coverage here is 14 of 25 max CATALYST points "
            "(TIMING_CONFIDENCE 5 + PROXIMITY 4 + MATURITY 5).",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    status = build()
    expected = render(status)
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text() != expected:
            raise SystemExit(f"Stale generated artifact: {OUTPUT_PATH.relative_to(ROOT)}")
    else:
        OUTPUT_PATH.write_text(expected)
    print(f"computed {status['score_count']} of {status['event_count']} catalyst scores")


if __name__ == "__main__":
    main()
