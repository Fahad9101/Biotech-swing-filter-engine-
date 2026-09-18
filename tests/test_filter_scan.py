"""End-to-end regressions for the filter_scan orchestrator.

EDGAR full-text search and SEC XBRL go through the injected PublicDataClient
(mocked). Alpaca's fetch_live_series is monkeypatched directly, since
boe.ingestion.alpaca builds its own httpx.Client internally rather than
accepting one - matching how the rest of this module's tests avoid live
network calls.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from boe.market import MarketBar, MarketSeries

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("filter_scan", ROOT / "scripts/filter_scan.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from boe.ingestion.http import PublicDataClient  # noqa: E402

AS_OF = datetime(2026, 9, 18, tzinfo=UTC)

SEARCH_RESPONSE = {
    "hits": {
        "total": {"value": 1},
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
            }
        ],
    }
}
FILING_TEXT = (
    "<html><body>New PDUFA target action date of November 22, 2026 follows "
    "submission of additional data.</body></html>"
)


def _submissions() -> dict:
    return {"filings": {"recent": {"form": ["10-K", "10-Q"]}}}


def _companyfacts() -> dict:
    gaap = {
        "CashAndCashEquivalentsAtCarryingValue": {
            "units": {
                "USD": [
                    {
                        "val": 10_000_000,
                        "end": "2026-06-30",
                        "filed": "2026-08-01",
                        "accn": "0001-26-1",
                        "form": "10-Q",
                    }
                ]
            }
        },
        "NetCashProvidedByUsedInOperatingActivities": {
            "units": {
                "USD": [
                    {
                        "val": -2_000_000,
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "filed": "2026-05-01",
                        "accn": "0001-26-q1",
                        "form": "10-Q",
                        "fy": 2026,
                        "fp": "Q1",
                    },
                    {
                        "val": -4_000_000,
                        "start": "2026-01-01",
                        "end": "2026-06-30",
                        "filed": "2026-08-01",
                        "accn": "0001-26-q2",
                        "form": "10-Q",
                        "fy": 2026,
                        "fp": "Q2",
                    },
                ]
            }
        },
    }
    return {"facts": {"us-gaap": gaap}}


def _client() -> PublicDataClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "efts.sec.gov" in url:
            return httpx.Response(200, content=json.dumps(SEARCH_RESPONSE), request=request)
        if "capr-ex99d1.htm" in url:
            return httpx.Response(200, content=FILING_TEXT, request=request)
        if "submissions" in url:
            return httpx.Response(200, json=_submissions(), request=request)
        if "companyfacts" in url:
            return httpx.Response(200, json=_companyfacts(), request=request)
        raise AssertionError(f"unexpected URL in test: {url}")

    return PublicDataClient("BOE test test@example.com", transport=httpx.MockTransport(handler))


def _fake_series(symbol: str, *, base: Decimal) -> MarketSeries:
    sessions: list[date] = []
    current = AS_OF.date()
    while len(sessions) < 90:
        if current.weekday() < 5:
            sessions.append(current)
        current = date.fromordinal(current.toordinal() - 1)
    sessions.reverse()
    bars = tuple(
        MarketBar(
            symbol=symbol,
            session_date=session,
            open=base + Decimal("0.05") * index,
            high=base + Decimal("0.05") * index + Decimal("0.2"),
            low=base + Decimal("0.05") * index - Decimal("0.2"),
            close=base + Decimal("0.05") * index,
            adjusted_close=base + Decimal("0.05") * index,
            volume=1_000_000,
        )
        for index, session in enumerate(sessions)
    )
    return MarketSeries(
        symbol=symbol,
        provider="TEST",
        bars=bars,
        retrieved_at=AS_OF,
        available_at=AS_OF,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=AS_OF.date(),
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST",
    )


def test_build_produces_a_real_watchlist_entry_from_discovery_through_scoring(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    monkeypatch.setattr(
        module,
        "fetch_live_series",
        lambda symbol, **_: _fake_series(symbol, base=Decimal("10.00")),
    )

    with _client() as client:
        status = module.build(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 18),
            as_of=AS_OF,
            client=client,
            api_key_id="k",
            api_secret_key="s",
            data_url="https://data.alpaca.markets",
        )

    assert status["role"] == "SCREENING_FACTS_NOT_A_RECOMMENDATION"
    assert status["watchlist_count"] == 1
    entry = status["watchlist"][0]
    assert entry["ticker"] == "CAPR"
    assert entry["catalyst_type"] == "REG_DECISION"
    assert entry["window_start"] == "2026-11-22"
    assert entry["cash_dilution_facts"]["debt_free_confirmed_by_absence"] is True
    assert entry["technical_facts"] is not None
    assert (
        entry["source_url"].endswith("capr-20260824xex99d1.htm")
        or "capr-ex99d1.htm" in entry["source_url"]
    )
    assert status["excluded_foreign_issuer"] == []


def test_build_filters_out_candidates_whose_window_already_ended(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    monkeypatch.setattr(
        module,
        "fetch_live_series",
        lambda symbol, **_: _fake_series(symbol, base=Decimal("10.00")),
    )
    past_tense_text = (
        "<html><body>The Company reported positive topline Phase 2a results "
        "on August 12, 2026.</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "efts.sec.gov" in url:
            return httpx.Response(200, content=json.dumps(SEARCH_RESPONSE), request=request)
        if "capr-ex99d1.htm" in url:
            return httpx.Response(200, content=past_tense_text, request=request)
        raise AssertionError(f"unexpected URL in test: {url}")

    with PublicDataClient(
        "BOE test test@example.com", transport=httpx.MockTransport(handler)
    ) as client:
        status = module.build(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 18),
            as_of=AS_OF,
            client=client,
            api_key_id="k",
            api_secret_key="s",
            data_url="https://data.alpaca.markets",
        )

    assert status["watchlist_count"] == 0
    assert len(status["already_past"]) == 1
    assert status["already_past"][0]["window_end"] == "2026-08-12"


def test_build_returns_empty_watchlist_when_nothing_is_discovered(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"hits": {"total": {"value": 0}, "hits": []}}),
            request=request,
        )

    with PublicDataClient(
        "BOE test test@example.com", transport=httpx.MockTransport(handler)
    ) as client:
        status = module.build(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 9, 18),
            as_of=AS_OF,
            client=client,
            api_key_id="k",
            api_secret_key="s",
            data_url="https://data.alpaca.markets",
        )

    assert status["watchlist_count"] == 0
    assert status["watchlist"] == []
