"""Enrich M7 clinical-event discovery candidates from ClinicalTrials.gov v2.

The research files are used only to identify candidate NCT/ticker pairs. Their outcome
labels are intentionally ignored. Current ClinicalTrials.gov records are official
identity/design evidence but are NOT point-in-time evidence for a historical BOE
snapshot; historical record-version verification remains mandatory before promotion.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
RESEARCH_BASE = "https://huggingface.co/datasets/chufangao/CTO/resolve/main/"
METADATA_URL = RESEARCH_BASE + "human_labels_2020_2024/human_labels_2020_2024.csv"
MAPPING_URL = RESEARCH_BASE + "labels_and_tickers/labels_and_tickers.csv"
PHASES = {"PHASE1", "PHASE1/PHASE2", "PHASE2", "PHASE2/PHASE3", "PHASE3"}
DISCOVERY_YEARS = {"2020", "2021", "2022", "2023", "2024"}
REQUEST_DELAY_SECONDS = 0.08


def _csv_rows(client: httpx.Client, url: str) -> list[dict[str, str]]:
    response = client.get(url)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
    return [dict(row) for row in reader]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _date_field(module: dict[str, Any], key: str) -> str | None:
    struct = _dict(module.get(key))
    value = struct.get("date")
    return str(value).strip() if isinstance(value, str) and value.strip() else None


def _candidate_pairs(client: httpx.Client) -> list[tuple[str, str]]:
    metadata = _csv_rows(client, METADATA_URL)
    mappings = _csv_rows(client, MAPPING_URL)
    by_nct: dict[str, set[str]] = {}
    for row in mappings:
        nct = (row.get("nct_id") or "").strip().upper()
        ticker = (row.get("Ticker") or "").strip().upper()
        if nct.startswith("NCT") and ticker:
            by_nct.setdefault(nct, set()).add(ticker)

    pairs: list[tuple[str, str]] = []
    for row in metadata:
        nct = (row.get("nct_id") or "").strip().upper()
        phase = (row.get("phase") or "").strip().upper()
        completion_year = (row.get("completion_year") or "").strip()
        if nct not in by_nct or phase not in PHASES or completion_year not in DISCOVERY_YEARS:
            continue
        for ticker in sorted(by_nct[nct]):
            pairs.append((nct, ticker))
    return sorted(set(pairs))


def _fetch_study(client: httpx.Client, nct: str) -> dict[str, Any] | None:
    response = client.get(f"{CTGOV}/{nct}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def _extract(nct: str, ticker: str, study: dict[str, Any]) -> dict[str, Any]:
    protocol = _dict(study.get("protocolSection"))
    identification = _dict(protocol.get("identificationModule"))
    status = _dict(protocol.get("statusModule"))
    design = _dict(protocol.get("designModule"))
    conditions = _dict(protocol.get("conditionsModule"))
    arms = _dict(protocol.get("armsInterventionsModule"))
    sponsors = _dict(protocol.get("sponsorCollaboratorsModule"))
    lead_sponsor = _dict(sponsors.get("leadSponsor"))

    interventions: list[str] = []
    raw_interventions = arms.get("interventions")
    if isinstance(raw_interventions, list):
        for item in raw_interventions:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    interventions.append(name.strip())

    first_post = _date_field(status, "studyFirstPostDateStruct")
    results_first_post = _date_field(status, "resultsFirstPostDateStruct")
    last_update_post = _date_field(status, "lastUpdatePostDateStruct")
    primary_completion = _date_field(status, "primaryCompletionDateStruct")
    completion = _date_field(status, "completionDateStruct")
    phases = _strings(design.get("phases"))
    current_record_hash = hashlib.sha256(
        json.dumps(study, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    return {
        "candidate_id": hashlib.sha256(f"{nct}|{ticker}".encode()).hexdigest()[:24],
        "nct_id": nct,
        "discovery_ticker": ticker,
        "brief_title": identification.get("briefTitle"),
        "official_title": identification.get("officialTitle"),
        "lead_sponsor": lead_sponsor.get("name"),
        "lead_sponsor_class": lead_sponsor.get("class"),
        "phases": phases,
        "overall_status_current": status.get("overallStatus"),
        "conditions": _strings(conditions.get("conditions")),
        "interventions": tuple(dict.fromkeys(interventions)),
        "study_first_post_date": first_post,
        "primary_completion_date": primary_completion,
        "completion_date": completion,
        "results_first_post_date": results_first_post,
        "last_update_post_date": last_update_post,
        "official_current_record_url": f"{CTGOV}/{nct}",
        "current_record_sha256": current_record_hash,
        "provenance_status": "CTGOV_CURRENT_RECORD_DISCOVERY_NOT_POINT_IN_TIME",
        "required_next_verification": [
            "SELECT_HISTORICAL_RECORD_VERSION_AT_EACH_SNAPSHOT_CUTOFF",
            "VERIFY_FIRST_MATERIAL_PUBLIC_RESULT_TIMESTAMP",
            "VERIFY_HISTORICAL_TICKER_AND_BOE_UNIVERSE",
            "VERIFY_PRIMARY_STRATUM_PRE_OUTCOME",
            "VERIFY_POINT_IN_TIME_CAPITAL_STRUCTURE",
            "VERIFY_MARKET_DATA_PROVENANCE",
        ],
    }


def main() -> None:
    headers = {
        "User-Agent": (
            "BOE-M7 historical-validation research "
            "https://github.com/Fahad9101/Biotech-swing-filter-engine-"
        )
    }
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
        pairs = _candidate_pairs(client)
        print(f"candidate NCT/ticker pairs: {len(pairs)}", flush=True)
        cache: dict[str, dict[str, Any] | None] = {}
        for index, (nct, ticker) in enumerate(pairs, start=1):
            if nct not in cache:
                try:
                    cache[nct] = _fetch_study(client, nct)
                except httpx.HTTPError as exc:
                    failures.append({"nct_id": nct, "error": type(exc).__name__})
                    cache[nct] = None
                time.sleep(REQUEST_DELAY_SECONDS)
            study = cache[nct]
            if study is not None:
                records.append(_extract(nct, ticker, study))
            if index % 100 == 0:
                print(
                    f"processed {index}/{len(pairs)} pairs; "
                    f"{len(records)} official records; {len(failures)} failures",
                    flush=True,
                )

    records.sort(
        key=lambda item: (
            str(item["results_first_post_date"] or item["primary_completion_date"] or ""),
            str(item["discovery_ticker"]),
            str(item["nct_id"]),
        )
    )
    generated_at = datetime.now(UTC).isoformat()
    payload = {
        "format_version": "1.0",
        "role": "CLINICAL_DISCOVERY_ONLY_NOT_FROZEN_COHORT",
        "generated_at": generated_at,
        "research_mapping_role": "NCT_TICKER_CANDIDATE_DISCOVERY_ONLY",
        "research_outcome_labels_used": False,
        "official_current_record_count": len(records),
        "fetch_failures": failures,
        "records": records,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["registry_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()

    phase_counts: dict[str, int] = {}
    year_counts: dict[str, int] = {}
    tickers: set[str] = set()
    for item in records:
        tickers.add(str(item["discovery_ticker"]))
        for phase in item["phases"]:
            phase_counts[str(phase)] = phase_counts.get(str(phase), 0) + 1
        approximate_date = item["results_first_post_date"] or item["primary_completion_date"]
        if approximate_date:
            year = str(approximate_date)[:4]
            year_counts[year] = year_counts.get(year, 0) + 1

    summary = {
        "generated_at": generated_at,
        "official_current_record_count": len(records),
        "unique_tickers": len(tickers),
        "fetch_failure_count": len(failures),
        "phase_counts": dict(sorted(phase_counts.items())),
        "approximate_date_year_counts": dict(sorted(year_counts.items())),
        "registry_sha256": payload["registry_sha256"],
        "authoritative_cohort_events": 0,
        "cohort_frozen": False,
        "point_in_time_record_versions_selected": 0,
    }

    out = Path("validation/m7/discovery")
    out.mkdir(parents=True, exist_ok=True)
    (out / "clinicaltrials-official-candidates.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (out / "clinicaltrials-official-candidates-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
