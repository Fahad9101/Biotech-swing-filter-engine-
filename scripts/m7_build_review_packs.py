"""Milestone 7 Section 13: outcome-blind evidence review-pack generator.

For every pre-freeze candidate whose historical-universe determination is
PASS, builds a standalone, outcome-blind review pack connecting the real
sourced evidence in validation/m7/acquisition/*.json to the BOE-1.0.0
contract layer:

    CatalystObservation -> normalize_catalyst() -> CatalystVersion
                                                  -> ScientificEvidencePack (skeleton)

Packs contain no market outcome, return, or swing-success data of any kind -
only the point-in-time catalyst assertion, its primary-source citation(s),
and a scientific-evidence skeleton a reviewer fills in. The actual human
judgments (HistoricalCatalystConfirmation, ManualScienceReview) are never
fabricated here; each pack simply carries a NOT_YET_REVIEWED placeholder for
a real reviewer to complete later, outside this generator.

Also writes a deterministic manifest (per-pack and aggregate sha256, so any
hand-edit of a pack is detectable) and a worklist a human reviewer would
actually work through, in a fixed deterministic order.

Derived output only: never hand-patch a pack, the manifest, or the worklist.
Re-run this script and commit its output instead.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from boe.catalysts import CatalystObservation, normalize_catalyst
from boe.enums import CatalystType, EvidenceTier, TimingConfidence
from boe.scientific import build_scientific_evidence_pack

ROOT = Path(__file__).resolve().parents[1]
RECONCILED_STATUS = Path("validation/m7/promotion/reconciled-candidate-status.json")
ACQUISITION_DIR = Path("validation/m7/acquisition")
# Mirrors scripts/m7_reconcile_readiness.py: this promotion-directory file is
# treated as an additional acquisition source for a handful of targeted
# single-asset replacement candidates, alongside validation/m7/acquisition/*.json.
REPLACEMENT_ACQUISITION_PATH = Path(
    "validation/m7/promotion/targeted-single-asset-replacement-03.json"
)
OUTPUT_DIR = Path("validation/m7/review_packs")
MANIFEST_OUTPUT = ROOT / OUTPUT_DIR / "manifest.json"
WORKLIST_OUTPUT = ROOT / OUTPUT_DIR / "worklist.json"

# Fixed generation stamp for this derived-artifact batch, not the wall clock the
# script happens to run at - see docs precedent in every validation/m7/*.json
# ledger's own "generated_at" field. Chosen to postdate every 2018-2025
# historical event so ScientificEvidencePack.generated_at >= evidence_cutoff
# holds for the whole pool without per-event branching.
PACK_GENERATED_AT = datetime(2026, 9, 16, tzinfo=UTC)

EVIDENCE_NAMESPACE = UUID("1a064e6d-8377-457a-aba8-ebffee97a462")

STRATUM_ORDER = (
    "PHASE_2_POC",
    "PHASE_3_PIVOTAL",
    "REGULATORY",
    "EARLY_CLINICAL",
    "CONFERENCE_OTHER",
)

# source_type values observed across validation/m7/acquisition/*.json, mapped
# to the closest BOE-1.0.0 EvidenceTier. Deliberately conservative: any
# unrecognized source_type is an error, not a silent SECONDARY_CONTEXT
# downgrade, so a future sourcing batch introducing a new source_type is
# forced to classify it here rather than pack evidence at the wrong tier.
_SOURCE_TIER_BY_TYPE: dict[str, EvidenceTier] = {
    "FDA_OFFICIAL": EvidenceTier.FDA_REGULATOR,
    "SEC_8_K": EvidenceTier.SEC_FILING,
    "SEC_EXHIBIT_99_1": EvidenceTier.SEC_FILING,
    "ISSUER_SEC_8K": EvidenceTier.SEC_FILING,
    "ISSUER_SEC_8K_EXHIBIT_991": EvidenceTier.SEC_FILING,
    "ISSUER_SEC_OR_CONTEMPORANEOUS_PRESS_RELEASE": EvidenceTier.SEC_FILING,
    "ISSUER_GLOBENEWSWIRE_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_DISCLOSURE_WITH_BUSINESS_WIRE_DISTRIBUTION": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_IR_BUSINESS_WIRE_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_IR_PRESS_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_OR_CONTEMPORANEOUS_CONFERENCE_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_OR_CONTEMPORANEOUS_PRESS_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "ISSUER_PRESS_RELEASE": EvidenceTier.ISSUER_RELATIONS,
    "PRESS_DISTRIBUTOR_ISSUER_RELEASE": EvidenceTier.ISSUER_RELATIONS,
}


class ReviewPackSourcingError(ValueError):
    """Raised when a PASS candidate's acquisition row cannot be packed safely."""


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _acquisition_events_by_id(root: Path) -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for path in sorted((root / ACQUISITION_DIR).glob("*.json")):
        data = _load_json(path)
        for event in data.get("events", []):
            events[event["candidate_id"]] = {
                **event,
                "acquisition_path": path.relative_to(root).as_posix(),
            }
    replacement_path = root / REPLACEMENT_ACQUISITION_PATH
    replacement = _load_json(replacement_path)
    for row in replacement.get("rows", []):
        # This file's schema was built for financing/single-asset promotion
        # checks, not review packs: it carries no `indication` and no explicit
        # `proposed_catalyst_type`. Index it anyway (rather than leaving these
        # candidates a misleading "not found anywhere") so downstream code can
        # raise a precise, field-named ReviewPackSourcingError instead of
        # guessing at values this file never actually asserts.
        events[row["candidate_id"]] = {
            "candidate_id": row["candidate_id"],
            "company": row.get("issuer"),
            "ticker": row["ticker"],
            "cik": row.get("cik"),
            "asset": row.get("asset"),
            "clinical_phase": row.get("clinical_phase"),
            "first_public_date": row["event_date"],
            "first_public_timestamp": row.get("first_public_timestamp"),
            "timestamp_precision": "EXACT_TO_MINUTE",
            "source_url": row.get("source_url"),
            "source_type": "ISSUER_GLOBENEWSWIRE_RELEASE",
            "source_role": "TARGETED_SINGLE_ASSET_REPLACEMENT_CANDIDATE",
            "negative_event_candidate": False,
            "promotion_blockers": (),
            "acquisition_path": REPLACEMENT_ACQUISITION_PATH.as_posix(),
        }
    return events


