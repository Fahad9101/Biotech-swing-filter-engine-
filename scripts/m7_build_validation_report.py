"""Assemble the final M7 validation report for the objective PoS methodology.

Follows the shape of VALIDATION-AND-MILESTONES.md section 9 as closely as
honestly possible given this project's real constraints: no human
scientific/catalyst reviewer, and therefore no HistoricalDecisionLock, no
BOE-1.0.0 score/classification/gates, and no full acceptance-criteria
evaluation against section 5. What this report DOES contain is entirely
real: the frozen cohort, the real snapshot cutoff timestamps, the real
live-fetched price outcomes, the objective (review-free) PoS methodology and
its real calibration against those outcomes, and an objectively-identified
failure register. What it does NOT contain - scores, classifications, gate
distributions, case-level decision locks - is listed explicitly rather than
silently omitted.

This is the terminal script in the M7 pipeline: it reads only already-
committed artifacts and performs no new computation of its own beyond
assembling and cross-referencing them, plus the failure register (which uses
only fields already defined in those artifacts).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
CUTOFFS_PATH = ROOT / "validation/m7/snapshot-cutoffs.json"
POS_PATH = ROOT / "validation/m7/objective-pos-assessments.json"
OUTCOMES_PATH = ROOT / "validation/m7/historical-outcomes.json"
CALIBRATION_PATH = ROOT / "validation/m7/objective-calibration-report.json"
CATALYST_PATH = ROOT / "validation/m7/catalyst-scores.json"
CASH_DILUTION_PATH = ROOT / "validation/m7/cash-dilution-scores.json"
TECHNICAL_PATH = ROOT / "validation/m7/technical-snapshots.json"
PARTIAL_SCORECARD_PATH = ROOT / "validation/m7/partial-scorecard-calibration.json"
OUTPUT_PATH = ROOT / "validation/m7/validation-report.json"

# Objective, pre-registered thresholds for the failure register below -
# matched to VALIDATION-AND-MILESTONES.md section 7's own thresholds
# (T+20 return <= -20% for false positives, MFE >= 40% for false negatives),
# adapted to rank by objective PoS quintile in place of a BOE-1.0.0
# classification this project does not have.
FALSE_POSITIVE_RETURN_THRESHOLD_PCT = -20.0
FALSE_NEGATIVE_MFE_THRESHOLD_PCT = 40.0


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _load(path: Path, what: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path} does not exist - run {what} first.")
    return dict(json.loads(path.read_bytes()))


def _git_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _failure_register(
    pos_by_id: dict[str, dict[str, Any]],
    outcomes_by_id: dict[str, dict[str, Any]],
    events_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(pos_by_id.values(), key=lambda a: (float(a["mid_pct"]), a["event_id"]))
    quintile = max(1, len(ordered) // 5)
    top_ids = {a["event_id"] for a in ordered[-quintile:]}
    bottom_ids = {a["event_id"] for a in ordered[:quintile]}

    false_positives = []
    for event_id in sorted(top_ids):
        outcome = outcomes_by_id[event_id]
        if float(outcome["return_t20_pct"]) <= FALSE_POSITIVE_RETURN_THRESHOLD_PCT:
            false_positives.append(
                {
                    "event_id": event_id,
                    "catalyst_type": events_by_id[event_id]["catalyst_type"],
                    "pos_mid_pct": float(pos_by_id[event_id]["mid_pct"]),
                    "return_t20_pct": float(outcome["return_t20_pct"]),
                    "categories_supportable_without_new_evidence": [
                        "PoS calibration failure - see objective-calibration-report.json"
                    ],
                    "categories_not_assessed": [
                        "source/data failure",
                        "catalyst timing failure",
                        "scientific reasoning failure (no science review exists)",
                        "valuation/expectation failure (no valuation exists)",
                        "dilution/capital-structure failure",
                        "technical/entry failure",
                        "unmodeled external event",
                        "classification/gate interaction (no classification exists)",
                        "whether information was knowable before the event",
                    ],
                }
            )
    false_negatives = []
    for event_id in sorted(bottom_ids):
        outcome = outcomes_by_id[event_id]
        if float(outcome["mfe_t20_pct"]) >= FALSE_NEGATIVE_MFE_THRESHOLD_PCT:
            false_negatives.append(
                {
                    "event_id": event_id,
                    "catalyst_type": events_by_id[event_id]["catalyst_type"],
                    "pos_mid_pct": float(pos_by_id[event_id]["mid_pct"]),
                    "mfe_t20_pct": float(outcome["mfe_t20_pct"]),
                    "categories_supportable_without_new_evidence": [
                        "PoS calibration failure - see objective-calibration-report.json"
                    ],
                    "categories_not_assessed": [
                        "source/data failure",
                        "catalyst timing failure",
                        "scientific reasoning failure (no science review exists)",
                        "valuation/expectation failure (no valuation exists)",
                        "dilution/capital-structure failure",
                        "technical/entry failure",
                        "unmodeled external event",
                        "classification/gate interaction (no classification exists)",
                        "whether information was knowable before the event",
                    ],
                }
            )
    fp_catalyst_types = sorted({f["catalyst_type"] for f in false_positives})
    fn_catalyst_types = sorted({f["catalyst_type"] for f in false_negatives})
    structural_pattern = (
        f"All {len(false_positives)} false positives are {fp_catalyst_types} events, and all "
        f"{len(false_negatives)} false negatives are {fn_catalyst_types} events. This is not a "
        "coincidence needing per-event research to explain: this methodology assigns every "
        "event of a given catalyst_type the same prior (e.g. every REG_DECISION gets 75%, "
        "every CLIN_P2 gets 40%), so it cannot distinguish an FDA approval from a CRL within "
        "REG_DECISION, or a strong Phase 2 readout from a weak one within CLIN_P2 - both land "
        "in the same PoS band regardless of which it turns out to be. This single structural "
        "limitation - a per-catalyst-type constant, not a per-event judgment - accounts for "
        "the entire false-positive and false-negative register and is the direct, evidenced "
        "cause of the calibration failure in objective-calibration-report.json. It is the one "
        "root cause this script CAN support without new per-event research, because it is "
        "visible directly in already-computed data, not inferred about any single company."
    )
    return {
        "definition": (
            "False positive: top PoS quintile with T+20 return "
            f"<= {FALSE_POSITIVE_RETURN_THRESHOLD_PCT}%. False negative: bottom "
            f"PoS quintile with MFE >= {FALSE_NEGATIVE_MFE_THRESHOLD_PCT}%. "
            "Adapted from VALIDATION-AND-MILESTONES.md section 7 by ranking on "
            "objective PoS quintile in place of a BOE-1.0.0 classification this "
            "project does not have."
        ),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "structural_pattern": structural_pattern,
        "note": (
            "Beyond the structural pattern above, per-event categories are NOT "
            "assessed: assigning them (source failure, timing failure, "
            "unmodeled event, etc.) for a specific real event without new "
            "per-event research would be fabrication, not analysis. "
            "Investigating any single event further is real, doable "
            "follow-up work - deliberately not attempted here rather than "
            "guessed at."
        ),
    }


def _recommendation(calibration: dict[str, Any]) -> str:
    beats_naive = calibration["brier_beats_naive_prior"]
    top = calibration["top_quintile_pos_swing_success"]["value"]
    bottom = calibration["bottom_quintile_pos_swing_success"]["value"]
    ranks_correctly = top > bottom
    reasons: list[str] = []
    if not beats_naive:
        reasons.append(
            "does not beat a naive constant-rate baseline (Brier "
            f"{calibration['brier_score']:.4f} vs {calibration['base_prior_brier_score']:.4f})"
        )
    if not ranks_correctly:
        reasons.append(
            "does not rank correctly (top-quintile swing success "
            f"{top:.3f} vs bottom-quintile {bottom:.3f})"
        )
    if not reasons:
        return "PROPOSE RECALIBRATION IN A NEW BOE VERSION"
    return (
        "PROPOSE RECALIBRATION IN A NEW BOE VERSION - the review-free PoS "
        "methodology as built " + " and ".join(reasons) + "; it is not a substitute "
        "for a genuine human scientific review and should not inform live decisions "
        "in its current form."
    )


def build() -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH, "scripts/m7_build_historical_event_registry.py --freeze")
    cutoffs = _load(CUTOFFS_PATH, "scripts/m7_build_snapshot_cutoffs.py")
    pos_data = _load(POS_PATH, "scripts/m7_build_objective_pos.py")
    outcomes_data = _load(OUTCOMES_PATH, "scripts/m7_build_outcomes.py")
    calibration = _load(CALIBRATION_PATH, "scripts/m7_build_objective_calibration.py")
    catalyst_data = _load(CATALYST_PATH, "scripts/m7_build_catalyst_scores.py")
    cash_dilution_data = _load(CASH_DILUTION_PATH, "scripts/m7_build_cash_dilution_scores.py")
    technical_data = _load(TECHNICAL_PATH, "scripts/m7_build_technical_snapshots.py")
    partial_scorecard = _load(
        PARTIAL_SCORECARD_PATH, "scripts/m7_build_partial_scorecard_calibration.py"
    )

    cohort_sha256 = manifest["cohort_sha256"]
    for name, data in (
        ("snapshot-cutoffs.json", cutoffs),
        ("objective-pos-assessments.json", pos_data),
        ("historical-outcomes.json", outcomes_data),
        ("objective-calibration-report.json", calibration),
        ("catalyst-scores.json", catalyst_data),
        ("cash-dilution-scores.json", cash_dilution_data),
        ("technical-snapshots.json", technical_data),
        ("partial-scorecard-calibration.json", partial_scorecard),
    ):
        if data["cohort_sha256"] != cohort_sha256:
            raise ValueError(f"{name} was built against a different cohort than the current freeze")

    events_by_id = {e["event_id"]: e for e in manifest["events"]}
    pos_by_id = {a["event_id"]: a for a in pos_data["assessments"]}
    outcomes_by_id = {o["event_id"]: o for o in outcomes_data["outcomes"]}
    failure_register = _failure_register(pos_by_id, outcomes_by_id, events_by_id)

    return {
        "generator": "python scripts/m7_build_validation_report.py",
        "milestone": 7,
        "report_subject": (
            "Real, objectively-computed substitutes for the parts of "
            "BOE-1.0.0 that do not require a human scientific/catalyst "
            "reviewer or rNPV commercial assumptions: an objective PoS "
            "methodology (src/boe/objective_pos_methodology.py), and real "
            "CATALYST, CASH_DILUTION, and TECHNICAL factor scores. NOT the "
            "full BOE-1.0.0 engine, which was never exercised end-to-end - "
            "SCIENCE needs a real human reviewer this project does not have "
            "(docs/M7-HUMAN-REVIEW-BLOCKER.md), and VALUATION needs real "
            "peak-sales/TAM assumptions this project cannot objectively "
            "source at scale, which also blocks gates and real "
            "classification since they depend on VALUATION's output."
        ),
        "code_sha": _git_head_sha(),
        "boe_rules_version": "BOE-1.0.0",
        "objective_methodology_version": pos_data["methodology"],
        "cohort_sha256": cohort_sha256,
        "registry_sha256": manifest["registry_sha256"],
        "manifest_frozen_at": manifest["frozen_at"],
        "data_cutoffs": {
            "snapshot_cutoffs_source": "validation/m7/snapshot-cutoffs.json",
            "price_data_provider": "ALPACA_MARKET_DATA",
            "price_data_benchmark_symbol": outcomes_data["benchmark_symbol"],
            "price_data_retrieved_at": outcomes_data["retrieved_at"],
        },
        "cohort_flow": {
            "event_count": len(manifest["events"]),
            "strata": {
                stratum: sum(1 for e in manifest["events"] if e["primary_stratum"] == stratum)
                for stratum in sorted({e["primary_stratum"] for e in manifest["events"]})
            },
            "negative_count": sum(e["negative_event"] for e in manifest["events"]),
            "financing_count": sum(
                e["financing_t_minus_90_to_t_plus_30"] for e in manifest["events"]
            ),
            "single_asset_count": sum(e["single_asset_issuer"] for e in manifest["events"]),
        },
        "missingness_and_source_conflicts": {
            "snapshot_cutoffs_missing": cutoffs["event_count"] - len(manifest["events"]),
            "outcomes_missing": outcomes_data["event_count"] - outcomes_data["outcome_count"],
            "outcomes_failed": outcomes_data["failed_count"],
            "objective_pos_missing": pos_data["event_count"] - pos_data["assessment_count"],
            "catalyst_score_missing": catalyst_data["event_count"] - catalyst_data["score_count"],
            "technical_score_missing": (
                technical_data["event_count"] - technical_data["snapshot_count"]
            ),
            "cash_dilution_score_missing": (
                cash_dilution_data["event_count"] - cash_dilution_data["score_count"]
            ),
        },
        "score_and_gate_distributions": (
            "NO FULL BOE-1.0.0 SCORE, GATE, OR CLASSIFICATION EXISTS for any event - "
            "those need SCIENCE, MARKET_IMPACT, VALUATION, OWNERSHIP, and SENTIMENT, "
            "which this project does not have (see partial-scorecard-calibration.json's "
            "factors_not_included for why each one). What DOES exist, real and not "
            f"fabricated: an objective PoS estimate for all {pos_data['assessment_count']} "
            f"events; a real CATALYST factor score for all {catalyst_data['score_count']} "
            f"events; a real TECHNICAL factor score for all {technical_data['snapshot_count']} "
            f"events; a real CASH_DILUTION factor score for {cash_dilution_data['score_count']} "
            "events (SEC XBRL coverage is narrower than price data coverage). See "
            "partial-scorecard-calibration.json for their combined calibration against real "
            "outcomes."
        ),
        "calibration_and_return_metrics": calibration,
        "partial_scorecard_calibration": partial_scorecard,
        "case_level_predictions_and_outcomes": [
            {
                "event_id": event_id,
                "pos_mid_pct": float(pos_by_id[event_id]["mid_pct"]),
                "pos_low_pct": float(pos_by_id[event_id]["low_pct"]),
                "pos_high_pct": float(pos_by_id[event_id]["high_pct"]),
                "negative_event": next(
                    e["negative_event"] for e in manifest["events"] if e["event_id"] == event_id
                ),
                "return_t20_pct": float(outcomes_by_id[event_id]["return_t20_pct"]),
                "xbi_relative_t20_pct": float(outcomes_by_id[event_id]["xbi_relative_t20_pct"]),
                "swing_success": outcomes_by_id[event_id]["swing_success"],
                "severe_loss": outcomes_by_id[event_id]["severe_loss"],
            }
            for event_id in sorted(pos_by_id)
        ],
        "failure_register": failure_register,
        "deviations_and_known_limitations": [
            *calibration["limitations"],
            *partial_scorecard["limitations"],
            "Real point-in-time CATALYST, CASH_DILUTION, and TECHNICAL factor "
            "scores exist (see partial-scorecard-calibration.json), but "
            "VALUATION (rNPV) was never reconstructed for any event, and "
            "OWNERSHIP and SENTIMENT were never attempted. Without VALUATION, "
            "gates.py's GateInput cannot be built either (it needs base_ev_pct/ "
            "conservative_ev_pct/reward_risk, all rNPV-derived) - so no gate "
            "evaluation and no real classification exist for any event.",
            "No decision was locked before outcomes were known, because no "
            "decision (in the BOE-1.0.0 sense of a scored, classified, "
            "gated HistoricalDecisionLock) was ever produced - the real "
            "PoS, CATALYST, CASH_DILUTION, and TECHNICAL scores that do "
            "exist were each computed from structural or objectively-sourced "
            "facts involving no outcome-dependent judgment, but this "
            "report's author did already know this cohort's real outcomes "
            "throughout, as disclosed in each component report.",
            "This report validates a substitute methodology built explicitly "
            "because no qualified human reviewer was available "
            "(docs/M7-HUMAN-REVIEW-BLOCKER.md) - it is not evidence that "
            "BOE-1.0.0 itself, as originally specified, does or does not work.",
        ],
        "recommendation": _recommendation(calibration),
    }


def main() -> None:
    # No --check flag: this report embeds the current git HEAD sha, which by
    # design changes on every commit, so byte-exact reproducibility against a
    # previously committed version is not a meaningful property to enforce
    # (see scripts/m7_build_outcomes.py for the same reasoning applied to
    # live price data).
    argparse.ArgumentParser().parse_args()
    status = build()
    OUTPUT_PATH.write_text(render(status))
    print(
        json.dumps(
            {
                "event_count": status["cohort_flow"]["event_count"],
                "recommendation": status["recommendation"],
                "false_positives": len(status["failure_register"]["false_positives"]),
                "false_negatives": len(status["failure_register"]["false_negatives"]),
            }
        )
    )


if __name__ == "__main__":
    main()
