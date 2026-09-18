"""Ties EdgarFullTextSearchAdapter + extraction together: real, live
forward-catalyst discovery across a set of trigger phrases and a real
pharma/biotech SIC-code filter, deduplicated by issuer.
"""

from __future__ import annotations

from datetime import date

from boe.filter.extraction import DiscoveredCatalyst, extract_candidates
from boe.ingestion.edgar_fts import EdgarFullTextSearchAdapter, FilingHit
from boe.ingestion.http import PublicDataClient

BIOTECH_PHARMA_SICS = frozenset({"2834", "2836", "8731"})
DEFAULT_SEARCH_PHRASES: tuple[str, ...] = (
    "PDUFA",
    "target action date",
    "topline",
    "readout",
)
PAGE_SIZE = 100
MAX_HITS_PER_PHRASE = 500


def _is_biotech_pharma(hit: FilingHit) -> bool:
    return bool(set(hit.sics) & BIOTECH_PHARMA_SICS)


def discover_filing_hits(
    client: PublicDataClient,
    *,
    phrases: tuple[str, ...] = DEFAULT_SEARCH_PHRASES,
    forms: str = "8-K",
    start_date: date,
    end_date: date,
) -> tuple[FilingHit, ...]:
    """Real EDGAR full-text search across `phrases`, paged up to
    MAX_HITS_PER_PHRASE per phrase, deduplicated by (accession_number,
    primary_document) and filtered to real pharma/biotech SIC codes."""
    adapter = EdgarFullTextSearchAdapter(client)
    seen: dict[tuple[str, str], FilingHit] = {}
    for phrase in phrases:
        offset = 0
        while offset < MAX_HITS_PER_PHRASE:
            _, total, hits = adapter.search(
                phrase, forms=forms, start_date=start_date, end_date=end_date, from_=offset
            )
            for hit in hits:
                if not _is_biotech_pharma(hit) or hit.ticker is None:
                    continue
                seen.setdefault((hit.accession_number, hit.primary_document), hit)
            offset += PAGE_SIZE
            if offset >= total or not hits:
                break
    return tuple(seen.values())


def discover_candidates_from_hit(
    client: PublicDataClient,
    hit: FilingHit,
) -> tuple[DiscoveredCatalyst, ...]:
    """Fetches one real filing exhibit and extracts real forward-catalyst
    candidates from it. Requires hit.ticker to already be resolved."""
    if hit.ticker is None:
        raise ValueError("filing hit has no resolved ticker")
    payload = client.fetch(hit.document_url)
    return extract_candidates(
        ticker=hit.ticker,
        cik=hit.cik,
        company=hit.display_name,
        document_text=payload.content.decode("utf-8", errors="replace"),
        source_url=hit.document_url,
        filing_date=hit.file_date,
    )
