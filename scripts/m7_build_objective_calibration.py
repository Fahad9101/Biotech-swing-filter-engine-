"""Calibrate the review-free objective PoS methodology against real outcomes.

This is the honest, narrowed substitute for VALIDATION-AND-MILESTONES.md
section 5's calibration and ranking metrics. boe.historical_validation's
summarize_validation() is NOT used here: it requires real HistoricalDecisionLock
records (raw_score, classification, gate_codes) from a full 8-factor
BOE-1.0.0 scorecard, which in turn needs point-in-time financial, technical,
and valuation reconstruction for all 120 events that this project has never
performed and is not attempting here (see docs/M7-HUMAN-REVIEW-BLOCKER.md and
docs/M7-OBJECTIVE-METHODOLOGY.md for why: replicating those inputs honestly is
its own large, separate undertaking, not attempted alongside the PoS
substitute). Building fake decisions/classifications just to satisfy that
function's shape would be fabrication of a different kind - a fake score
standing in for a fake review. This script instead compares the one real
thing this project has - an objective, review-free PoS estimate - against
the one other real thing it has - real, live-fetched price outcomes - using
only boe.historical_validation's data-independent statistics helpers
(brier_score, wilson_rate).

The ground truth for "did the catalyst succeed" is the frozen cohort's own
negative_event field (inverted): a real, already-curated label describing
whether the disclosed result was a trial failure, CRL, material safety
issue, or clinically disappointing data - not something computed by this
script, and not the market-price-based swing_success/severe_loss fields
used separately below for the return-based comparisons.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.historical_validation import brier_score, wilson_rate  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
POS_PATH = ROOT / "validation/m7/objective-pos-assessments.json"
OUTCOMES_PATH = ROOT / "validation/m7/historical-outcomes.json"
OUTPUT_PATH = ROOT / "validation/m7/objective-calibration-report.json"


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _load(path: Path, what: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path} does not exist - run {what} first.")
    return dict(json.loads(path.read_bytes()))


def _band_calibration(rows: list[dict[str, Any]], n_bands: int = 5) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: (r["pos_mid_pct"], r["event_id"]))
    size = max(1, len(ordered) // n_bands)
    bands = []
    for start in range(0, len(ordered), size):
        chunk = ordered[start : start + size]
        if not chunk:
            continue
        successes = sum(r["observed_success"] for r in chunk)
        rate = wilson_rate(successes, len(chunk))
        mean_predicted = statistics.mean(r["pos_mid_pct"] for r in chunk) / 100.0
        bands.append(
            {
                "n": len(chunk),
                "pos_mid_pct_range": [
                    min(r["pos_mid_pct"] for r in chunk),
                    max(r["pos_mid_pct"] for r in chunk),
                ],
                "mean_predicted_pct": round(mean_predicted * 100, 2),
                "observed_success_rate_pct": round(rate.value * 100, 2),
                "deviation_pp": round(abs(mean_predicted - rate.value) * 100, 2),
                "within_20pp": abs(mean_predicted - rate.value) * 100 <= 20.0
                if len(chunk) >= 15
                else None,
            }
        )
    return bands


def build() -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH, "scripts/m7_build_historical_event_registry.py --freeze")
    pos_data = _load(POS_PATH, "scripts/m7_build_objective_pos.py")
    outcomes_data = _load(OUTCOMES_PATH, "scripts/m7_build_outcomes.py")

    cohort_sha256 = manifest["cohort_sha256"]
    if (
        pos_data["cohort_sha256"] != cohort_sha256
        or outcomes_data["cohort_sha256"] != cohort_sha256
    ):
        raise ValueError(
            "objective-pos-assessments.json or historical-outcomes.json was built "
            "against a different cohort - regenerate both before calibrating."
        )

    events_by_id = {e["event_id"]: e for e in manifest["events"]}
    pos_by_id = {a["event_id"]: a for a in pos_data["assessments"]}
    outcomes_by_id = {o["event_id"]: o for o in outcomes_data["outcomes"]}

    matched_ids = sorted(set(events_by_id) & set(pos_by_id) & set(outcomes_by_id))
    if len(matched_ids) != len(events_by_id):
        raise ValueError(
            f"only {len(matched_ids)} of {len(events_by_id)} events have both a PoS "
            "assessment and a real outcome - both artifacts must cover the full cohort."
        )

    rows = []
    for event_id in matched_ids:
        event = events_by_id[event_id]
        pos = pos_by_id[event_id]
        outcome = outcomes_by_id[event_id]
        rows.append(
            {
                "event_id": event_id,
                "primary_stratum": event["primary_stratum"],
                "pos_mid_pct": float(pos["mid_pct"]),
                # Ground truth for PoS calibration: the real, already-curated
                # negative_event label, inverted. Not derived here.
                "observed_success": not event["negative_event"],
                # Separately, real market-price-based outcome fields, used
                # only for the return-based comparisons below - never mixed
                # into the PoS-calibration ground truth above.
                "xbi_relative_t20_pct": float(outcome["xbi_relative_t20_pct"]),
                "swing_success": bool(outcome["swing_success"]),
                "severe_loss": bool(outcome["severe_loss"]),
            }
        )

    predicted = tuple(r["pos_mid_pct"] for r in rows)
    observed = tuple(r["observed_success"] for r in rows)
    brier = brier_score(predicted, observed)
    naive_prior = statistics.mean(observed) * 100.0
    base_brier = brier_score(tuple(naive_prior for _ in rows), observed)

    strata: dict[str, Any] = {}
    for stratum in sorted({r["primary_stratum"] for r in rows}):
        stratum_rows = [r for r in rows if r["primary_stratum"] == stratum]
        strata[stratum] = {
            "n": len(stratum_rows),
            "brier_score": brier_score(
                tuple(r["pos_mid_pct"] for r in stratum_rows),
                tuple(r["observed_success"] for r in stratum_rows),
            ),
        }

    ordered_by_pos = sorted(rows, key=lambda r: (r["pos_mid_pct"], r["event_id"]))
    quintile = max(1, len(ordered_by_pos) // 5)
    bottom = ordered_by_pos[:quintile]
    top = ordered_by_pos[-quintile:]
    top_swing = wilson_rate(sum(r["swing_success"] for r in top), len(top))
    bottom_swing = wilson_rate(sum(r["swing_success"] for r in bottom), len(bottom))
    top_returns = [r["xbi_relative_t20_pct"] for r in top]
    bottom_returns = [r["xbi_relative_t20_pct"] for r in bottom]

    return {
        "generator": "python scripts/m7_build_objective_calibration.py",
        "methodology": "src/boe/objective_pos_methodology.py",
        "cohort_sha256": cohort_sha256,
        "event_count": len(rows),
        "brier_score": brier,
        "naive_prior_pct": round(naive_prior, 2),
        "base_prior_brier_score": base_brier,
        "brier_beats_naive_prior": brier <= base_brier,
        "brier_score_by_stratum": strata,
        "pos_band_calibration": _band_calibration(rows),
        "top_quintile_pos_swing_success": top_swing.model_dump(mode="json"),
        "bottom_quintile_pos_swing_success": bottom_swing.model_dump(mode="json"),
        "top_quintile_median_xbi_relative_t20_pct": round(statistics.median(top_returns), 2),
        "bottom_quintile_median_xbi_relative_t20_pct": round(statistics.median(bottom_returns), 2),
        "limitations": [
            "Ground truth for calibration is the scientific/regulatory readout "
            "result (negative_event, inverted), not a market outcome - it "
            "measures whether the PoS number tracks catalyst success, not "
            "whether following it would have been profitable.",
            "This methodology has no adjustment layer, gates, valuation, or "
            "classification - it cannot be compared to BOE-1.0.0's own "
            "acceptance criteria (VALIDATION-AND-MILESTONES.md 5.2-5.3), which "
            "assume a full scored decision this project does not have.",
            "The author of this methodology had already seen this cohort's "
            "aggregate outcome rates (27 severe losses, 31 swing successes of "
            "120) before designing it. The prior table is BOE-1.0.0's own "
            "frozen, pre-existing values, not fitted to this cohort, but "
            "perfect blinding cannot be claimed.",
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
    print(
        json.dumps(
            {
                "event_count": status["event_count"],
                "brier_score": status["brier_score"],
                "base_prior_brier_score": status["base_prior_brier_score"],
                "brier_beats_naive_prior": status["brier_beats_naive_prior"],
            }
        )
    )


if __name__ == "__main__":
    main()
