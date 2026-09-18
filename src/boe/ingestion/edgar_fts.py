"""SEC EDGAR full-text search adapter.

Used to discover real, company-self-disclosed forward-looking catalyst
language (e.g. "PDUFA target action date of November 27, 2026") in recent
SEC filings, rather than relying on any third-party catalyst calendar (no
such official, free, forward-looking FDA calendar exists - PDUFA dates are
disclosed by companies themselves, not published by the FDA). This is the
same EDGAR full-text-search technique already used elsewhere in this
project to find a company's own self-declaring language before reading
filings one by one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import quote

from boe.ingestion.http import FetchedPayload, PublicDataClient

EDGAR_FTS_API = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


@dataclass(frozen=True, slots=True)
class FilingHit:
    accession_number: str
    cik: str
    display_name: str
    ticker: str | None
    form: str
    file_date: date | None
    sics: tuple[str, ...]
    primary_document: str

    @property
    def document_url(self) -> str:
        cik_no_zeros = str(int(self.cik))
        accession_no_dashes = self.accession_number.replace("-", "")
        return f"{EDGAR_ARCHIVES}/{cik_no_zeros}/{accession_no_dashes}/{self.primary_document}"


class EdgarFullTextSearchAdapter:
    def __init__(self, client: PublicDataClient) -> None:
        self._client = client

    @staticmethod
    def search_url(
        phrase: str,
        *,
        forms: str = "8-K",
        start_date: date,
        end_date: date,
        from_: int = 0,
    ) -> str:
        if not phrase.strip():
            raise ValueError("phrase is required")
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
        if from_ < 0:
            raise ValueError("from_ cannot be negative")
        query = quote(f'"{phrase.strip()}"')
        url = (
            f"{EDGAR_FTS_API}?q={query}&forms={forms}"
            f"&startdt={start_date.isoformat()}&enddt={end_date.isoformat()}"
        )
        return url if from_ == 0 else f"{url}&from={from_}"

    def search(
        self,
        phrase: str,
        *,
        forms: str = "8-K",
        start_date: date,
        end_date: date,
        from_: int = 0,
    ) -> tuple[FetchedPayload, int, tuple[FilingHit, ...]]:
        payload = self._client.fetch(
            self.search_url(
                phrase, forms=forms, start_date=start_date, end_date=end_date, from_=from_
            )
        )
        total, hits = self.parse_results(payload.content)
        return payload, total, hits

    @classmethod
    def parse_results(cls, content: bytes | str) -> tuple[int, tuple[FilingHit, ...]]:
        raw = json.loads(content)
        if not isinstance(raw, dict):
            raise ValueError("EDGAR full-text search response must be an object")
        hits_block = raw.get("hits")
        total_block = hits_block.get("total") if isinstance(hits_block, dict) else None
        total = int(total_block["value"]) if isinstance(total_block, dict) else 0
        hits = hits_block.get("hits") if isinstance(hits_block, dict) else None
        if not isinstance(hits, list):
            return total, ()
        results: list[FilingHit] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            parsed = cls._parse_hit(hit)
            if parsed is not None:
                results.append(parsed)
        return total, tuple(results)

    @classmethod
    def _parse_hit(cls, hit: dict[str, Any]) -> FilingHit | None:
        hit_id = str(hit.get("_id", ""))
        source = hit.get("_source")
        if ":" not in hit_id or not isinstance(source, dict):
            return None
        accession_number, _, primary_document = hit_id.partition(":")
        ciks = source.get("ciks")
        cik = str(ciks[0]).strip() if isinstance(ciks, list) and ciks else ""
        if not cik or not primary_document:
            return None
        display_names = source.get("display_names")
        display_name = (
            str(display_names[0]).strip()
            if isinstance(display_names, list) and display_names
            else ""
        )
        ticker = cls._ticker_from_display_name(display_name)
        sics_raw = source.get("sics")
        sics = tuple(str(s) for s in sics_raw) if isinstance(sics_raw, list) else ()
        return FilingHit(
            accession_number=accession_number,
            cik=cik,
            display_name=display_name,
            ticker=ticker,
            form=str(source.get("form", "")).strip(),
            file_date=cls._parse_date(source.get("file_date")),
            sics=sics,
            primary_document=primary_document,
        )

    @staticmethod
    def _ticker_from_display_name(display_name: str) -> str | None:
        # EDGAR FTS display_names look like "Cogent Biosciences, Inc.  (COGT)  (CIK 0001622229)"
        for group in re.findall(r"\(([^()]*)\)", display_name):
            candidate = group.strip()
            if candidate and not candidate.startswith("CIK"):
                return candidate.split(",")[0].strip() or None
        return None

    @staticmethod
    def _parse_date(value: object) -> date | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
