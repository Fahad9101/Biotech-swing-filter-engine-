"""Acquire Milestone 7 regulatory-event candidates from official openFDA data.

The output is discovery-only. It does not freeze the M7 cohort or assert that an
FDA submission status date is the first material public timestamp. Every candidate
must still pass historical issuer, universe, timestamp, and outcome-blinding checks.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

OPENFDA = "https://api.fda.gov/drug/drugsfda.json"
START = date(2018, 1, 1)
END = date(2025, 12, 31)
LIMIT = 99
MAX_SKIP = 25000
REQUEST_DELAY_SECONDS = 0.25


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_product(result: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    products = result.get("products")
    if not isinstance(products, list) or not products:
        return None, ()
    first = products[0] if isinstance(products[0], dict) else {}
    brand = _text(first.get("brand_name"))
    ingredients_raw = first.get("active_ingredients")
    ingredients: list[str] = []
    if isinstance(ingredients_raw, list):
        for item in ingredients_raw:
            if isinstance(item, dict):
                name = _text(item.get("name"))
                if name:
                    ingredients.append(name)
    return brand, tuple(dict.fromkeys(ingredients))


def _candidate_id(application: str, submission: str, status_date: date) -> str:
    raw = f"{application}|{submission}|{status_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _fetch_page(client: httpx.Client, skip: int) -> dict[str, Any]:
    search = (
        f"submissions.submission_status_date:[{START.strftime('%Y%m%d')}+TO+"
        f"{END.strftime('%Y%m%d')}]"
    )
    params = {"search": search, "limit": LIMIT, "skip": skip}
    response = client.get(OPENFDA, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("openFDA response must be an object")
    return payload


def _extract_candidates(results: list[object]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw_result in results:
        if not isinstance(raw_result, dict):
            continue
        application = _text(raw_result.get("application_number"))
        if not application:
            continue
        sponsor = _text(raw_result.get("sponsor_name"))
        product, ingredients = _first_product(raw_result)
        submissions = raw_result.get("submissions")
        if not isinstance(submissions, list):
            continue
        for raw_submission in submissions:
            if not isinstance(raw_submission, dict):
                continue
            status_date = _parse_date(raw_submission.get("submission_status_date"))
            if status_date is None or not (START <= status_date <= END):
                continue
            submission_number = _text(raw_submission.get("submission_number")) or "UNKNOWN"
            submission_type = _text(raw_submission.get("submission_type"))
            submission_status = _text(raw_submission.get("submission_status"))
            review_priority = _text(raw_submission.get("review_priority"))
            query_search = f'application_number:"{application}"'
            query_url = f"{OPENFDA}?{urlencode({'search': query_search, 'limit': 1})}"
            candidates.append(
                {
                    "candidate_id": _candidate_id(application, submission_number, status_date),
                    "application_number": application,
                    "sponsor_name": sponsor,
                    "product_name": product,
                    "active_ingredients": ingredients,
                    "action_date": status_date.isoformat(),
                    "submission_number": submission_number,
                    "submission_type": submission_type,
                    "submission_status": submission_status,
                    "review_priority": review_priority,
                    "official_discovery_source": "openFDA Drugs@FDA",
                    "official_discovery_url": query_url,
                    "provenance_status": "FDA_PRIMARY_DERIVED_CANDIDATE_NOT_YET_COHORT_VERIFIED",
                    "required_next_verification": [
                        "VERIFY_MATERIAL_REGULATORY_EVENT_TYPE",
                        "VERIFY_FIRST_PUBLIC_FDA_OR_ISSUER_TIMESTAMP",
                        "RESOLVE_HISTORICAL_PUBLIC_ISSUER_AND_TICKER",
                        "VERIFY_BOE_UNIVERSE_AT_EVENT",
                        "VERIFY_POINT_IN_TIME_CAPITAL_STRUCTURE",
                        "VERIFY_MARKET_DATA_PROVENANCE",
                    ],
                }
            )
    return candidates


def main() -> None:
    headers = {
        "User-Agent": (
            "BOE-M7 historical-validation research "
            "https://github.com/Fahad9101/Biotech-swing-filter-engine-"
        )
    }
    candidates: list[dict[str, Any]] = []
    total_records: int | None = None
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        skip = 0
        while skip <= MAX_SKIP:
            payload = _fetch_page(client, skip)
            meta = payload.get("meta")
            if total_records is None and isinstance(meta, dict):
                results_meta = meta.get("results")
                if isinstance(results_meta, dict) and isinstance(results_meta.get("total"), int):
                    total_records = results_meta["total"]
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                break
            candidates.extend(_extract_candidates(results))
            print(
                f"openFDA page skip={skip}: {len(results)} applications; "
                f"{len(candidates)} action-date candidates",
                flush=True,
            )
            skip += len(results)
            if total_records is not None and skip >= total_records:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

    deduped = {item["candidate_id"]: item for item in candidates}
    ordered = sorted(
        deduped.values(),
        key=lambda item: (
            str(item["action_date"]),
            str(item["sponsor_name"] or ""),
            str(item["application_number"]),
            str(item["submission_number"]),
        ),
    )
    year_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    sponsors: set[str] = set()
    for item in ordered:
        year = str(item["action_date"])[:4]
        year_counts[year] = year_counts.get(year, 0) + 1
        status = str(item["submission_status"] or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
        submission_type = str(item["submission_type"] or "UNKNOWN")
        type_counts[submission_type] = type_counts.get(submission_type, 0) + 1
        if item["sponsor_name"]:
            sponsors.add(str(item["sponsor_name"]))

    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "format_version": "1.0",
        "role": "REGULATORY_DISCOVERY_ONLY_NOT_FROZEN_COHORT",
        "generated_at": generated_at,
        "date_range": {"start": START.isoformat(), "end": END.isoformat()},
        "openfda_matching_applications": total_records,
        "candidate_count": len(ordered),
        "candidates": ordered,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["registry_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()

    out = Path("validation/m7/discovery")
    out.mkdir(parents=True, exist_ok=True)
    (out / "fda-regulatory-candidates.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "generated_at": generated_at,
        "candidate_count": len(ordered),
        "unique_sponsors": len(sponsors),
        "year_counts": dict(sorted(year_counts.items())),
        "submission_status_counts": dict(sorted(status_counts.items())),
        "submission_type_counts": dict(sorted(type_counts.items())),
        "registry_sha256": payload["registry_sha256"],
        "authoritative_cohort_events": 0,
        "cohort_frozen": False,
    }
    (out / "fda-regulatory-candidates-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
