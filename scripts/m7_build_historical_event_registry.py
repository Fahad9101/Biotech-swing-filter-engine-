"""Build the real HistoricalEvent registry from the M7 evidence ledgers and run
the frozen select_frozen_cohort(seed=100100) selection against it.

This script is read-only with respect to src/boe/historical_validation.py - it
imports and calls the frozen functions but never modifies investment behavior.

By default it is a dry run: it reports whether the real registry, built
entirely from committed evidence, produces a valid 120-event frozen cohort,
without writing or persisting anything.

With --freeze, it performs the actual freeze: writes the validated
CohortManifest to validation/m7/cohort-manifest.json. This is a deliberate,
consequential, one-way action - run scripts/m7_build_authoritative_status.py
afterward to derive the real post-freeze status.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.historical_validation import (  # noqa: E402
    CohortManifest,
    HistoricalEvent,
    cohort_sha256,
    registry_sha256,
    select_frozen_cohort,
    validate_cohort,
)

RECONCILED = ROOT / "validation/m7/promotion/reconciled-candidate-status.json"

# Candidates with universe_status=PASS but no genuine minute-level first-public
# timestamp evidence (see first-public-availability-ledger-13.json). Excluded
# rather than assigned a fabricated time.
NO_USABLE_TIMESTAMP = {"P2-2023-MLTX-MIRA", "REG-2022-AMLX-RELYVRIO"}

CATALYST_FALLBACK_BY_PHASE = {
    "PHASE_2": "CLIN_P2",
    "PHASE_1": "CLIN_P1",
    "PHASE_3": "CLIN_P3",
}

CIK_URL_RE = re.compile(r"/data/(\d{1,10})/")

_json_cache: dict[str, dict] = {}


def _load(path: str) -> dict:
    if path not in _json_cache:
        _json_cache[path] = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return _json_cache[path]


def _find_event(acquisition_path: str, candidate_id: str) -> dict:
    data = _load(acquisition_path)
    items = data.get("events") or data.get("rows", [])
    for item in items:
        if item["candidate_id"] == candidate_id:
            return item
    raise ValueError(f"candidate {candidate_id} not found in {acquisition_path}")


def _resolve_cik(row: dict, event: dict) -> str:
    cik = event.get("cik")
    if not cik and row.get("universe_evidence_path"):
        uni = _load(row["universe_evidence_path"])
        urow = next(
            (x for x in uni.get("rows", []) if x["candidate_id"] == row["candidate_id"]), None
        )
        if urow:
            cik = urow.get("cik")
            if not cik:
                for url_field in ("sec_evidence_urls", "evidence_urls"):
                    for url in urow.get(url_field, []) or []:
                        match = CIK_URL_RE.search(url)
                        if match:
                            cik = match.group(1)
                            break
                    if cik:
                        break
    if not cik:
        url = event.get("source_url") or event.get("sec_event_url")
        if url:
            match = CIK_URL_RE.search(url)
            if match:
                cik = match.group(1)
    if not cik:
        raise ValueError(f"could not resolve CIK for {row['candidate_id']}")
    return str(int(cik)).zfill(10)


def build_eligible_events() -> list[HistoricalEvent]:
    reconciled = json.loads(RECONCILED.read_text(encoding="utf-8"))
    events: list[HistoricalEvent] = []
    for row in reconciled["rows"]:
        if row["universe_status"] != "PASS":
            continue
        if row["candidate_id"] in NO_USABLE_TIMESTAMP:
            continue
        acq_event = _find_event(row["acquisition_path"], row["candidate_id"])
        cik = _resolve_cik(row, acq_event)
        catalyst_type = acq_event.get("proposed_catalyst_type")
        if not catalyst_type:
            catalyst_type = CATALYST_FALLBACK_BY_PHASE[acq_event["clinical_phase"]]
        clinical_phase = acq_event.get("clinical_phase") or "UNSPECIFIED"
        company = acq_event.get("company") or acq_event.get("issuer")
        asset = acq_event["asset"]
        indication = acq_event.get("indication") or "not recorded in acquisition evidence"

        source_ids: list[str] = [row["acquisition_path"]]
        if row.get("universe_evidence_path"):
            source_ids.append(row["universe_evidence_path"])
        if row.get("financing_evidence_path"):
            source_ids.append(row["financing_evidence_path"])
        if row.get("single_asset_evidence_path"):
            source_ids.append(row["single_asset_evidence_path"])
        if row.get("timestamp_evidence_path"):
            source_ids.append(row["timestamp_evidence_path"])
        if row.get("normalization_path"):
            source_ids.append(row["normalization_path"])
        source_ids = list(dict.fromkeys(source_ids))  # dedupe, preserve order

        event = HistoricalEvent(
            event_id=row["candidate_id"],
            issuer_id=row["ticker"],
            ticker=row["ticker"],
            cik=cik,
            company=company,
            asset=asset,
            indication=indication,
            catalyst_type=catalyst_type,
            clinical_phase=clinical_phase,
            primary_stratum=row["stratum"],
            event_at=datetime.fromisoformat(row["first_public_timestamp"]),
            source_ids=tuple(source_ids),
            included=True,
            exclusion_reason=None,
            negative_event=bool(row["negative_label_recorded"]),
            financing_t_minus_90_to_t_plus_30=(row["financing_status"] == "QUALIFIES"),
            single_asset_issuer=(row["single_asset_status"] == "QUALIFIES"),
        )
        events.append(event)
    return events


MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Write the validated CohortManifest to validation/m7/cohort-manifest.json. "
        "A deliberate, one-way action; omit for a dry run.",
    )
    args = parser.parse_args()

    if MANIFEST_PATH.exists() and not args.freeze:
        raise SystemExit(
            f"{MANIFEST_PATH} already exists - the cohort is already frozen. "
            "Use scripts/m7_build_authoritative_status.py to report on it."
        )

    events = build_eligible_events()
    print(f"eligible registry size: {len(events)}")
    registry = tuple(events)
    cohort = select_frozen_cohort(registry)
    validate_cohort(cohort)
    print(f"selected cohort size: {len(cohort)}")
    from collections import Counter

    strata = Counter(e.primary_stratum.value for e in cohort)
    print("strata:", dict(strata))
    print("negative:", sum(e.negative_event for e in cohort))
    print("financing:", sum(e.financing_t_minus_90_to_t_plus_30 for e in cohort))
    print("single_asset:", sum(e.single_asset_issuer for e in cohort))
    issuer_counts = Counter(e.issuer_id for e in cohort)
    print("max issuer count:", max(issuer_counts.values()))
    reg_sha = registry_sha256(registry)
    coh_sha = cohort_sha256(cohort)
    print("registry_sha256:", reg_sha)
    print("cohort_sha256:", coh_sha)
    manifest = CohortManifest(
        frozen_at=datetime.now().astimezone(),
        events=cohort,
        registry_sha256=reg_sha,
        cohort_sha256=coh_sha,
    )
    print("CohortManifest constructed and self-validated successfully.")

    if not args.freeze:
        print("(dry run only - nothing was written or persisted)")
        return

    if MANIFEST_PATH.exists():
        raise SystemExit(f"{MANIFEST_PATH} already exists - refusing to overwrite a frozen cohort.")
    MANIFEST_PATH.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    print(f"FROZEN: wrote {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
