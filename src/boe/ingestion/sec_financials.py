"""SEC XBRL financial facts and capital-raising filing adapters for Milestone 4."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from boe.financials import (
    FinancialFact,
    FinancingDisclosureObservation,
    FinancingFiling,
)

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
TRACKED_FINANCING_FORMS = frozenset(
    {
        "S-3",
        "S-3/A",
        "S-3ASR",
        "S-3ASR/A",
        "424B1",
        "424B2",
        "424B3",
        "424B4",
        "424B5",
        "424B7",
        "424B8",
    }
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MONEY_RE = re.compile(
    r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*(million|billion|thousand)?",
    re.IGNORECASE,
)


def sec_companyfacts_url(cik: str | int) -> str:
    return COMPANYFACTS_URL.format(cik=_normalize_cik(cik))


def parse_companyfacts(
    content: bytes,
    *,
    issuer_id: str,
    as_of: datetime,
    default_evidence_id: UUID,
    accession_available_at: dict[str, datetime] | None = None,
    accession_evidence_ids: dict[str, UUID] | None = None,
) -> tuple[FinancialFact, ...]:
    """Parse only facts knowable by ``as_of`` with deterministic lineage.

    SEC Company Facts gives filing dates but not acceptance timestamps. Callers may
    provide exact accession acceptance times from submissions. When unavailable,
    the parser conservatively treats the fact as available at 23:59:59 UTC on the
    filing date, preventing same-day look-ahead rather than guessing an earlier
    acceptance time.
    """

    _require_aware(as_of, "as_of")
    payload = _json_object(content)
    facts_payload = payload.get("facts")
    if not isinstance(facts_payload, dict):
        raise ValueError("SEC companyfacts payload lacks facts object")
    available_map = accession_available_at or {}
    evidence_map = accession_evidence_ids or {}

    parsed: list[FinancialFact] = []
    for taxonomy, taxonomy_payload in facts_payload.items():
        if not isinstance(taxonomy_payload, dict):
            continue
        for concept, concept_payload in taxonomy_payload.items():
            if not isinstance(concept_payload, dict):
                continue
            units = concept_payload.get("units")
            if not isinstance(units, dict):
                continue
            for unit, observations in units.items():
                if not isinstance(observations, list):
                    continue
                for observation in observations:
                    if not isinstance(observation, dict):
                        continue
                    fact = _financial_fact_from_observation(
                        issuer_id=issuer_id,
                        taxonomy=str(taxonomy),
                        concept=str(concept),
                        unit=str(unit),
                        observation=observation,
                        as_of=as_of,
                        default_evidence_id=default_evidence_id,
                        available_map=available_map,
                        evidence_map=evidence_map,
                    )
                    if fact is not None:
                        parsed.append(fact)
    return tuple(sorted(parsed, key=_fact_sort_key))


def parse_financing_filings(
    content: bytes,
    *,
    issuer_id: str,
    as_of: datetime,
) -> tuple[FinancingFiling, ...]:
    """Extract S-3 shelf and 424B prospectus-supplement filing metadata."""

    _require_aware(as_of, "as_of")
    payload = _json_object(content)
    cik = _normalize_cik(payload.get("cik"))
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        return ()
    forms = recent.get("form")
    accessions = recent.get("accessionNumber")
    filing_dates = recent.get("filingDate")
    acceptance_times = recent.get("acceptanceDateTime")
    primary_documents = recent.get("primaryDocument")
    arrays = (forms, accessions, filing_dates, acceptance_times, primary_documents)
    if not all(isinstance(item, list) for item in arrays):
        return ()
    lengths = {len(item) for item in arrays if isinstance(item, list)}
    if len(lengths) != 1:
        raise ValueError("SEC submissions financing arrays do not align")

    output: list[FinancingFiling] = []
    assert isinstance(forms, list)
    assert isinstance(accessions, list)
    assert isinstance(filing_dates, list)
    assert isinstance(acceptance_times, list)
    assert isinstance(primary_documents, list)
    for form, accession, filing_date, accepted, primary_document in zip(
        forms,
        accessions,
        filing_dates,
        acceptance_times,
        primary_documents,
        strict=True,
    ):
        normalized_form = str(form).strip().upper()
        if normalized_form not in TRACKED_FINANCING_FORMS:
            continue
        filed = date.fromisoformat(str(filing_date))
        accepted_at = _acceptance_datetime(accepted, filed)
        if accepted_at > as_of:
            continue
        accession_text = str(accession).strip()
        document = str(primary_document).strip()
        if not accession_text or not document:
            continue
        category: str
        if normalized_form.startswith("S-3"):
            category = "SHELF"
        elif normalized_form.startswith("424B"):
            category = "PROSPECTUS_SUPPLEMENT"
        else:
            category = "OTHER_FINANCING_FILING"
        cik_directory = str(int(cik))
        accession_directory = accession_text.replace("-", "")
        filing_url = (
            "https://www.sec.gov/Archives/edgar/data/"
            f"{cik_directory}/{accession_directory}/{document}"
        )
        output.append(
            FinancingFiling(
                issuer_id=issuer_id,
                cik=cik,
                accession=accession_text,
                form=normalized_form,
                filing_date=filed,
                accepted_at=accepted_at,
                primary_document=document,
                filing_url=filing_url,
                category=category,
            )
        )
    return tuple(sorted(output, key=lambda item: (item.accepted_at, item.accession)))


def extract_financing_disclosures(
    text: str,
    *,
    filing: FinancingFiling,
    evidence_id: UUID,
) -> tuple[FinancingDisclosureObservation, ...]:
    """Extract explicit ATM/shelf/offering statements without inferring status.

    Extracted observations are evidence candidates, not normalized active
    facilities. A reviewer-confirmed ``FinancingFacility`` is required before
    these observations may influence financing-risk inputs.
    """

    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ()
    observations: list[FinancingDisclosureObservation] = []
    for sentence in _SENTENCE_RE.split(cleaned):
        lower = sentence.lower()
        kind: str | None = None
        if any(
            phrase in lower
            for phrase in (
                "at-the-market",
                "at the market offering",
                "sales agreement",
                "equity distribution agreement",
            )
        ):
            kind = "ATM"
        elif "shelf registration" in lower or "shelf prospectus" in lower:
            kind = "SHELF"
        elif any(
            phrase in lower
            for phrase in (
                "public offering",
                "registered direct offering",
                "underwritten offering",
            )
        ):
            kind = "OFFERING"
        if kind is None:
            continue
        amounts = [_money_decimal(match) for match in _MONEY_RE.finditer(sentence)]
        amounts = [value for value in amounts if value is not None]
        capacity = max(amounts) if amounts else None
        observations.append(
            FinancingDisclosureObservation(
                issuer_id=filing.issuer_id,
                accession=filing.accession,
                kind=kind,
                statement=sentence[:2000],
                capacity_usd=capacity,
                used_usd=None,
                evidence_id=evidence_id,
                known_at=filing.accepted_at,
            )
        )
    return tuple(observations)


def _financial_fact_from_observation(
    *,
    issuer_id: str,
    taxonomy: str,
    concept: str,
    unit: str,
    observation: dict[str, Any],
    as_of: datetime,
    default_evidence_id: UUID,
    available_map: dict[str, datetime],
    evidence_map: dict[str, UUID],
) -> FinancialFact | None:
    accession = str(observation.get("accn") or "").strip()
    form = str(observation.get("form") or "").strip()
    filed_text = str(observation.get("filed") or "").strip()
    if not accession or not form or not filed_text:
        return None
    try:
        filed_date = date.fromisoformat(filed_text)
    except ValueError:
        return None
    filed_at = datetime.combine(filed_date, time.min, tzinfo=UTC)
    exact_available = available_map.get(accession)
    if exact_available is not None:
        _require_aware(exact_available, f"accession_available_at[{accession}]")
        available_at = exact_available.astimezone(UTC)
    else:
        available_at = datetime.combine(filed_date, time.max, tzinfo=UTC)
    if available_at > as_of:
        return None

    raw_value = observation.get("val")
    try:
        value = Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None

    start = _optional_date(observation.get("start"))
    end = _optional_date(observation.get("end"))
    if end is None:
        return None
    instant = end if start is None else None
    period_end = end if start is not None else None
    if end > as_of.date():
        return None
    fiscal_year = _optional_int(observation.get("fy"))
    fiscal_period = _optional_text(observation.get("fp"))
    frame = _optional_text(observation.get("frame"))
    evidence_id = evidence_map.get(accession, default_evidence_id)
    identity = "|".join(
        (
            issuer_id,
            taxonomy,
            concept,
            unit,
            accession,
            str(start),
            str(end),
            str(value),
        )
    )
    return FinancialFact(
        id=uuid5(NAMESPACE_URL, identity),
        issuer_id=issuer_id,
        taxonomy=taxonomy,
        concept=concept,
        value=value,
        unit=unit,
        period_start=start,
        period_end=period_end,
        instant=instant,
        form=form,
        accession=accession,
        filed_at=filed_at,
        source_available_at=available_at,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        frame=frame,
        source_evidence_id=evidence_id,
    )


def _fact_sort_key(fact: FinancialFact) -> tuple[datetime, str, str, str]:
    return fact.source_available_at, fact.accession, fact.taxonomy, fact.concept


def _money_decimal(match: re.Match[str]) -> Decimal | None:
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    scale = (match.group(2) or "").lower()
    if scale == "thousand":
        value *= Decimal("1000")
    elif scale == "million":
        value *= Decimal("1000000")
    elif scale == "billion":
        value *= Decimal("1000000000")
    return value


def _acceptance_datetime(value: object, filed: date) -> datetime:
    if value:
        text = str(value).strip()
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
            if len(text) == 14 and text.isdigit():
                return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.combine(filed, time.max, tzinfo=UTC)


def _json_object(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid SEC JSON payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("SEC JSON payload must be an object")
    return payload


def _normalize_cik(value: object) -> str:
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10:
        raise ValueError(f"invalid CIK: {value!r}")
    return text.zfill(10)


def _optional_date(value: object) -> date | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _optional_int(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
