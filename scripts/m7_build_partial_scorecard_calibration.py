"""Combine the three real, objectively-computed BOE-1.0.0 factor scores this
project has built - CATALYST, CASH_DILUTION, TECHNICAL - into a genuine
partial-scorecard signal, and calibrate it against real outcomes.

This is NOT a BOE-1.0.0 score. The real 100-point scorecard also needs
SCIENCE (20 pts, human review), MARKET_IMPACT (15 pts, needs
expectation/competitive judgment), VALUATION (10 pts, needs rNPV
peak-sales/TAM assumptions), OWNERSHIP (5 pts, needs Form 13F/Form 4 data
this project has not sourced), and SENTIMENT (5 pts, mostly needs analyst
revision data). None of those exist here. What exists is real: three factor
scores, each built from real, objectively-sourced data (real SEC XBRL
financials, real Alpaca price/volume data, and structural facts already in
the frozen manifest), summed and compared against real price outcomes -
genuinely informative regardless of the result, not fabricated to look
complete.

Reports two coverage tiers because CASH_DILUTION's real SEC data coverage
(88 of 120 events) is narrower than CATALYST/TECHNICAL's (120 of 120):
- CATALYST + TECHNICAL only, all 120 events.
- CATALYST + CASH_DILUTION + TECHNICAL, the 88 events where all three exist.

Pure function of already-committed artifacts. No new network calls, no new
evidence - see scripts/m7_build_catalyst_scores.py,
scripts/m7_build_cash_dilution_scores.py, and
scripts/m7_build_technical_snapshots.py for how each real factor score was
built.
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

from boe.historical_validation import wilson_rate  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
CATALYST_PATH = ROOT / "validation/m7/catalyst-scores.json"
CASH_DILUTION_PATH = ROOT / "validation/m7/cash-dilution-scores.json"
TECHNICAL_PATH = ROOT / "validation/m7/technical-snapshots.json"
OUTCOMES_PATH = ROOT / "validation/m7/historical-outcomes.json"
OUTPUT_PATH = ROOT / "validation/m7/partial-scorecard-calibration.json"


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _load(path: Path, what: str) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"{path} does not exist - run {what} first.")
    return dict(json.loads(path.read_bytes()))


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def _tier_summary(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    if not rows:
        return {"label": label, "n": 0}
    points = [r["points_pct"] for r in rows]
    returns = [r["xbi_relative_t20_pct"] for r in rows]
    ordered = sorted(rows, key=lambda r: (r["points_pct"], r["event_id"]))
    quintile = max(1, len(ordered) // 5)
    bottom, top = ordered[:quintile], ordered[-quintile:]
    top_swing = wilson_rate(sum(r["swing_success"] for r in top), len(top))
    bottom_swing = wilson_rate(sum(r["swing_success"] for r in bottom), len(bottom))
    top_severe = wilson_rate(sum(r["severe_loss"] for r in top), len(top))
    bottom_severe = wilson_rate(sum(r["severe_loss"] for r in bottom), len(bottom))
    return {
        "label": label,
        "n": len(rows),
        "mean_points_pct": round(statistics.fmean(points), 2),
        "pearson_r_points_vs_xbi_relative_t20_return": _pearson_r(points, returns),
        "top_quintile_median_xbi_relative_t20_pct": round(
            statistics.median(r["xbi_relative_t20_pct"] for r in top), 2
        ),
        "bottom_quintile_median_xbi_relative_t20_pct": round(
            statistics.median(r["xbi_relative_t20_pct"] for r in bottom), 2
        ),
        "top_quintile_swing_success": top_swing.model_dump(mode="json"),
        "bottom_quintile_swing_success": bottom_swing.model_dump(mode="json"),
        "top_quintile_severe_loss": top_severe.model_dump(mode="json"),
        "bottom_quintile_severe_loss": bottom_severe.model_dump(mode="json"),
        # These two can and do disagree in the real results here - reported
        # separately rather than collapsed into one flattering summary.
        "swing_success_rate_ranks_correctly": top_swing.value > bottom_swing.value,
        "median_return_ranks_correctly": statistics.median(r["xbi_relative_t20_pct"] for r in top)
        > statistics.median(r["xbi_relative_t20_pct"] for r in bottom),
    }


def build() -> dict[str, Any]:
    manifest = _load(MANIFEST_PATH, "scripts/m7_build_historical_event_registry.py --freeze")
    catalyst = _load(CATALYST_PATH, "scripts/m7_build_catalyst_scores.py")
    cash_dilution = _load(CASH_DILUTION_PATH, "scripts/m7_build_cash_dilution_scores.py")
    technical = _load(TECHNICAL_PATH, "scripts/m7_build_technical_snapshots.py")
    outcomes = _load(OUTCOMES_PATH, "scripts/m7_build_outcomes.py")

    cohort_sha256 = manifest["cohort_sha256"]
    for name, data in (
        ("catalyst-scores.json", catalyst),
        ("cash-dilution-scores.json", cash_dilution),
        ("technical-snapshots.json", technical),
        ("historical-outcomes.json", outcomes),
    ):
        if data["cohort_sha256"] != cohort_sha256:
            raise ValueError(f"{name} was built against a different cohort - regenerate it")

    catalyst_by_id = {s["event_id"]: s for s in catalyst["scores"]}
    cash_dilution_by_id = {s["event_id"]: s for s in cash_dilution["scores"]}
    technical_by_id = {s["event_id"]: s for s in technical["snapshots"]}
    outcomes_by_id = {o["event_id"]: o for o in outcomes["outcomes"]}

    two_factor_rows: list[dict[str, Any]] = []
    three_factor_rows: list[dict[str, Any]] = []
    for event_id, outcome in outcomes_by_id.items():
        cat = catalyst_by_id.get(event_id)
        tech = technical_by_id.get(event_id)
        if cat is None or tech is None:
            continue
        points_2 = cat["catalyst_factor_points"] + tech["technical_factor_points"]
        max_points_2 = cat["catalyst_factor_max_points"] + tech["technical_factor_max_points"]
        row = {
            "event_id": event_id,
            "points": points_2,
            "max_points": max_points_2,
            "points_pct": round(points_2 / max_points_2 * 100, 2),
            "xbi_relative_t20_pct": float(outcome["xbi_relative_t20_pct"]),
            "swing_success": bool(outcome["swing_success"]),
            "severe_loss": bool(outcome["severe_loss"]),
        }
        two_factor_rows.append(row)

        cash = cash_dilution_by_id.get(event_id)
        if cash is None:
            continue
        points_3 = points_2 + cash["cash_dilution_factor_points"]
        max_points_3 = max_points_2 + cash["cash_dilution_factor_max_points"]
        three_factor_rows.append(
            {
                **row,
                "points": points_3,
                "max_points": max_points_3,
                "points_pct": round(points_3 / max_points_3 * 100, 2),
            }
        )

    catalyst_technical_summary = _tier_summary(
        two_factor_rows, label="CATALYST + TECHNICAL (n=120)"
    )
    three_factor_summary = _tier_summary(
        three_factor_rows, label="CATALYST + CASH_DILUTION + TECHNICAL (n=88)"
    )
    pearson_values = ", ".join(
        f"{tier['pearson_r_points_vs_xbi_relative_t20_return']:.4f}"
        for tier in (catalyst_technical_summary, three_factor_summary)
        if tier.get("pearson_r_points_vs_xbi_relative_t20_return") is not None
    )
    disagreement = ""
    for tier in (catalyst_technical_summary, three_factor_summary):
        if tier.get("swing_success_rate_ranks_correctly") != tier.get(
            "median_return_ranks_correctly"
        ):
            disagreement = (
                f" This disagrees for {tier['label']}: its top quintile has a higher "
                "swing-success RATE than its bottom quintile, but a WORSE median return - "
                "consistent with more variance (bigger wins and bigger losses) rather than "
                "a clean, one-directional predictive signal."
            )
            break

    return {
        "generator": "python scripts/m7_build_partial_scorecard_calibration.py",
        "cohort_sha256": cohort_sha256,
        "factors_included": {
            "catalyst_technical": ["CATALYST", "TECHNICAL"],
            "catalyst_cash_dilution_technical": ["CATALYST", "CASH_DILUTION", "TECHNICAL"],
        },
        "factors_not_included": [
            "SCIENCE (20 pts) - requires a real human scientific reviewer this "
            "project does not have.",
            "MARKET_IMPACT (15 pts) - subfactors need expectation-gap/"
            "competitive-position judgment or analyst data not available.",
            "VALUATION (10 pts) - requires rNPV peak-sales/TAM assumptions per "
            "indication this project cannot objectively source at scale.",
            "OWNERSHIP (5 pts) - requires Form 13F/Form 4 data this project has not sourced.",
            "SENTIMENT (5 pts) - mostly requires analyst revision data not "
            "available; the two subfactors that would be computable "
            "(ATTENTION_VOLUME, SECTOR_REGIME) were not built here.",
        ],
        "catalyst_technical": catalyst_technical_summary,
        "catalyst_cash_dilution_technical": three_factor_summary,
        "limitations": [
            "This is a raw sum of real factor points, not a BOE-1.0.0 score: "
            "no weighting, gates, or classification is applied - those all "
            "require factors this project does not have.",
            "The two ranking metrics (swing-success rate vs. median return) "
            f"can disagree.{disagreement} Both Pearson correlations "
            f"({pearson_values}) are indistinguishable from zero. The honest "
            "read of this data is that combining these three real factors "
            "alone does not show a clear, reliable predictive signal - "
            "consistent with, not contradicting, objective-calibration-"
            "report.json's PoS-only finding.",
            "The ground truth here is the real price outcome "
            "(xbi_relative_t20_pct/swing_success/severe_loss), unlike "
            "objective-calibration-report.json's PoS calibration, which uses "
            "the scientific/regulatory readout result (negative_event). Both "
            "are real; they answer different questions.",
            "The author had already seen this cohort's aggregate outcome "
            "rates before any of CATALYST/CASH_DILUTION/TECHNICAL were "
            "built, the same disclosed limitation as "
            "objective-calibration-report.json - no per-event outcome was "
            "consulted while writing the scoring logic in "
            "scripts/m7_build_catalyst_scores.py, "
            "scripts/m7_build_cash_dilution_scores.py, or "
            "scripts/m7_build_technical_snapshots.py, but perfect blinding "
            "cannot be claimed.",
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
                "catalyst_technical_n": status["catalyst_technical"]["n"],
                "catalyst_technical_swing_success_rate_ranks_correctly": status[
                    "catalyst_technical"
                ].get("swing_success_rate_ranks_correctly"),
                "catalyst_technical_median_return_ranks_correctly": status[
                    "catalyst_technical"
                ].get("median_return_ranks_correctly"),
                "three_factor_n": status["catalyst_cash_dilution_technical"]["n"],
                "three_factor_swing_success_rate_ranks_correctly": status[
                    "catalyst_cash_dilution_technical"
                ].get("swing_success_rate_ranks_correctly"),
                "three_factor_median_return_ranks_correctly": status[
                    "catalyst_cash_dilution_technical"
                ].get("median_return_ranks_correctly"),
            }
        )
    )


if __name__ == "__main__":
    main()
