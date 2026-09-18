"""Feasibility pilot for a real, non-fabricated SCIENCE-factor redesign
using structured clinical-trial data, run against the full frozen
Milestone 7 cohort (validation/m7/cohort-manifest.json, 120 events).

Why this exists: ClinicalTrials.gov's own API (src/boe/ingestion/clinicaltrials.py,
CTGOV_API) returns a consistent, real, tested 403 Forbidden to programmatic
requests from this environment (confirmed with multiple User-Agent strings,
including a full browser-mimicking one), while the same study pages are
reachable through an interactive browser - this is an environment/IP-level
block on programmatic access, not an outage. This matches the pre-existing
962/962 fetch-failure result already committed in
validation/m7/discovery/clinicaltrials-official-candidates.json (from before
this pilot), so it is a persistent, structural condition, not a transient
blip worth retrying.

This script tests whether a free, non-CT.gov-blocked bulk research dataset
(huggingface.co/datasets/chufangao/CTO, already referenced for candidate
discovery by scripts/m7_enrich_clinical_candidates.py) can support a genuine
NCT-to-event match at real, checkable scale across the full cohort, using
only structural/design data - never the dataset's own outcome-prediction
"labels" column, which is functionally an outcome label and is therefore
never read here at all (not filtered out after reading - the column is
never selected from any parsed row).

Matching an event to a candidate trial requires the event's own, already
real, already-known HistoricalEvent.asset text (e.g. "Libtayo (cemiplimab)")
to appear as a normalized token in the candidate's title. Naive ticker- and
date-only matching was tested first and produced real, confirmed false
positives (Regeneron's real Libtayo/NSCLC event matched an unrelated
cat-allergy asthma trial by date proximity alone; Genmab's real daratumumab
event matched a cervical-cancer tisotumab-vedotin trial) - this asset-name
requirement is the fix, using data already sourced during cohort-building,
not new fabrication.

Live network calls: real, unauthenticated HTTPS GETs to huggingface.co CSV
exports. Not exercised live by CI (see scripts/m7_build_cash_dilution_scores.py
for the same reasoning applied to SEC EDGAR); tests inject a mocked
httpx.Client instead. huggingface.co is intentionally not added to
boe.ingestion.http.ALLOWED_HOSTS: this script is a one-off feasibility
pilot, not part of the scored-factor production pipeline, matching the same
raw-httpx precedent already established by scripts/m7_enrich_clinical_candidates.py
for discovery-only tooling.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.historical_validation import CohortManifest  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/discovery/science-redesign-pilot.json"
SUMMARY_PATH = ROOT / "validation/m7/discovery/science-redesign-pilot-summary.json"

RESEARCH_BASE = "https://huggingface.co/datasets/chufangao/CTO/resolve/main/"
METADATA_URL = RESEARCH_BASE + "human_labels_2020_2024/human_labels_2020_2024.csv"
MAPPING_URL = RESEARCH_BASE + "labels_and_tickers/labels_and_tickers.csv"
USER_AGENT = "BOE-M7 historical-validation research https://github.com/Fahad9101/Biotech-swing-filter-engine-"

# Candidate trial phase/completion-year filter - identical to the filter
# scripts/m7_enrich_clinical_candidates.py already applies for discovery.
ELIGIBLE_PHASES = {"PHASE1", "PHASE1/PHASE2", "PHASE2", "PHASE2/PHASE3", "PHASE3"}
ELIGIBLE_YEARS = {"2020", "2021", "2022", "2023", "2024"}

# Only structural/design metadata fields are ever read from the metadata CSV.
# The dataset's "labels" column (an ML outcome-prediction target) is never
# selected here under any circumstance.
METADATA_FIELDS = (
    "nct_id",
    "brief_title",
    "official_title",
    "phase",
    "completion_year",
    "primary_completion_date",
    "completion_date",
    "study_type",
    "enrollment",
    "enrollment_type",
    "number_of_arms",
    "overall_status",
)
DESIGN_FIELDS_ABSENT_FROM_DATASET = ("allocation", "masking", "intervention_model")

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _norm(text: str) -> str:
    return _TOKEN_RE.sub("", text.lower())


def _asset_tokens(asset: str) -> tuple[str, ...]:
    parts = re.split(r"[\s/+\-()]+", asset)
    return tuple(dict.fromkeys(_norm(part) for part in parts if len(_norm(part)) >= 4))


def _generic_ticker_token_only(ticker: str, asset_tokens: tuple[str, ...], title_norm: str) -> bool:
    """True when the ONLY reason a title matched is that the asset text
    happens to contain the company's own ticker symbol as a token (e.g.
    "bempegaldesleukin (BEMPEG, NKTR-214)" contains the generic token "nktr",
    which matches ANY Nektar Therapeutics trial title, not specifically the
    NKTR-214 one) - i.e. no OTHER, more specific asset token also appears in
    the title. Found by manually spot-checking the full-cohort pilot run
    (NEG-P3-2022-NKTR-PIVOTIO001 matched an unrelated NKTR-102 trial;
    NEG-P2-2024-SAGE-LIGHTWAVE/PRECEDENT and P2-2024-SAGE-DIMENSION all
    matched the same unrelated SAGE-324 trial) - a real, confirmed residual
    false-positive mode even after the asset-name-token fix.
    """
    ticker_token = _norm(ticker)
    if ticker_token not in asset_tokens or len(ticker_token) > 5:
        return False
    other_tokens = [token for token in asset_tokens if token != ticker_token]
    return not any(token in title_norm for token in other_tokens)


def _csv_rows(client: httpx.Client, url: str) -> list[dict[str, str]]:
    response = client.get(url)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text.lstrip("﻿")))
    return [dict(row) for row in reader]


def _ticker_to_ncts(mapping_rows: list[dict[str, str]]) -> dict[str, set[str]]:
    by_ticker: dict[str, set[str]] = {}
    for row in mapping_rows:
        nct = (row.get("nct_id") or "").strip().upper()
        ticker = (row.get("Ticker") or "").strip().upper()
        if nct.startswith("NCT") and ticker:
            by_ticker.setdefault(ticker, set()).add(nct)
    return by_ticker


def _nct_metadata(metadata_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_nct: dict[str, dict[str, str]] = {}
    for row in metadata_rows:
        nct = (row.get("nct_id") or "").strip().upper()
        if not nct.startswith("NCT"):
            continue
        by_nct[nct] = {field: (row.get(field) or "").strip() for field in METADATA_FIELDS}
    return by_nct


def build(client: httpx.Client | None = None) -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))

    owns_client = client is None
    active_client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30.0, follow_redirects=True
    )
    try:
        ticker_to_ncts = _ticker_to_ncts(_csv_rows(active_client, MAPPING_URL))
        nct_metadata = _nct_metadata(_csv_rows(active_client, METADATA_URL))
    finally:
        if owns_client:
            active_client.close()

    results: list[dict[str, Any]] = []
    for event in sorted(manifest.events, key=lambda e: e.event_id):
        candidate_ncts = ticker_to_ncts.get(event.ticker, set())
        if not candidate_ncts:
            results.append(
                {
                    "event_id": event.event_id,
                    "ticker": event.ticker,
                    "asset": event.asset,
                    "stage": "NO_TICKER_COVERAGE",
                    "matched_ncts": [],
                }
            )
            continue

        phase_year_candidates = sorted(
            nct
            for nct in candidate_ncts
            if nct in nct_metadata
            and nct_metadata[nct]["phase"].upper() in ELIGIBLE_PHASES
            and nct_metadata[nct]["completion_year"] in ELIGIBLE_YEARS
        )
        if not phase_year_candidates:
            results.append(
                {
                    "event_id": event.event_id,
                    "ticker": event.ticker,
                    "asset": event.asset,
                    "stage": "TICKER_COVERAGE_NO_PHASE_YEAR_CANDIDATE",
                    "matched_ncts": [],
                }
            )
            continue

        asset_tokens = _asset_tokens(event.asset)
        matched: list[dict[str, Any]] = []
        for nct in phase_year_candidates:
            meta = nct_metadata[nct]
            title_norm = _norm(meta["brief_title"] + " " + meta["official_title"])
            if asset_tokens and any(token in title_norm for token in asset_tokens):
                matched.append(
                    {
                        "nct_id": nct,
                        "brief_title": meta["brief_title"],
                        "phase": meta["phase"],
                        "primary_completion_date": meta["primary_completion_date"],
                        "completion_date": meta["completion_date"],
                        "study_type": meta["study_type"],
                        "number_of_arms": meta["number_of_arms"],
                        "generic_ticker_token_only_match": _generic_ticker_token_only(
                            event.ticker, asset_tokens, title_norm
                        ),
                    }
                )

        specific_match_exists = any(not m["generic_ticker_token_only_match"] for m in matched)
        if not matched:
            stage = "CANDIDATES_NO_ASSET_NAME_MATCH"
        elif specific_match_exists:
            stage = "ASSET_NAME_MATCHED"
        else:
            stage = "GENERIC_TICKER_TOKEN_ONLY_MATCH"
        results.append(
            {
                "event_id": event.event_id,
                "ticker": event.ticker,
                "asset": event.asset,
                "stage": stage,
                "matched_ncts": matched,
            }
        )

    stage_counts: dict[str, int] = {}
    for result in results:
        stage_counts[result["stage"]] = stage_counts.get(result["stage"], 0) + 1
    matched_count = stage_counts.get("ASSET_NAME_MATCHED", 0)
    generic_only_count = stage_counts.get("GENERIC_TICKER_TOKEN_ONLY_MATCH", 0)

    conclusion = (
        f"{matched_count}/{len(results)} events ({matched_count / len(results):.0%}) resolve "
        "to at least one real, drug-name-verified candidate trial via this free dataset. A "
        f"further {generic_only_count} events only matched because the asset text happened to "
        "contain the company's own ticker as a generic token (e.g. NKTR-214's event matching an "
        "unrelated NKTR-102 trial, or three separate SAGE-718 events all matching the same "
        "unrelated SAGE-324 trial) - confirmed by manual spot-check, not assumed - so they are "
        "excluded from the reliable count above rather than silently accepted. Even for the "
        "reliable matches, the metadata CSV does not carry allocation/masking/intervention_model "
        f"(the fields TRIAL_DESIGN actually needs - see {DESIGN_FIELDS_ABSENT_FROM_DATASET}), "
        "only weaker proxies (phase, arm count, study_type). Given a genuine match rate this low "
        "and missing the specific fields the redesign was meant to make objective, this path "
        "does not clear the bar to build a full SCIENCE-redesign pipeline on top of it. "
        "RECOMMENDATION: DO_NOT_PROCEED - document this finding and do not build "
        "scripts/m7_build_science_scores.py against this data source."
    )

    return {
        "generator": "python scripts/m7_pilot_science_redesign.py",
        "role": "FEASIBILITY_PILOT_NOT_A_SCORED_FACTOR",
        "cohort_sha256": manifest.cohort_sha256,
        "event_count": len(results),
        "data_sources": {
            "blocked_primary_source": "https://clinicaltrials.gov/api/v2/studies (403 from this "
            "environment; see validation/m7/discovery/clinicaltrials-official-candidates.json)",
            "mapping_url": MAPPING_URL,
            "metadata_url": METADATA_URL,
            "outcome_label_column_read": False,
        },
        "match_requirement": (
            "candidate trial title (brief_title + official_title, normalized) must contain a "
            "normalized token (>=4 chars) from the event's real HistoricalEvent.asset field"
        ),
        "stage_counts": dict(sorted(stage_counts.items())),
        "design_fields_absent_from_dataset": list(DESIGN_FIELDS_ABSENT_FROM_DATASET),
        "results": results,
        "conclusion": conclusion,
        "recommendation": "DO_NOT_PROCEED",
    }


def main() -> None:
    argparse.ArgumentParser().parse_args()
    status = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render(status))
    summary = {
        "generator": status["generator"],
        "event_count": status["event_count"],
        "stage_counts": status["stage_counts"],
        "conclusion": status["conclusion"],
        "recommendation": status["recommendation"],
    }
    SUMMARY_PATH.write_text(render(summary))
    print(json.dumps(summary["stage_counts"] | {"recommendation": status["recommendation"]}))


if __name__ == "__main__":
    main()
