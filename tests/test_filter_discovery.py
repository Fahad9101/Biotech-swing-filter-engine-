"""Regressions for the discovery orchestration layer (EDGAR FTS + extraction)."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from boe.filter.discovery import discover_candidates_from_hit, discover_filing_hits
from boe.ingestion.edgar_fts import FilingHit
from boe.ingestion.http import PublicDataClient

SEARCH_RESPONSE = {
    "hits": {
        "hits": [
            {
                "_id": "0001104659-26-100071:capr-ex99d1.htm",
                "_source": {
                    "ciks": ["0001133869"],
                    "display_names": ["Capricor Therapeutics, Inc.  (CAPR)  (CIK 0001133869)"],
                    "form": "8-K",
                    "file_date": "2026-08-24",
                    "sics": ["8731"],
                },
            },
            {
                # non-biotech SIC - must be filtered out
                "_id": "0009999999-26-000001:other-ex99d1.htm",
                "_source": {
                    "ciks": ["0009999999"],
                    "display_names": ["Some Retailer, Inc.  (RTLR)  (CIK 0009999999)"],
                    "form": "8-K",
                    "file_date": "2026-08-24",
                    "sics": ["5411"],
                },
            },
        ]
    }
}

FILING_TEXT = (
    "<html><body>New PDUFA target action date of November 22, 2026 follows "
    "submission of additional data.</body></html>"
)


def _client(handler) -> PublicDataClient:
    return PublicDataClient("BOE test test@example.com", transport=httpx.MockTransport(handler))


def test_discover_filing_hits_filters_to_biotech_sics_and_dedupes(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=json.dumps(SEARCH_RESPONSE), request=request)

    with _client(handler) as client:
        hits = discover_filing_hits(
            client,
            phrases=("PDUFA", "topline"),
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 18),
        )

    assert calls == 2  # one page per phrase - total (2) fits in one page
    assert len(hits) == 1  # deduped across phrases, non-biotech filtered out
    assert hits[0].ticker == "CAPR"


def test_discover_filing_hits_pages_through_more_than_one_hundred_hits(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    requested_offsets: list[str] = []

    def _hit(n: int) -> dict:
        return {
            "_id": f"000110465926{n:06d}:capr-ex{n}.htm",
            "_source": {
                "ciks": ["0001133869"],
                "display_names": [f"Capricor Therapeutics {n}  (CAPR)  (CIK 0001133869)"],
                "form": "8-K",
                "file_date": "2026-08-24",
                "sics": ["8731"],
            },
        }

    def handler(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs, urlparse

        offset = int(parse_qs(urlparse(str(request.url)).query).get("from", ["0"])[0])
        requested_offsets.append(str(offset))
        page_size = 100 if offset == 0 else 1
        page = [_hit(offset + i) for i in range(page_size)]
        total = 101
        return httpx.Response(
            200,
            content=json.dumps({"hits": {"total": {"value": total}, "hits": page}}),
            request=request,
        )

    with _client(handler) as client:
        hits = discover_filing_hits(
            client, phrases=("PDUFA",), start_date=date(2026, 7, 1), end_date=date(2026, 9, 18)
        )

    assert requested_offsets == ["0", "100"]
    assert len(hits) == 101


def test_discover_candidates_from_hit_fetches_and_extracts_real_facts(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    hit = FilingHit(
        accession_number="0001104659-26-100071",
        cik="0001133869",
        display_name="Capricor Therapeutics, Inc.  (CAPR)  (CIK 0001133869)",
        ticker="CAPR",
        form="8-K",
        file_date=date(2026, 8, 24),
        sics=("8731",),
        primary_document="capr-ex99d1.htm",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == hit.document_url
        return httpx.Response(200, content=FILING_TEXT, request=request)

    with _client(handler) as client:
        candidates = discover_candidates_from_hit(client, hit)

    assert len(candidates) == 1
    assert candidates[0].ticker == "CAPR"
    assert candidates[0].window_start.isoformat() == "2026-11-22"


def test_discover_candidates_from_hit_requires_a_resolved_ticker():
    hit = FilingHit(
        accession_number="0001104659-26-100071",
        cik="0001133869",
        display_name="Unresolvable Display Name",
        ticker=None,
        form="8-K",
        file_date=date(2026, 8, 24),
        sics=("8731",),
        primary_document="x.htm",
    )
    with PublicDataClient(
        "BOE test test@example.com", transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as client:
        with pytest.raises(ValueError, match="no resolved ticker"):
            discover_candidates_from_hit(client, hit)
