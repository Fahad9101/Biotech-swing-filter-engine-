"""ClinicalTrials.gov API v2 adapter for point-in-time scientific evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote_plus

from boe.ingestion.http import FetchedPayload, PublicDataClient

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"


@dataclass(frozen=True, slots=True)
class ClinicalTrialRecord:
    nct_id: str
    brief_title: str
    official_title: str | None
    phases: tuple[str, ...]
    overall_status: str | None
    conditions: tuple[str, ...]
    interventions: tuple[str, ...]
    enrollment: int | None
    allocation: str | None
    masking: str | None
    intervention_model: str | None
    primary_endpoints: tuple[str, ...]
    secondary_endpoints: tuple[str, ...]
    primary_completion_date: date | None
    study_type: str | None


class ClinicalTrialsAdapter:
    def __init__(self, client: PublicDataClient) -> None:
        self._client = client

    @staticmethod
    def study_url(nct_id: str) -> str:
        normalized = nct_id.strip().upper()
        if not normalized.startswith("NCT") or not normalized[3:].isdigit():
            raise ValueError("invalid NCT identifier")
        return f"{CTGOV_API}/{normalized}"

    @staticmethod
    def search_url(query: str, page_size: int = 100) -> str:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be within 1..1000")
        return f"{CTGOV_API}?query.term={quote_plus(query)}&pageSize={page_size}&format=json"

    def fetch_study(self, nct_id: str) -> tuple[FetchedPayload, ClinicalTrialRecord]:
        payload = self._client.fetch(self.study_url(nct_id))
        return payload, self.parse_study(payload.content)

    @classmethod
    def parse_study(cls, content: bytes | str) -> ClinicalTrialRecord:
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("ClinicalTrials.gov response must be an object")
        protocol = cls._dict(raw.get("protocolSection"))
        identification = cls._dict(protocol.get("identificationModule"))
        status = cls._dict(protocol.get("statusModule"))
        design = cls._dict(protocol.get("designModule"))
        conditions = cls._dict(protocol.get("conditionsModule"))
        arms = cls._dict(protocol.get("armsInterventionsModule"))
        outcomes = cls._dict(protocol.get("outcomesModule"))

        nct_id = str(identification.get("nctId", "")).strip().upper()
        if not nct_id:
            raise ValueError("ClinicalTrials.gov study lacks nctId")
        brief_title = str(identification.get("briefTitle", "")).strip()
        if not brief_title:
            raise ValueError("ClinicalTrials.gov study lacks briefTitle")

        enrollment_info = cls._dict(design.get("enrollmentInfo"))
        enrollment_raw = enrollment_info.get("count")
        enrollment = int(enrollment_raw) if isinstance(enrollment_raw, (int, float)) else None
        design_info = cls._dict(design.get("designInfo"))
        masking_info = cls._dict(design_info.get("maskingInfo"))

        primary_completion = cls._dict(status.get("primaryCompletionDateStruct"))
        completion_date = cls._parse_date(primary_completion.get("date"))

        return ClinicalTrialRecord(
            nct_id=nct_id,
            brief_title=brief_title,
            official_title=cls._optional_text(identification.get("officialTitle")),
            phases=cls._strings(design.get("phases")),
            overall_status=cls._optional_text(status.get("overallStatus")),
            conditions=cls._strings(conditions.get("conditions")),
            interventions=tuple(
                str(item.get("name", "")).strip()
                for item in cls._dicts(arms.get("interventions"))
                if str(item.get("name", "")).strip()
            ),
            enrollment=enrollment,
            allocation=cls._optional_text(design_info.get("allocation")),
            masking=cls._optional_text(masking_info.get("masking")),
            intervention_model=cls._optional_text(design_info.get("interventionModel")),
            primary_endpoints=tuple(
                str(item.get("measure", "")).strip()
                for item in cls._dicts(outcomes.get("primaryOutcomes"))
                if str(item.get("measure", "")).strip()
            ),
            secondary_endpoints=tuple(
                str(item.get("measure", "")).strip()
                for item in cls._dicts(outcomes.get("secondaryOutcomes"))
                if str(item.get("measure", "")).strip()
            ),
            primary_completion_date=completion_date,
            study_type=cls._optional_text(design.get("studyType")),
        )

    @staticmethod
    def _dict(value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _dicts(cls, value: object) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        return tuple(cls._dict(item) for item in value if isinstance(item, dict))

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(str(item).strip() for item in value if str(item).strip())

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        for candidate in (text, f"{text}-01", f"{text}-01-01"):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue
        return None
