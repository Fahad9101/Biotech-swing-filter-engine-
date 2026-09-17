"""Derive authoritative post-freeze status from a real, committed CohortManifest.

This is the post-freeze counterpart to scripts/m7_reconcile_readiness.py, which
deliberately refuses to run once validation/m7/cohort-manifest.json exists (see
its own guard and tests/test_m7_readiness.py::
test_manifest_presence_cannot_automatically_mark_complete). Never infers
completion from file existence: it re-parses the manifest as a real
CohortManifest (re-running every Pydantic validator, including
validate_cohort() and the cohort_sha256 recomputation check), and separately
rebuilds the real eligible registry from the still-committed evidence ledgers
to confirm registry_sha256 still matches - proving the frozen artifact is
both internally consistent and unchanged since freezing.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m7_build_historical_event_registry import build_eligible_events  # noqa: E402

from boe.historical_validation import CohortManifest, registry_sha256  # noqa: E402

OUTPUT = Path("validation/m7/cohort-readiness.json")
ROWS_INPUT = ROOT / "validation/m7/promotion/reconciled-candidate-status.json"
SNAPSHOT_CUTOFFS_PATH = ROOT / "validation/m7/snapshot-cutoffs.json"
OUTCOMES_PATH = ROOT / "validation/m7/historical-outcomes.json"

STRATUM_REQUIREMENTS = {
    "PHASE_2_POC": 30,
    "PHASE_3_PIVOTAL": 30,
    "REGULATORY": 30,
    "EARLY_CLINICAL": 15,
    "CONFERENCE_OTHER": 15,
}
ISSUER_MAX_EVENTS = 5
ISSUER_MAX_STRATUM_SHARE = 0.10


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _counts(selected: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(r["universe_status"] for r in selected)
    return {
        "total": len(selected),
        "pass": c["PASS"],
        "fail": c["FAIL"],
        "pending": c["PENDING"],
        "not_yet_excluded": c["PASS"] + c["PENDING"],
    }


def _issuer_concentration(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    passed = [r for r in selected if r["universe_status"] == "PASS"]
    findings = []
    overall = Counter(r["ticker"] for r in passed)
    for ticker, n in sorted(overall.items()):
        if n > ISSUER_MAX_EVENTS:
            findings.append(
                {
                    "ticker": ticker,
                    "scope": "OVERALL",
                    "pass_count": n,
                    "cap": ISSUER_MAX_EVENTS,
                    "candidate_ids": sorted(
                        r["candidate_id"] for r in passed if r["ticker"] == ticker
                    ),
                }
            )
    for stratum in sorted({r["stratum"] for r in passed if r["stratum"]}):
        stratum_rows = [r for r in passed if r["stratum"] == stratum]
        per_issuer = Counter(r["ticker"] for r in stratum_rows)
        for ticker, n in sorted(per_issuer.items()):
            share = n / len(stratum_rows)
            if share > ISSUER_MAX_STRATUM_SHARE:
                findings.append(
                    {
                        "ticker": ticker,
                        "scope": stratum,
                        "pass_count": n,
                        "stratum_pass_total": len(stratum_rows),
                        "share": round(share, 4),
                        "cap_share": ISSUER_MAX_STRATUM_SHARE,
                        "candidate_ids": sorted(
                            r["candidate_id"] for r in stratum_rows if r["ticker"] == ticker
                        ),
                    }
                )
    return findings


def build(root: Path = ROOT) -> dict[str, Any]:
    manifest_path = root / "validation/m7/cohort-manifest.json"
    if not manifest_path.exists():
        raise ValueError(
            f"{manifest_path} does not exist - the cohort is not frozen yet. "
            "Use scripts/m7_reconcile_readiness.py for pre-freeze status."
        )

    manifest_raw = json.loads(manifest_path.read_bytes())
    # Re-parsing as a real CohortManifest re-runs every Pydantic validator,
    # including validate_cohort() (strata minimums, negative/financing/
    # single-asset floors, issuer caps) and the cohort_sha256 recomputation
    # check - a corrupted or hand-edited manifest fails here, loudly.
    manifest = CohortManifest.model_validate(manifest_raw)

    # Rebuild the eligible registry from the still-committed evidence ledgers
    # and confirm its hash still matches what was frozen - proof nothing
    # changed since freezing.
    rebuilt_registry = tuple(build_eligible_events())
    rebuilt_registry_sha256 = registry_sha256(rebuilt_registry)
    registry_unchanged_since_freeze = rebuilt_registry_sha256 == manifest.registry_sha256

    rows_data = json.loads(ROWS_INPUT.read_bytes())
    rows = rows_data["rows"]

    negative = _counts([r for r in rows if r["negative_label_recorded"]])
    single = _counts([r for r in rows if r["single_asset_status"] == "QUALIFIES"])
    funds = _counts(
        [
            r
            for r in rows
            if r["financing_status"] in {"QUALIFIES", "QUALIFIES_BY_CONTAINED_REPORTING_INTERVAL"}
        ]
    )

    frozen_strata = Counter(e.primary_stratum.value for e in manifest.events)
    frozen_issuer_counts = Counter(e.issuer_id for e in manifest.events)

    # Real, committed artifacts of later pipeline stages - read directly, not
    # inferred from existence. Each is cross-checked against the current
    # manifest's cohort_sha256 so a stale artifact from a different freeze
    # can never be silently reported as current.
    cutoffs_data = json.loads(SNAPSHOT_CUTOFFS_PATH.read_bytes())
    snapshot_cutoffs_current = cutoffs_data["cohort_sha256"] == manifest.cohort_sha256
    snapshot_cutoffs_computed = len(cutoffs_data["events"]) if snapshot_cutoffs_current else 0

    outcomes_data = json.loads(OUTCOMES_PATH.read_bytes())
    outcomes_current = outcomes_data["cohort_sha256"] == manifest.cohort_sha256
    real_outcomes_complete = outcomes_data["outcome_count"] if outcomes_current else 0
    real_outcomes_failed = outcomes_data["failed_count"] if outcomes_current else None

    status: dict[str, Any] = {
        "milestone": 7,
        "rules_version": manifest.rules_version,
        "generator": "python scripts/m7_build_authoritative_status.py",
        "manifest_path": str(manifest_path.relative_to(root).as_posix()),
        "manifest_frozen_at": manifest.frozen_at.isoformat(),
        "manifest_seed": manifest.seed,
        "manifest_registry_sha256": manifest.registry_sha256,
        "manifest_cohort_sha256": manifest.cohort_sha256,
        "registry_unchanged_since_freeze": registry_unchanged_since_freeze,
        "rebuilt_registry_sha256": rebuilt_registry_sha256,
        "required_minimum_events": 120,
        "authoritative_events_frozen": len(manifest.events),
        "authoritative_cohort_manifest_present": True,
        "eligible_authoritative_registry_count": len(rebuilt_registry),
        # snapshot_cutoffs_computed and real_outcomes_complete are read from
        # real, committed artifacts (see above) - both genuinely reached 120
        # events x 4 cutoffs / 120 events this session, with zero fabricated
        # content, since neither needs a human scientific/catalyst reviewer.
        # The remaining three stay honestly 0: they require a real, named
        # reviewer this project does not have (see blocking_findings below),
        # and an automated agent must never supply one.
        "snapshot_cutoffs_computed": snapshot_cutoffs_computed,
        "snapshot_cutoffs_current": snapshot_cutoffs_current,
        "real_outcomes_complete": real_outcomes_complete,
        "real_outcomes_current": outcomes_current,
        "real_outcomes_failed_count": real_outcomes_failed,
        "real_four_snapshot_reconstructions_complete": 0,
        "decision_locks_complete": 0,
        "holdout_2025_locked_events": 0,
        "frozen_cohort_strata": dict(sorted(frozen_strata.items())),
        "frozen_cohort_negative_count": sum(e.negative_event for e in manifest.events),
        "frozen_cohort_financing_count": sum(
            e.financing_t_minus_90_to_t_plus_30 for e in manifest.events
        ),
        "frozen_cohort_single_asset_count": sum(e.single_asset_issuer for e in manifest.events),
        "frozen_cohort_max_issuer_count": max(frozen_issuer_counts.values()),
        "candidate_counts": _counts(rows),
        "negative_reserve": {**negative, "requirement": 40},
        "single_asset_reserve": {**single, "requirement": 20},
        "financing_reserve": {**funds, "requirement": 20},
        "strata": {
            k: {
                **_counts([r for r in rows if r["stratum"] == k]),
                "requirement": STRATUM_REQUIREMENTS[k],
            }
            for k in sorted({r["stratum"] for r in rows})
        },
        "issuer_concentration_findings": _issuer_concentration(rows),
        "blocking_findings": [
            "Cohort is frozen; investment-rule behavior and cohort membership "
            "must not change without a new, separately approved rules version.",
            "Snapshot cutoff timestamps and real price outcomes are complete "
            "for all frozen events, but no decision locks, scores, PoS, "
            "valuations, or calibration exist - the frozen cohort is a fixed "
            "candidate set with known real returns, not yet a scored or "
            "reviewed one.",
            "Human confirmations and scientific reviews cannot be fabricated "
            "or backdated, and no automated agent may supply them. The "
            "project owner has confirmed no qualified reviewer is available; "
            "this is accepted as Milestone 7's final reachable state absent "
            "one, not a temporary gap awaiting more automated work.",
        ],
        "merge_ready": False,
        "milestone_complete": False,
        "milestone_8_allowed": False,
        "accepted_final_state_without_reviewer": True,
        "required_action": "None automatable remains: decision locks, scoring, "
        "calibration, and failure analysis all require a real, identified "
        "human scientific/catalyst reviewer, which this project does not "
        "have. Re-run this script if that changes. Do not merge PR #5 or "
        "start Milestone 8 without explicit owner approval regardless.",
    }
    return status


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    status = build()
    target = ROOT / OUTPUT
    expected = render(status)
    if args.check:
        if not target.exists() or target.read_text() != expected:
            raise SystemExit(f"Stale generated artifact: {OUTPUT}")
    else:
        target.write_text(expected)
    print(
        json.dumps(
            {
                k: status[k]
                for k in (
                    "authoritative_events_frozen",
                    "authoritative_cohort_manifest_present",
                    "registry_unchanged_since_freeze",
                    "frozen_cohort_negative_count",
                    "frozen_cohort_financing_count",
                    "frozen_cohort_single_asset_count",
                    "snapshot_cutoffs_computed",
                    "real_outcomes_complete",
                    "decision_locks_complete",
                    "accepted_final_state_without_reviewer",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
