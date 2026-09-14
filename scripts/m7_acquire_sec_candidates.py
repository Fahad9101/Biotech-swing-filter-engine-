"""Build a broad Milestone 7 event-candidate registry from SEC primary sources.

This script is discovery and provenance acquisition only. It deliberately does not
freeze the M7 cohort, reveal price outcomes, or promote a filing to an authoritative
historical event without the later verification steps required by the M7 contract.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import httpx

SEC_BASE = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"
SEC_TICKER_MIRROR = (
    "https://raw.githubusercontent.com/ryansmccoy/py-sec-edgar/"
    "1603502fec209d186615b086bd28d17cc86589b1/refdata/company_tickers.json"
)
RESEARCH_MAPPING = (
    "https://huggingface.co/datasets/chufangao/CTO/resolve/main/"
    "labels_and_tickers/labels_and_tickers.csv"
)
YEARS = set(range(2018, 2026))
SEC_FORMS = {"8-K", "6-K"}
MAX_DISCOVERY_TICKERS = 220
MAX_FILINGS_PER_ISSUER = 90
REQUEST_DELAY_SECONDS = 0.13

THERAPEUTIC_NAME_TERMS = (
    "bio",
    "therapeutic",
    "pharma",
    "pharmaceutical",
    "medicine",
    "medicines",
    "oncology",
    "gene",
)

MATERIAL_RESULT_TERMS = (
    "topline",
    "top-line",
    "clinical trial results",
    "study results",
    "primary endpoint",
    "key secondary endpoint",
    "met the primary",
    "did not meet",
    "statistically significant",
    "phase 1",
    "phase i",
    "phase 2",
    "phase ii",
    "phase 3",
    "phase iii",
    "pivotal",
    "proof-of-concept",
    "proof of concept",
)
REGULATORY_TERMS = (
    "pdufa",
    "complete response letter",
    "advisory committee",
    "fda approval",
    "fda approved",
    "food and drug administration approved",
    "biologics license application",
    "new drug application",
    "clinical hold",
)
CONFERENCE_TERMS = (
    "conference",
    "congress",
    "annual meeting",
    "asco",
    "ash ",
    "aacr",
    "esmo",
    "aan ",
    "easl",
)
NEGATIVE_TERMS = (
    "did not meet",
    "failed to meet",
    "complete response letter",
    "clinical hold",
    "terminated",
    "discontinue",
    "discontinued",
    "not statistically significant",
    "futility",
)

NCT_RE = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
PHASE_PATTERNS = (
    (re.compile(r"\bphase\s*(?:3|iii)\b", re.IGNORECASE), "PHASE3"),
    (re.compile(r"\bphase\s*(?:2\s*/\s*3|ii\s*/\s*iii)\b", re.IGNORECASE), "PHASE2_3"),
    (re.compile(r"\bphase\s*(?:2|ii)\b", re.IGNORECASE), "PHASE2"),
    (re.compile(r"\bphase\s*(?:1\s*/\s*2|i\s*/\s*ii)\b", re.IGNORECASE), "PHASE1_2"),
    (re.compile(r"\bphase\s*(?:1|i)\b", re.IGNORECASE), "PHASE1"),
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


@dataclass(frozen=True)
class IssuerSeed:
    ticker: str
    cik: str
    company: str
    discovery_basis: tuple[str, ...]


@dataclass(frozen=True)
class CandidateEvent:
    candidate_id: str
    ticker: str
    cik: str
    company: str
    form: str
    accession: str
    accepted_at: str
    filing_date: str
    sec_primary_url: str
    sec_exhibit_url: str | None
    source_text_sha256: str
    event_tags: tuple[str, ...]
    phase: str | None
    nct_ids: tuple[str, ...]
    possible_negative_event: bool
    excerpt: str
    provenance_status: str
    required_next_verification: tuple[str, ...]


class SecClient:
    def __init__(self) -> None:
        user_agent = os.environ.get(
            "BOE_SEC_USER_AGENT",
            "BOE-M7 historical-validation research "
            "https://github.com/Fahad9101/Biotech-swing-filter-engine-",
        )
        self.client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=30.0,
            follow_redirects=True,
        )
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < REQUEST_DELAY_SECONDS:
            time.sleep(REQUEST_DELAY_SECONDS - elapsed)

    def get_text(self, url: str) -> str:
        self._throttle()
        response = self.client.get(url)
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response.text

    def get_json(self, url: str) -> dict[str, Any]:
        return json.loads(self.get_text(url))

    def close(self) -> None:
        self.client.close()


def _safe_str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _research_tickers(client: httpx.Client) -> set[str]:
    response = client.get(RESEARCH_MAPPING, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
    return {
        (row.get("Ticker") or "").strip().upper()
        for row in reader
        if (row.get("Ticker") or "").strip()
    }


def _ticker_payload_from_pinned_mirror(client: httpx.Client) -> dict[str, Any]:
    response = client.get(SEC_TICKER_MIRROR, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("pinned SEC ticker mirror did not return an object")
    return payload


def _issuer_seeds(sec: SecClient) -> list[IssuerSeed]:
    with httpx.Client() as discovery_client:
        ticker_payload = _ticker_payload_from_pinned_mirror(discovery_client)
        research_tickers = _research_tickers(discovery_client)

    records: list[IssuerSeed] = []
    for record in ticker_payload.values():
        if not isinstance(record, dict):
            continue
        ticker = _safe_str(record.get("ticker")).upper()
        title = _safe_str(record.get("title"))
        raw_cik = record.get("cik_str")
        if isinstance(raw_cik, int):
            cik_value = raw_cik
        elif isinstance(raw_cik, str) and raw_cik.isdigit():
            cik_value = int(raw_cik)
        else:
            continue
        if not ticker:
            continue
        lower_title = title.lower()
        bases: list[str] = []
        if ticker in research_tickers:
            bases.append("CTO_TICKER_DISCOVERY")
        if any(term in lower_title for term in THERAPEUTIC_NAME_TERMS):
            bases.append("SEC_NAME_HEURISTIC")
        if not bases:
            continue
        records.append(
            IssuerSeed(
                ticker=ticker,
                cik=f"{cik_value:010d}",
                company=title,
                discovery_basis=tuple(sorted(set(bases))),
            )
        )

    records.sort(key=lambda item: ("CTO_TICKER_DISCOVERY" not in item.discovery_basis, item.ticker))
    return records[:MAX_DISCOVERY_TICKERS]


def _filing_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    keys = [
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
        "items",
    ]
    lengths = [len(recent.get(key, [])) for key in keys if isinstance(recent.get(key), list)]
    if not lengths:
        return []
    count = min(lengths)
    rows: list[dict[str, str]] = []
    for index in range(count):
        rows.append({key: _safe_str(recent.get(key, [])[index]) for key in keys})
    return rows


def _all_filing_rows(sec: SecClient, cik: str) -> list[dict[str, str]]:
    payload = sec.get_json(f"{SEC_DATA}/submissions/CIK{cik}.json")
    rows = _filing_rows(payload)
    files = payload.get("filings", {}).get("files", [])
    if isinstance(files, list):
        for item in files:
            if not isinstance(item, dict):
                continue
            name = _safe_str(item.get("name"))
            if not name:
                continue
            historical = sec.get_json(f"{SEC_DATA}/submissions/{name}")
            rows.extend(_filing_rows({"filings": {"recent": historical}}))
    return rows


def _filing_year(row: dict[str, str]) -> int | None:
    value = row.get("filingDate", "")
    try:
        return int(value[:4])
    except (TypeError, ValueError):
        return None


def _archive_root(cik: str, accession: str) -> str:
    return f"{SEC_BASE}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"


def _find_press_release(sec: SecClient, cik: str, accession: str) -> tuple[str | None, str]:
    root = _archive_root(cik, accession)
    try:
        index = sec.get_json(f"{root}/index.json")
    except (httpx.HTTPError, json.JSONDecodeError):
        return None, ""
    directory = index.get("directory", {})
    items = directory.get("item", []) if isinstance(directory, dict) else []
    if not isinstance(items, list):
        return None, ""
    names = [
        _safe_str(item.get("name"))
        for item in items
        if isinstance(item, dict) and _safe_str(item.get("name"))
    ]
    preferred = [
        name
        for name in names
        if re.search(r"(?:ex|exhibit)?[-_]?99(?:[.-]?1)?", name, re.IGNORECASE)
        and name.lower().endswith((".htm", ".html", ".txt"))
    ]
    for name in preferred[:3]:
        url = f"{root}/{name}"
        try:
            return url, html_to_text(sec.get_text(url))
        except httpx.HTTPError:
            continue
    return None, ""


def _phase(text: str) -> str | None:
    for pattern, label in PHASE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _event_tags(text: str) -> tuple[str, ...]:
    lower = text.lower()
    tags: set[str] = set()
    if any(term in lower for term in REGULATORY_TERMS):
        tags.add("REGULATORY_CANDIDATE")
    if any(term in lower for term in MATERIAL_RESULT_TERMS):
        phase = _phase(text)
        if phase == "PHASE3" or phase == "PHASE2_3":
            tags.add("PHASE_3_PIVOTAL_CANDIDATE")
        elif phase == "PHASE2":
            tags.add("PHASE_2_POC_CANDIDATE")
        elif phase in {"PHASE1", "PHASE1_2"}:
            tags.add("EARLY_CLINICAL_CANDIDATE")
        else:
            tags.add("CLINICAL_RESULT_CANDIDATE")
    if any(term in lower for term in CONFERENCE_TERMS) and (
        "data" in lower or "results" in lower or "present" in lower
    ):
        tags.add("CONFERENCE_OTHER_CANDIDATE")
    return tuple(sorted(tags))


def _best_excerpt(text: str) -> str:
    lower = text.lower()
    needles = MATERIAL_RESULT_TERMS + REGULATORY_TERMS + CONFERENCE_TERMS
    locations = [lower.find(term) for term in needles if lower.find(term) >= 0]
    start = max(0, min(locations) - 300) if locations else 0
    return text[start : start + 1400]


def _candidate_from_filing(
    sec: SecClient,
    issuer: IssuerSeed,
    row: dict[str, str],
) -> CandidateEvent | None:
    accession = row["accessionNumber"]
    primary = row["primaryDocument"]
    if not accession or not primary:
        return None
    root = _archive_root(issuer.cik, accession)
    primary_url = f"{root}/{primary}"
    try:
        primary_text = html_to_text(sec.get_text(primary_url))
    except httpx.HTTPError:
        return None

    tags = _event_tags(primary_text)
    exhibit_url: str | None = None
    source_text = primary_text
    if not tags and "press release" in primary_text.lower():
        exhibit_url, exhibit_text = _find_press_release(sec, issuer.cik, accession)
        if exhibit_text:
            exhibit_tags = _event_tags(exhibit_text)
            if exhibit_tags:
                tags = exhibit_tags
                source_text = exhibit_text
    elif tags:
        candidate_exhibit_url, exhibit_text = _find_press_release(sec, issuer.cik, accession)
        if exhibit_text and len(_event_tags(exhibit_text)) >= len(tags):
            exhibit_url = candidate_exhibit_url
            source_text = exhibit_text
            tags = tuple(sorted(set(tags) | set(_event_tags(exhibit_text))))

    if not tags:
        return None

    accepted_at = row.get("acceptanceDateTime", "")
    if not accepted_at:
        accepted_at = f"{row.get('filingDate', '')}T23:59:59Z"
    elif accepted_at.endswith("Z"):
        pass
    elif len(accepted_at) == 14 and accepted_at.isdigit():
        accepted_at = datetime.strptime(accepted_at, "%Y%m%d%H%M%S").replace(tzinfo=UTC).isoformat()

    source_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    candidate_id = hashlib.sha256(
        f"{issuer.cik}|{accession}|{','.join(tags)}".encode()
    ).hexdigest()[:24]
    lower = source_text.lower()
    return CandidateEvent(
        candidate_id=candidate_id,
        ticker=issuer.ticker,
        cik=issuer.cik,
        company=issuer.company,
        form=row["form"],
        accession=accession,
        accepted_at=accepted_at,
        filing_date=row["filingDate"],
        sec_primary_url=primary_url,
        sec_exhibit_url=exhibit_url,
        source_text_sha256=source_hash,
        event_tags=tags,
        phase=_phase(source_text),
        nct_ids=tuple(sorted({match.upper() for match in NCT_RE.findall(source_text)})),
        possible_negative_event=any(term in lower for term in NEGATIVE_TERMS),
        excerpt=_best_excerpt(source_text),
        provenance_status="SEC_PRIMARY_CANDIDATE_NOT_YET_COHORT_VERIFIED",
        required_next_verification=(
            "VERIFY_FIRST_MATERIAL_PUBLIC_TIMESTAMP",
            "VERIFY_BOE_UNIVERSE_AT_EVENT",
            "VERIFY_TRIAL_OR_REGULATORY_IDENTITY",
            "VERIFY_PRIMARY_STRATUM_PRE_OUTCOME",
            "VERIFY_POINT_IN_TIME_CAPITAL_STRUCTURE",
            "VERIFY_MARKET_DATA_PROVENANCE",
        ),
    )


def _write_outputs(seeds: list[IssuerSeed], candidates: list[CandidateEvent]) -> None:
    output_dir = Path("validation/m7/discovery")
    output_dir.mkdir(parents=True, exist_ok=True)
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (item.accepted_at, item.ticker, item.accession),
    )
    registry_payload = {
        "format_version": "1.0",
        "role": "DISCOVERY_ONLY_NOT_FROZEN_COHORT",
        "generated_at": datetime.now(UTC).isoformat(),
        "years": [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
        "issuer_seed_count": len(seeds),
        "candidate_count": len(sorted_candidates),
        "issuer_mapping_source": SEC_TICKER_MIRROR,
        "issuer_mapping_role": "DISCOVERY_ONLY",
        "candidates": [asdict(item) for item in sorted_candidates],
    }
    canonical = json.dumps(registry_payload, sort_keys=True, separators=(",", ":"))
    registry_payload["registry_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path = output_dir / "sec-primary-candidates.json"
    path.write_text(json.dumps(registry_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    year_counts: dict[str, int] = {}
    negative = 0
    unique_tickers: set[str] = set()
    for item in sorted_candidates:
        unique_tickers.add(item.ticker)
        year_counts[item.filing_date[:4]] = year_counts.get(item.filing_date[:4], 0) + 1
        negative += int(item.possible_negative_event)
        for tag in item.event_tags:
            counts[tag] = counts.get(tag, 0) + 1

    summary = {
        "generated_at": registry_payload["generated_at"],
        "issuer_seed_count": len(seeds),
        "candidate_count": len(sorted_candidates),
        "unique_candidate_tickers": len(unique_tickers),
        "possible_negative_candidates": negative,
        "tag_counts": dict(sorted(counts.items())),
        "year_counts": dict(sorted(year_counts.items())),
        "registry_sha256": registry_payload["registry_sha256"],
        "authoritative_cohort_events": 0,
        "cohort_frozen": False,
    }
    (output_dir / "sec-primary-candidates-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sec = SecClient()
    try:
        seeds = _issuer_seeds(sec)
        candidates: list[CandidateEvent] = []
        for issuer_index, issuer in enumerate(seeds, start=1):
            try:
                filings = _all_filing_rows(sec, issuer.cik)
            except (httpx.HTTPError, json.JSONDecodeError):
                continue
            eligible = [
                row
                for row in filings
                if row.get("form") in SEC_FORMS and _filing_year(row) in YEARS
            ]
            eligible.sort(key=lambda row: row.get("filingDate", ""), reverse=True)
            for row in eligible[:MAX_FILINGS_PER_ISSUER]:
                candidate = _candidate_from_filing(sec, issuer, row)
                if candidate is not None:
                    candidates.append(candidate)
            print(
                f"issuer {issuer_index}/{len(seeds)} {issuer.ticker}: "
                f"{len(eligible)} eligible filings; {len(candidates)} cumulative candidates",
                flush=True,
            )
        _write_outputs(seeds, candidates)
        print(f"wrote {len(candidates)} SEC primary-source candidates", flush=True)
    finally:
        sec.close()


if __name__ == "__main__":
    main()
