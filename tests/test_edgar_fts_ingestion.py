"""Regressions for the EDGAR full-text search adapter.

Fixture payloads below are trimmed but structurally real - shaped from a
live efts.sec.gov query run during development (2026-09-18), not invented.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from boe.ingestion.edgar_fts import EdgarFullTextSearchAdapter, FilingHit
from boe.ingestion.http import PublicDataClient

REAL_SHAPED_RESPONSE = {
    "took": 266,
    "timed_out": False,
    "hits": {
        "total": {"value": 2, "relation": "eq"},
        "hits": [
            {
                "_id": "0001104659-26-100071:capr-20260824xex99d1.htm",
                "_source": {
                    "ciks": ["0001133869"],
                    "display_names": ["Capricor Therapeutics, Inc.  (CAPR)  (CIK 0001133869)"],
                    "form": "8-K",
                    "file_date": "2026-08-24",
                    "sics": ["8731"],
                },
            },
            {
                "_id": "0001743881-26-000026:bbio-20260630xex991.htm",
                "_source": {
                    "ciks": ["0001743881"],
                    "display_names": ["BridgeBio Pharma, Inc.  (BBIO)  (CIK 0001743881)"],
                    "form": "8-K",
                    "file_date": "2026-08-10",
                    "sics": ["2836"],
                },
            },
        ],
    },
}


def _client(handler) -> PublicDataClient:
    return PublicDataClient("BOE test test@example.com", transport=httpx.MockTransport(handler))


def test_search_url_quotes_the_phrase_and_sets_date_range():
    url = EdgarFullTextSearchAdapter.search_url(
        "PDUFA", forms="8-K", start_date=date(2026, 7, 1), end_date=date(2026, 9, 18)
    )
    assert url.startswith("https://efts.sec.gov/LATEST/search-index?q=")
    assert "%22PDUFA%22" in url
    assert "forms=8-K" in url
    assert "startdt=2026-07-01" in url
    assert "enddt=2026-09-18" in url


def test_search_url_includes_from_offset_only_when_nonzero():
    base = EdgarFullTextSearchAdapter.search_url(
        "PDUFA", start_date=date(2026, 7, 1), end_date=date(2026, 9, 18)
    )
    assert "&from=" not in base
    paged = EdgarFullTextSearchAdapter.search_url(
        "PDUFA", start_date=date(2026, 7, 1), end_date=date(2026, 9, 18), from_=100
    )
    assert paged.endswith("&from=100")


def test_search_url_rejects_bad_range_and_empty_phrase():
    with pytest.raises(ValueError, match="phrase is required"):
        EdgarFullTextSearchAdapter.search_url(
            "  ", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)
        )
    with pytest.raises(ValueError, match="end_date cannot be before"):
        EdgarFullTextSearchAdapter.search_url(
            "PDUFA", start_date=date(2026, 1, 2), end_date=date(2026, 1, 1)
        )


def test_parse_results_extracts_real_shaped_hits():
    total, hits = EdgarFullTextSearchAdapter.parse_results(
        __import__("json").dumps(REAL_SHAPED_RESPONSE)
    )
    assert total == 2
    assert len(hits) == 2
    capr, bbio = hits
    assert capr == FilingHit(
        accession_number="0001104659-26-100071",
        cik="0001133869",
        display_name="Capricor Therapeutics, Inc.  (CAPR)  (CIK 0001133869)",
        ticker="CAPR",
        form="8-K",
        file_date=date(2026, 8, 24),
        sics=("8731",),
        primary_document="capr-20260824xex99d1.htm",
    )
    assert bbio.ticker == "BBIO"
    assert bbio.sics == ("2836",)


def test_filing_hit_document_url_matches_real_edgar_archive_layout():
    hit = FilingHit(
        accession_number="0001104659-26-100071",
        cik="0001133869",
        display_name="Capricor Therapeutics, Inc.  (CAPR)  (CIK 0001133869)",
        ticker="CAPR",
        form="8-K",
        file_date=date(2026, 8, 24),
        sics=("8731",),
        primary_document="capr-20260824xex99d1.htm",
    )
    assert hit.document_url == (
        "https://www.sec.gov/Archives/edgar/data/1133869/"
        "000110465926100071/capr-20260824xex99d1.htm"
    )


def test_parse_results_skips_malformed_hits():
    malformed = {"hits": {"hits": [{"_id": "no-colon-here", "_source": {}}, {"_source": {}}]}}
    assert EdgarFullTextSearchAdapter.parse_results(__import__("json").dumps(malformed)) == (0, ())


def test_parse_results_requires_an_object():
    with pytest.raises(ValueError, match="must be an object"):
        EdgarFullTextSearchAdapter.parse_results("[]")


def test_search_fetches_and_parses(monkeypatch: pytest.MonkeyPatch):
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://efts.sec.gov/LATEST/search-index")
        return httpx.Response(200, content=json.dumps(REAL_SHAPED_RESPONSE), request=request)

    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with _client(handler) as client:
        adapter = EdgarFullTextSearchAdapter(client)
        payload, total, hits = adapter.search(
            "PDUFA", start_date=date(2026, 7, 1), end_date=date(2026, 9, 18)
        )

    assert payload.status_code == 200
    assert total == 2
    assert len(hits) == 2
