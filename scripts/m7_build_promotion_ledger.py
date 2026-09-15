"""Build the Milestone 7 pre-freeze promotion ledger.

The ledger is intentionally outcome-blind. It consolidates acquisition artifacts,
flags potential cross-batch duplicates, and records unresolved promotion controls.
It does not promote any event to the frozen cohort by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_DIR = ROOT / "validation" / "m7" / "acquisition"
OUTPUT_DIR = ROOT / "validation" / "m7" / "promotion"
OUTPUT_PATH = OUTPUT_DIR / "candidate-promotion-ledger.json"

ACQUISITION_FILES = (
    "regulatory-primary-batch-01.json",
    "phase2-primary-batch-01.json",
    "phase3-primary-batch-01.json",
    "early-clinical-primary-batch-01.json",
    "conference-other-primary-batch-01.json",
    "negative-phase2-supplement-01.json",
)

FORBIDDEN_MARKET_OUTCOME_FIELDS = {
    "return_t1_pct",
    "return_t5_pct",
    "return_t20_pct",
    "xbi_relative_t1_pct",
    "xbi_relative_t5_pct",
    "xbi_relative_t20_pct",
    "mfe_t20_pct",
    "mae_t20_pct",
    "severe_loss",
    "swing_success",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ET = ZoneInfo("America/New_York")


def _canonical_sha256(payload: dict[str, Any]) -> str:
    unhashed = dict(payload)
    unhashed.pop("ledger_sha256", None)
    canonical = json.dumps(unhashed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _source_id(url: str) -> str:
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    return f"SRC-{digest}"


def _tokens(value: str | None) -> set[str]:
    return set(_TOKEN_RE.findall((value or "").lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _event_datetime(event: dict[str, Any]) -> datetime | None:
    timestamp = event.get("first_public_timestamp")
    if not timestamp:
        return None
    return datetime.fromisoformat(str(timestamp))


def _session_classification(event: dict[str, Any]) -> tuple[str, str | None]:
    event_at = _event_datetime(event)
    if event_at is None:
        return "UNRESOLVED_DATE_ONLY", None
    local = event_at.astimezone(_ET)
    if local.weekday() >= 5:
        return "WEEKEND", "America/New_York"
    minutes = local.hour * 60 + local.minute
    if minutes < 9 * 60 + 30:
        return "PRE_MARKET", "America/New_York"
    if minutes < 16 * 60:
        return "REGULAR_SESSION", "America/New_York"
    return "AFTER_HOURS", "America/New_York"


def _potential_duplicate(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if left["ticker"] != right["ticker"]:
        return False
    left_date = datetime.fromisoformat(left["first_public_date"]).date()
    right_date = datetime.fromisoformat(right["first_public_date"]).date()
    day_gap = abs((left_date - right_date).days)
    asset_similarity = _jaccard(_tokens(left.get("asset")), _tokens(right.get("asset")))
    indication_similarity = _jaccard(
        _tokens(left.get("indication")), _tokens(right.get("indication"))
    )
    if asset_similarity >= 0.67 and day_gap <= 45:
        return True
    return indication_similarity >= 0.75 and asset_similarity >= 0.35 and day_gap <= 14


def _duplicate_groups(events: list[dict[str, Any]]) -> dict[int, str | None]:
    parents = list(range(len(events)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    by_ticker: dict[str, list[int]] = defaultdict(list)
    for index, event in enumerate(events):
        by_ticker[str(event["ticker"])].append(index)
    for indices in by_ticker.values():
        for offset, left in enumerate(indices):
            for right in indices[offset + 1 :]:
                if _potential_duplicate(events[left], events[right]):
                    union(left, right)

    members: dict[int, list[int]] = defaultdict(list)
    for index in range(len(events)):
        members[find(index)].append(index)

    result: dict[int, str | None] = {}
    duplicate_number = 0
    for group in sorted(members.values(), key=lambda item: min(item)):
        if len(group) == 1:
            result[group[0]] = None
            continue
        duplicate_number += 1
        group_id = f"DUP-{duplicate_number:03d}"
        for index in group:
            result[index] = group_id
    return result


def _load_events() -> tuple[list[dict[str, Any]], dict[str, int]]:
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for filename in ACQUISITION_FILES:
        path = ACQUISITION_DIR / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        file_events = payload["events"]
        counts[filename] = len(file_events)
        for event in file_events:
            market_fields = FORBIDDEN_MARKET_OUTCOME_FIELDS & set(event)
            if market_fields:
                raise ValueError(
                    f"{filename}:{event['candidate_id']} contains forbidden market fields "
                    f"{sorted(market_fields)}"
                )
            copied = dict(event)
            copied["source_acquisition_file"] = f"validation/m7/acquisition/{filename}"
            events.append(copied)
    return events, counts


def build_ledger() -> dict[str, Any]:
    acquisition_events, source_counts = _load_events()
    duplicate_group_ids = _duplicate_groups(acquisition_events)
    rows: list[dict[str, Any]] = []
    duplicate_groups: dict[str, list[str]] = defaultdict(list)

    for index, event in enumerate(acquisition_events):
        source_url = str(event["source_url"])
        session_class, timezone = _session_classification(event)
        duplicate_group_id = duplicate_group_ids[index]
        if duplicate_group_id:
            duplicate_groups[duplicate_group_id].append(str(event["candidate_id"]))

        unresolved = list(dict.fromkeys(event.get("promotion_blockers", [])))
        for blocker in (
            "VERIFY_HISTORICAL_BOE_UNIVERSE_AT_EVENT",
            "RESOLVE_FINANCING_T_MINUS_90_TO_T_PLUS_30",
            "RESOLVE_SINGLE_ASSET_ISSUER_STATUS",
            "VERIFY_POINT_IN_TIME_SCIENCE_AND_CAPITAL_STRUCTURE",
        ):
            if blocker not in unresolved:
                unresolved.append(blocker)
        if duplicate_group_id and "RESOLVE_CROSS_STRATUM_DUPLICATE" not in unresolved:
            unresolved.append("RESOLVE_CROSS_STRATUM_DUPLICATE")

        row = {
            "candidate_id": event["candidate_id"],
            "source_acquisition_file": event["source_acquisition_file"],
            "company": event["company"],
            "historical_ticker": event["ticker"],
            "cik": event.get("cik"),
            "exchange": None,
            "historical_security_identity_status": (
                "PARTIALLY_RESOLVED_CIK_PRESENT" if event.get("cik") else "PENDING"
            ),
            "asset": event["asset"],
            "indication": event["indication"],
            "clinical_phase": event["clinical_phase"],
            "proposed_primary_stratum": event["proposed_primary_stratum"],
            "first_public_date": event["first_public_date"],
            "first_public_timestamp": event.get("first_public_timestamp"),
            "timestamp_precision": event.get("timestamp_precision"),
            "timezone": timezone,
            "market_session_classification": session_class,
            "authoritative_source_ids": [_source_id(source_url)],
            "source_urls": [source_url],
            "source_url_sha256": hashlib.sha256(source_url.encode()).hexdigest(),
            "historical_universe_eligible": None,
            "negative_event": bool(event.get("negative_event_candidate", False)),
            "negative_event_basis": event.get("result_direction"),
            "financing_t_minus_90_to_t_plus_30": None,
            "single_asset_issuer": None,
            "point_in_time_evidence_ready": None,
            "duplicate_group_id": duplicate_group_id,
            "cross_stratum_duplicate_result": (
                "PENDING_REVIEW" if duplicate_group_id else "NO_POTENTIAL_DUPLICATE_FOUND"
            ),
            "promotion_status": "PENDING",
            "exclusion_reason": None,
            "unresolved_blockers": unresolved,
            "verification_provenance": "DETERMINISTIC_NORMALIZATION_NO_MARKET_OUTCOMES",
        }
        rows.append(row)

    payload: dict[str, Any] = {
        "format_version": "1.0",
        "milestone": 7,
        "rules_version": "BOE-1.0.0",
        "role": "PREFREEZE_CANDIDATE_PROMOTION_LEDGER",
        "selection_seed": 100100,
        "source_acquisition_files": list(ACQUISITION_FILES),
        "source_candidate_counts": source_counts,
        "raw_candidate_count": len(rows),
        "promotion_counts": {
            "eligible": 0,
            "pending": len(rows),
            "excluded": 0,
        },
        "negative_candidate_count": sum(row["negative_event"] for row in rows),
        "potential_duplicate_group_count": len(duplicate_groups),
        "potential_duplicate_candidate_count": sum(
            len(candidate_ids) for candidate_ids in duplicate_groups.values()
        ),
        "potential_duplicate_groups": dict(sorted(duplicate_groups.items())),
        "market_outcome_fields_permitted": False,
        "cohort_frozen": False,
        "rows": rows,
    }
    payload["ledger_sha256"] = _canonical_sha256(payload)
    return payload


def main() -> None:
    payload = build_ledger()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ledger_sha256": payload["ledger_sha256"],
                "raw_candidate_count": payload["raw_candidate_count"],
                "negative_candidate_count": payload["negative_candidate_count"],
                "potential_duplicate_group_count": payload[
                    "potential_duplicate_group_count"
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
