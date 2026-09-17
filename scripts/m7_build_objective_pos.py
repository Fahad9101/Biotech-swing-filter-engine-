"""Compute the review-free objective PoS estimate for every frozen M7 event.

See src/boe/objective_pos_methodology.py for what this is and, more
importantly, what it deliberately is not: not BOE-1.0.0, not a human
scientific review, not a fabricated substitute for one. It is a single,
transparent, structural input (catalyst_type, resolved to an underlying
clinical phase for conference/publication events) run through BOE-1.0.0's
own frozen, non-review-dependent prior table.

Live network calls: none. Pure function of the already-frozen, already-
committed cohort manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.enums import CatalystType  # noqa: E402
from boe.historical_validation import CohortManifest  # noqa: E402
from boe.objective_pos_methodology import estimate_objective_pos  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/objective-pos-assessments.json"

# Maps the free-text clinical_phase recorded on conference/publication events
# (see scripts/m7_build_historical_event_registry.py) to the CatalystType
# BOE-1.0.0's own frozen prior table is keyed by. This is a structural
# classification of what stage of development the underlying trial was in -
# not a judgment about trial quality - but two entries require a documented
# call: PHASE_1B and PHASE_1A_1B are both kept as Phase 1 proper (still
# single-arm dose/expansion work, not yet a controlled Phase 2), and
# APPROVED_LIFECYCLE_DATA (post-approval follow-up data with no pre-approval
# "phase" of its own) falls back to REG_OTHER, the frozen table's generic,
# uninformative 50% regulatory-adjacent bucket.
UNDERLYING_PHASE_BY_CLINICAL_PHASE = {
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


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def build() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))

    assessments: list[dict[str, Any]] = []
    for event in manifest.events:
        underlying_phase = None
        if event.catalyst_type in _NEEDS_UNDERLYING_PHASE:
            underlying_phase = UNDERLYING_PHASE_BY_CLINICAL_PHASE.get(event.clinical_phase)
            if underlying_phase is None:
                raise ValueError(
                    f"{event.event_id}: no underlying-phase mapping for "
                    f"clinical_phase={event.clinical_phase!r}"
                )
        assessment = estimate_objective_pos(
            event_id=event.event_id,
            catalyst_type=event.catalyst_type,
            underlying_phase=underlying_phase,
        )
        assessments.append(assessment.model_dump(mode="json"))

    assessments.sort(key=lambda a: str(a["event_id"]))
    return {
        "generator": "python scripts/m7_build_objective_pos.py",
        "methodology": "src/boe/objective_pos_methodology.py",
        "cohort_sha256": manifest.cohort_sha256,
        "event_count": len(manifest.events),
        "assessment_count": len(assessments),
        "assessments": assessments,
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
    print(
        f"computed {status['assessment_count']} of {status['event_count']} "
        "objective PoS assessments"
    )


if __name__ == "__main__":
    main()