def _issuer_id(root: Path, row: dict[str, Any], event: dict[str, Any]) -> str:
    universe = _load_json(root / row["universe_evidence_path"])
    universe_row = next(
        item for item in universe["rows"] if item["candidate_id"] == row["candidate_id"]
    )
    cik = universe_row.get("cik") or event.get("cik")
    if cik:
        return str(cik).strip().zfill(10)
    return f"TICKER:{row['ticker']}"


def _source_citations(event: dict[str, Any]) -> tuple[str, ...]:
    if event.get("source_url"):
        return (event["source_url"],)
    if event.get("source_urls"):
        return tuple(event["source_urls"])
    raise ReviewPackSourcingError(f"{event['candidate_id']} has no source_url(s)")


def _source_tier(event: dict[str, Any]) -> EvidenceTier:
    source_type = event.get("source_type")
    if source_type in _SOURCE_TIER_BY_TYPE:
        return _SOURCE_TIER_BY_TYPE[source_type]
    raise ReviewPackSourcingError(
        f"{event['candidate_id']} has unmapped source_type {source_type!r}"
    )


def _timing_confidence(event: dict[str, Any]) -> TimingConfidence:
    precision = event.get("timestamp_precision") or ""
    if precision.startswith("EXACT_TO_MINUTE"):
        return TimingConfidence.HIGH
    if precision == "DATE_ONLY":
        return TimingConfidence.MODERATE
    return TimingConfidence.UNVERIFIED


def _source_statement(event: dict[str, Any]) -> str:
    if event.get("notes"):
        return str(event["notes"])
    role = event.get("source_role", "primary source")
    return f"{event.get('company', event['ticker'])} - {role} dated {event['first_public_date']}."


def _require_fields(event: dict[str, Any], *fields: str) -> None:
    missing = [field for field in fields if not event.get(field)]
    if missing:
        raise ReviewPackSourcingError(
            f"{event['candidate_id']} is missing required field(s) {missing} in "
            f"{event['acquisition_path']}; cannot build a review pack without "
            "fabricating evidence the source does not assert"
        )


