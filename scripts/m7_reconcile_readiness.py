"""Derive pre-freeze readiness from row evidence; never authorize cohort promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path("validation/m7/cohort-readiness.json")
ROWS_OUTPUT = Path("validation/m7/promotion/reconciled-candidate-status.json")


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def build(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    base = root / "validation/m7"
    hashes: dict[str, str] = {}

    def read(path: Path) -> Any:
        data = path.read_bytes()
        hashes[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    def ledgers(pattern: str) -> list[tuple[str, dict[str, Any]]]:
        result = []
        for path in sorted((base / "promotion").glob(pattern)):
            data = read(path)
            result.extend(
                (str(path.relative_to(root)), row)
                for row in data.get("rows", data.get("entries", []))
            )
        return result

    candidates: dict[str, dict[str, Any]] = {}
    for path in sorted((base / "acquisition").glob("*.json")):
        data = read(path)
        for row in data.get("events", []):
            key = row["candidate_id"]
            if key in candidates:
                raise ValueError(f"Duplicate acquisition ID: {key}")
            candidates[key] = {**row, "acquisition_path": str(path.relative_to(root))}
    replacement = base / "promotion/targeted-single-asset-replacement-03.json"
    for row in read(replacement)["rows"]:
        key = row["candidate_id"]
        if key in candidates:
            raise ValueError(f"Duplicate targeted acquisition ID: {key}")
        candidates[key] = {**row, "acquisition_path": str(replacement.relative_to(root))}

    aliases = {}
    for path, row in ledgers("event-normalization-ledger-*.json"):
        old, new = row["source_candidate_id"], row["canonical_candidate_id"]
        event = candidates.pop(old)
        candidates[new] = {
            **event,
            "candidate_id": new,
            "first_public_timestamp": row["canonical_first_public_timestamp"],
            "first_public_date": row["canonical_first_public_timestamp"][:10],
            "normalization_path": path,
            "original_candidate_id": old,
        }
        aliases[old] = new

    universe: dict[str, dict[str, Any]] = {}
    universe_paths = {}
    warnings = []
    for path, row in ledgers("historical-universe-ledger-*.json"):
        key = row["candidate_id"]
        if key not in candidates and row.get("original_candidate_id") in aliases:
            key = aliases[row["original_candidate_id"]]
            if row["first_public_timestamp"] != candidates[key]["first_public_timestamp"]:
                raise ValueError("Normalization cutoff mismatch")
        if key not in candidates:
            raise ValueError(f"Unmapped universe ID: {key}")
        if key in universe:
            raise ValueError(f"Conflicting/repeated universe determination requires review: {key}")
        universe[key] = row
        universe_paths[key] = path
        if "event_session_sensitivity_if_2025_05_06_regular_session_were_included" in row:
            warnings.append(
                {
                    "candidate_id": key,
                    "path": path,
                    "finding": "Existing pre-freeze ledger contains event-session "
                    "liquidity sensitivity after a pre-market disclosure. "
                    "Quarantine this sensitivity from selection and audit unblinding.",
                }
            )

    def overlay(pattern: str) -> dict[str, tuple[str, dict[str, Any]]]:
        result = {}
        for path, row in ledgers(pattern):
            key = aliases.get(row["candidate_id"], row["candidate_id"])
            if key not in candidates:
                raise ValueError(f"Unmapped evidence ID: {key}")
            result[key] = (path, row)
        return result

    science = overlay("single-asset-evidence-ledger-*.json")
    financing = overlay("financing-evidence-ledger-*.json")
    timestamps = overlay("first-public-availability-ledger-*.json")
    # Explicit clinical labels recorded in the prior integration are evidence;
    # its aggregate arithmetic is deliberately not an input to these totals.
    prior = read(base / "promotion/negative-reserve-integration-01.json")
    extra_negative = {r["candidate_id"]: r for r in prior["targeted_negative_rows_already_present"]}
    rows = []
    for key, event in sorted(candidates.items()):
        determination = universe.get(key, {}).get("historical_universe_eligible")
        status = {True: "PASS", False: "FAIL", None: "PENDING"}[determination]
        neg = event.get("negative_event_candidate") is True or key in extra_negative
        s_path, s = science.get(key, (None, {}))
        f_path, f = financing.get(key, (None, {}))
        t_path, t = timestamps.get(key, (None, {}))
        rows.append(
            {
                "candidate_id": key,
                "acquisition_path": event["acquisition_path"],
                "normalization_path": event.get("normalization_path"),
                "stratum": event["proposed_primary_stratum"],
                "ticker": event["ticker"],
                "first_public_timestamp": t.get(
                    "first_public_timestamp", event.get("first_public_timestamp")
                ),
                "timestamp_evidence_path": t_path,
                "negative_label_recorded": neg,
                "negative_label_path": (
                    "validation/m7/promotion/negative-reserve-integration-01.json"
                    if key in extra_negative
                    else event["acquisition_path"]
                ),
                "universe_status": status,
                "universe_evidence_path": universe_paths.get(key),
                "single_asset_status": s.get("determination", "PENDING"),
                "single_asset_evidence_path": s_path,
                "financing_status": f.get("status", "PENDING"),
                "financing_evidence_path": f_path,
                "eligible_registry_status": "NOT_PROMOTED",
            }
        )

    def counts(selected: list[dict[str, Any]]) -> dict[str, int]:
        c = Counter(r["universe_status"] for r in selected)
        return {
            "total": len(selected),
            "pass": c["PASS"],
            "fail": c["FAIL"],
            "pending": c["PENDING"],
            "not_yet_excluded": c["PASS"] + c["PENDING"],
        }

    negative = counts([r for r in rows if r["negative_label_recorded"]])
    single = counts([r for r in rows if r["single_asset_status"] == "QUALIFIES"])
    funds = counts(
        [
            r
            for r in rows
            if r["financing_status"] in {"QUALIFIES", "QUALIFIES_BY_CONTAINED_REPORTING_INTERVAL"}
        ]
    )
    # This utility is intentionally pre-freeze. A manifest requires the actual
    # frozen validator, never inferred completion from file existence.
    for name in ("eligible-registry.json", "cohort-manifest.json"):
        if list(base.rglob(name)):
            raise ValueError(f"{name} now exists: run authoritative frozen validation first")
    scorecard = root / "contracts/boe-scorecard.v1.0.0.json"
    raw = scorecard.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != "e9019ecb9975c21e62371c25dcd7d2b114de60e4":
        raise ValueError("Frozen scorecard changed")
    hashes[str(scorecard.relative_to(root))] = hashlib.sha256(raw).hexdigest()
    registry = {
        "role": "DERIVED_PREFREEZE_STATUS_NOT_ELIGIBLE_REGISTRY",
        "rules_version": "BOE-1.0.0",
        "rows": rows,
    }
    status = {
        "milestone": 7,
        "rules_version": "BOE-1.0.0",
        "m6_baseline_sha": "3060761a11f7bd85298f79efa8e262e5b8adedaf",
        "generator": "python scripts/m7_reconcile_readiness.py",
        "source_sha256": dict(sorted(hashes.items())),
        "reconciled_rows_sha256": hashlib.sha256(render(registry).encode()).hexdigest(),
        "required_minimum_events": 120,
        "authoritative_events_frozen": 0,
        "authoritative_cohort_manifest_present": False,
        "eligible_authoritative_registry_count": 0,
        "real_four_snapshot_reconstructions_complete": 0,
        "decision_locks_complete": 0,
        "real_outcomes_complete": 0,
        "holdout_2025_locked_events": 0,
        "candidate_counts": counts(rows),
        "negative_reserve": {
            **negative,
            "requirement": 40,
            "maximum_provisional_buffer": negative["not_yet_excluded"] - 40,
            "final_negative_quota_satisfied": False,
        },
        "single_asset_reserve": {**single, "requirement": 20},
        "financing_reserve": {**funds, "requirement": 20},
        "strata": {
            k: counts([r for r in rows if r["stratum"] == k])
            for k in sorted({r["stratum"] for r in rows})
        },
        "audit_findings": warnings,
        "blocking_findings": [
            "Universe PASS is not full eligibility; pending is not PASS.",
            "No eligible registry, frozen cohort, four-snapshot set or decision locks exist.",
            "Prior negative reserve of 43 omitted broad RAIN/MANTRA failure; "
            "only explicitly recorded negative labels count here.",
            "Timestamp, trial identity, conference earliest availability, point-in-time "
            "science/capital structure, concentration and review gates remain unresolved.",
            "Human confirmations and scientific reviews cannot be fabricated or backdated.",
            "Existing source-side unblinding findings require audit before any leakage PASS.",
        ],
        "merge_ready": False,
        "milestone_complete": False,
        "milestone_8_allowed": False,
        "required_action": "Complete outcome-blind evidence promotion and review; "
        "do not freeze, inspect returns or merge based on reserve counts.",
    }
    return status, registry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    status, registry = build()
    for path, data in ((OUTPUT, status), (ROWS_OUTPUT, registry)):
        target = ROOT / path
        expected = render(data)
        if args.check:
            if not target.exists() or target.read_text() != expected:
                raise SystemExit(f"Stale generated artifact: {path}")
        else:
            target.write_text(expected)
    print(json.dumps({k: status[k] for k in ("candidate_counts", "negative_reserve")}))


if __name__ == "__main__":
    main()
