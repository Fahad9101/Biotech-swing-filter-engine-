"""End-to-end regressions for the forward_measure orchestrator.

Alpaca's fetch is monkeypatched directly (module._fetch_full_series),
matching how tests/test_filter_scan.py avoids live network calls for
Alpaca (boe.ingestion.alpaca builds its own httpx.Client internally
rather than accepting an injected transport).
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from boe.market import MarketBar, MarketSeries

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "forward_measure", ROOT / "scripts/forward_measure.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

AS_OF = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


def _shortlist_row(ticker: str, *, close: str = "10.00", tier: int = 1) -> dict:
    return {
        "candidate_id": f"{ticker}-REG_DECISION-2026-10-01",
        "ticker": ticker,
        "company": f"{ticker} Inc.",
        "catalyst_type": "REG_DECISION",
        "window_start": "2026-10-01",
        "window_end": "2026-10-01",
        "date_precision": "EXACT_DATE",
        "tier": tier,
        "source_url": "https://www.sec.gov/example.htm",
        "technical_facts": {"close": close},
    }


def _series(symbol: str, *, start: date, end: date, base: Decimal, drift: Decimal) -> MarketSeries:
    bars = []
    session = start
    index = 0
    while session <= end:
        if session.weekday() < 5:
            close = base + drift * index
            bars.append(
                MarketBar(
                    symbol=symbol,
                    session_date=session,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    adjusted_close=close,
                    volume=1_000_000,
                )
            )
            index += 1
        session += timedelta(days=1)
    return MarketSeries(
        symbol=symbol,
        provider="TEST",
        bars=tuple(bars),
        retrieved_at=AS_OF,
        available_at=AS_OF,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=AS_OF.date(),
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST",
    )


def _watchlist_status(*, shortlist: list[dict], as_of: datetime = AS_OF) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "shortlist_definition": "SHORTLIST-1.0",
        "shortlist_parameters": {"horizon_days": 56},
        "shortlist": shortlist,
        "benchmark": {"symbol": "XBI", "close": "100.00", "session_date": as_of.date().isoformat()},
    }


def test_measure_records_new_entries_from_a_fresh_shortlist(monkeypatch: pytest.MonkeyPatch):
    status = _watchlist_status(shortlist=[_shortlist_row("AAA", close="10.00")])
    entries, added, measured = module.measure(
        watchlist_status=status,
        existing_entries=[],
        as_of=AS_OF,
        api_key_id="k",
        api_secret_key="s",
        data_url="https://data.alpaca.markets",
    )
    assert added == ["AAA-REG_DECISION-2026-10-01"]
    assert entries[0]["entry_close"] == "10.00"
    assert entries[0]["entry_xbi_close"] == "100.00"
    assert measured == 0  # nothing due yet on entry day


def test_measure_computes_a_due_checkpoint_from_real_fetched_bars(
    monkeypatch: pytest.MonkeyPatch,
):
    entry_date = date(2026, 9, 1)
    today = entry_date + timedelta(weeks=1)
    existing = [
        {
            "candidate_id": "AAA-REG_DECISION-2026-10-01",
            "ticker": "AAA",
            "company": "AAA Inc.",
            "catalyst_type": "REG_DECISION",
            "tier": 1,
            "entry_date": entry_date.isoformat(),
            "entry_close": "10.00",
            "entry_xbi_close": "100.00",
            "checkpoints": {},
        }
    ]

    def fake_fetch(symbol, *, start, end, api_key_id, api_secret_key, data_url):
        base = Decimal("10.00") if symbol == "AAA" else Decimal("100.00")
        drift = Decimal("0.50") if symbol == "AAA" else Decimal("0.10")
        return _series(symbol, start=start, end=end, base=base, drift=drift)

    monkeypatch.setattr(module, "_fetch_full_series", fake_fetch)

    status = _watchlist_status(shortlist=[], as_of=datetime.combine(today, AS_OF.timetz()))
    entries, added, measured = module.measure(
        watchlist_status=status,
        existing_entries=existing,
        as_of=datetime.combine(today, AS_OF.timetz()),
        api_key_id="k",
        api_secret_key="s",
        data_url="https://data.alpaca.markets",
    )
    assert added == []
    assert measured == 1
    checkpoint = entries[0]["checkpoints"]["1"]
    assert Decimal(checkpoint["return_pct"]) > 0
    assert "week" not in checkpoint or checkpoint["week"] == 1


def test_measure_records_a_fetch_error_instead_of_crashing(monkeypatch: pytest.MonkeyPatch):
    entry_date = date(2026, 9, 1)
    today = entry_date + timedelta(weeks=1)
    existing = [
        {
            "candidate_id": "AAA-REG_DECISION-2026-10-01",
            "ticker": "AAA",
            "company": "AAA Inc.",
            "catalyst_type": "REG_DECISION",
            "tier": 1,
            "entry_date": entry_date.isoformat(),
            "entry_close": "10.00",
            "entry_xbi_close": "100.00",
            "checkpoints": {},
        }
    ]

    def fake_fetch(symbol, *, start, end, api_key_id, api_secret_key, data_url):
        if symbol == "XBI":
            return _series(symbol, start=start, end=end, base=Decimal("100.00"), drift=Decimal("0"))
        raise ValueError("simulated Alpaca outage")

    monkeypatch.setattr(module, "_fetch_full_series", fake_fetch)

    status = _watchlist_status(shortlist=[], as_of=datetime.combine(today, AS_OF.timetz()))
    entries, added, measured = module.measure(
        watchlist_status=status,
        existing_entries=existing,
        as_of=datetime.combine(today, AS_OF.timetz()),
        api_key_id="k",
        api_secret_key="s",
        data_url="https://data.alpaca.markets",
    )
    assert measured == 0
    assert entries[0]["checkpoints"] == {}
    assert "simulated Alpaca outage" in entries[0]["measurement_errors"][0]["reason"]


def test_measure_skips_entries_when_shortlist_is_empty_and_no_checkpoints_due():
    status = _watchlist_status(shortlist=[])
    entries, added, measured = module.measure(
        watchlist_status=status,
        existing_entries=[],
        as_of=AS_OF,
        api_key_id="k",
        api_secret_key="s",
        data_url="https://data.alpaca.markets",
    )
    assert entries == []
    assert added == []
    assert measured == 0


def test_measure_never_overwrites_a_frozen_entry_on_a_rerun():
    status = _watchlist_status(shortlist=[_shortlist_row("AAA", close="999.00")])
    existing = [
        {
            "candidate_id": "AAA-REG_DECISION-2026-10-01",
            "ticker": "AAA",
            "entry_date": "2026-09-22",
            "entry_close": "10.00",
            "entry_xbi_close": "100.00",
            "checkpoints": {},
        }
    ]
    entries, added, measured = module.measure(
        watchlist_status=status,
        existing_entries=existing,
        as_of=AS_OF,
        api_key_id="k",
        api_secret_key="s",
        data_url="https://data.alpaca.markets",
    )
    assert added == []
    assert entries[0]["entry_close"] == "10.00"