def build_catalyst_observation(
    root: Path, row: dict[str, Any], event: dict[str, Any]
) -> CatalystObservation:
    _require_fields(event, "indication", "proposed_catalyst_type", "asset", "clinical_phase")
    known_at = datetime.fromisoformat(row["first_public_timestamp"])
    citations = _source_citations(event)
    evidence_id = uuid5(EVIDENCE_NAMESPACE, f"{row['candidate_id']}|{citations[0]}")
    window = date.fromisoformat(event["first_public_date"])
    return CatalystObservation(
        issuer_id=_issuer_id(root, row, event),
        asset=event["asset"],
        indication=event["indication"],
        catalyst_type=CatalystType(event["proposed_catalyst_type"]),
        clinical_phase=event["clinical_phase"],
        title=f"{event.get('company', row['ticker'])} - {event['asset']} ({event['indication']})",
        window_start=window,
        window_end=window,
        timing_confidence=_timing_confidence(event),
        evidence_id=evidence_id,
        source_tier=_source_tier(event),
        known_at=known_at,
        source_statement=_source_statement(event),
        external_event_id=row["candidate_id"],
    )


def build_pack(root: Path, row: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    observation = build_catalyst_observation(root, row, event)
    version = normalize_catalyst((observation,), cutoff=observation.known_at)
    pack = build_scientific_evidence_pack(
        catalyst_version_id=version.id,
        asset=observation.asset,
        indication=observation.indication,
        clinical_phase=observation.clinical_phase,
        trial_ids=(),
        study_design="NOT_YET_REVIEWED",
        enrollment=None,
        randomized=None,
        blinded=None,
        comparator=None,
        primary_endpoints=(),
        secondary_endpoints=(),
        primary_completion_date=None,
        study_status=None,
        safety_signals=(),
        regulatory_context=(),
        evidence_ids=version.supporting_evidence_ids,
        evidence_cutoff=version.resolved_at_cutoff,
        generated_at=PACK_GENERATED_AT,
    )
    body = {
        "format_version": "1.0",
        "milestone": 7,
        "role": "OUTCOME_BLIND_HUMAN_REVIEW_PACK",
        "rules_version": "BOE-1.0.0",
        "candidate_id": row["candidate_id"],
        "ticker": row["ticker"],
        "company": event.get("company"),
        "stratum": row["stratum"],
        "negative_event_candidate": bool(event.get("negative_event_candidate", False)),
        "outcome_inspected_for_selection": False,
        "market_outcomes_inspected": False,
        "acquisition_path": event["acquisition_path"],
        "universe_evidence_path": row["universe_evidence_path"],
        "promotion_blockers": tuple(event.get("promotion_blockers", ())),
        "source_citations": _source_citations(event),
        "catalyst_observation": observation.model_dump(mode="json"),
        "catalyst_version": version.model_dump(mode="json"),
        "scientific_evidence_pack": pack.model_dump(mode="json"),
        "review": {
            "historical_catalyst_confirmation_status": "NOT_YET_REVIEWED",
            "manual_science_review_status": "NOT_YET_REVIEWED",
            "reviewer": None,
            "reviewed_at": None,
            "note": (
                "A HistoricalCatalystConfirmation must bind evidence_cutoff exactly to "
                f"{version.resolved_at_cutoff.isoformat()} (this pack's catalyst_version."
                "resolved_at_cutoff) and review all of catalyst_version.supporting_"
                "evidence_ids; outcome_data_shown must be false. Do not fabricate, "
                "backdate, or synthesize either record - only a genuine human review "
                "performed against this pack's evidence may populate them."
            ),
        },
    }
    body["pack_sha256"] = _canonical_hash(body)
    return body


def build(
    root: Path = ROOT,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    status = _load_json(root / RECONCILED_STATUS)
    events = _acquisition_events_by_id(root)
    pass_rows = [row for row in status["rows"] if row["universe_status"] == "PASS"]
    pass_rows.sort(key=lambda row: row["candidate_id"])

    packs: list[dict[str, Any]] = []
    deferred: list[dict[str, str]] = []
    for row in pass_rows:
        event = events.get(row["candidate_id"])
        if event is None:
            deferred.append(
                {
                    "candidate_id": row["candidate_id"],
                    "reason": "PASS but not found in any acquisition batch under its current "
                    "candidate_id (needs alias-lookup support for a normalized event; none "
                    "currently exist among PASS rows)",
                }
            )
            continue
        if not row.get("first_public_timestamp"):
            deferred.append(
                {
                    "candidate_id": row["candidate_id"],
                    "reason": "universe eligibility used a conservative cutoff assumption but "
                    "the exact first-public-disclosure timestamp is not yet resolved "
                    "(RESOLVE_EXACT_FIRST_PUBLIC_TIMESTAMP still open) - packing a review pack "
                    "on an unresolved point-in-time anchor would risk fabricating precision "
                    "that does not exist yet",
                }
            )
            continue
        try:
            packs.append(build_pack(root, row, event))
        except ReviewPackSourcingError as exc:
            deferred.append({"candidate_id": row["candidate_id"], "reason": str(exc)})
    deferred.sort(key=lambda item: item["candidate_id"])

    manifest = {
        "format_version": "1.0",
        "milestone": 7,
        "role": "OUTCOME_BLIND_REVIEW_PACK_MANIFEST",
        "rules_version": "BOE-1.0.0",
        "generated_at": PACK_GENERATED_AT.isoformat(),
        "market_outcomes_inspected": False,
        "pack_count": len(packs),
        "deferred_count": len(deferred),
        "deferred": deferred,
        "packs": sorted(
            (
                {
                    "candidate_id": pack["candidate_id"],
                    "ticker": pack["ticker"],
                    "stratum": pack["stratum"],
                    "pack_path": f"validation/m7/review_packs/{pack['candidate_id']}.json",
                    "pack_sha256": pack["pack_sha256"],
                }
                for pack in packs
            ),
            key=lambda item: item["candidate_id"],
        ),
    }
    manifest["manifest_sha256"] = _canonical_hash(manifest["packs"])

    by_stratum: dict[str, list[dict[str, Any]]] = {stratum: [] for stratum in STRATUM_ORDER}
    for pack in packs:
        by_stratum[pack["stratum"]].append(pack)
    for rows in by_stratum.values():
        rows.sort(
            key=lambda pack: (
                pack["catalyst_observation"]["known_at"],
                pack["candidate_id"],
            )
        )
    worklist_entries = [
        {
            "sequence": index,
            "candidate_id": pack["candidate_id"],
            "ticker": pack["ticker"],
            "company": pack["company"],
            "stratum": pack["stratum"],
            "negative_event_candidate": pack["negative_event_candidate"],
            "event_date": pack["catalyst_observation"]["window_start"],
            "catalyst_type": pack["catalyst_observation"]["catalyst_type"],
            "source_citations": pack["source_citations"],
            "pack_path": f"validation/m7/review_packs/{pack['candidate_id']}.json",
            "historical_catalyst_confirmation_status": "NOT_YET_REVIEWED",
            "manual_science_review_status": "NOT_YET_REVIEWED",
        }
        for index, pack in enumerate(
            (pack for stratum in STRATUM_ORDER for pack in by_stratum[stratum]),
            start=1,
        )
    ]
    worklist = {
        "format_version": "1.0",
        "milestone": 7,
        "role": "OUTCOME_BLIND_HUMAN_REVIEW_WORKLIST",
        "rules_version": "BOE-1.0.0",
        "generated_at": PACK_GENERATED_AT.isoformat(),
        "market_outcomes_inspected": False,
        "sequencing_rule": (
            "Stratum round-robin order PHASE_2_POC, PHASE_3_PIVOTAL, REGULATORY, "
            "EARLY_CLINICAL, CONFERENCE_OTHER; within a stratum, ascending event date "
            "then candidate_id. Fixed and deterministic - reviewers work top to bottom, "
            "they do not self-select easy candidates."
        ),
        "entry_count": len(worklist_entries),
        "entries": worklist_entries,
    }
    return packs, manifest, worklist, deferred


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    packs, manifest, worklist, deferred = build()
    output_dir = ROOT / OUTPUT_DIR

    targets: list[tuple[Path, Any]] = [
        (MANIFEST_OUTPUT, manifest),
        (WORKLIST_OUTPUT, worklist),
    ]
    for pack in packs:
        targets.append((output_dir / f"{pack['candidate_id']}.json", pack))

    if args.check:
        keep = {path for path, _ in targets}
        existing_paths = set(output_dir.glob("*.json"))
        stray = existing_paths - keep
        if stray:
            raise SystemExit(f"Stray review-pack file(s) no longer derived: {sorted(stray)}")
        for path, data in targets:
            expected = render(data)
            if not path.exists() or path.read_text() != expected:
                raise SystemExit(f"Stale generated artifact: {path.relative_to(ROOT)}")
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        current_files = set(output_dir.glob("*.json"))
        keep = {path for path, _ in targets}
        for stray in current_files - keep:
            stray.unlink()
        for path, data in targets:
            path.write_text(render(data))

    print(json.dumps({"pack_count": len(packs), "deferred_count": len(deferred)}))


if __name__ == "__main__":
    main()
