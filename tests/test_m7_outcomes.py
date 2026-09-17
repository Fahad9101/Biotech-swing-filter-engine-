"""Regressions for the real, live-price-dependent outcome-reconstruction script.

Network access is always mocked - see docstring in
scripts/m7_build_outcomes.py for why this script is not exercised live by CI.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("m7_outcomes", ROOT / "scripts/m7_build_outcomes.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from boe.market import MarketBar, MarketSeries  # noqa: E402


def _synthetic_series(symbol: str, events: list, *, retrieved_at: datetime) -> MarketSeries:
    start = min(e.event_at.date() for e in events) - timedelta(days=module.PRE_EVENT_BUFFER_DAYS)
    end = max(e.event_at.date() for e in events) + timedelta(days=module.POST_EVENT_BUFFER_DAYS)
    bars = []
    current = start
    price = Decimal("100")
    while current <= end:
        bars.append(
            MarketBar(
                symbol=symbol,
                session_date=current,
                open=price,
                high=price + 1,
                low=price - 1,
                close=price,
                adjusted_close=price,
                volume=1000,
            )
        )
        current += timedelta(days=1)
        price += Decimal("1")
    return MarketSeries(
        symbol=symbol,
        provider="TEST_SYNTHETIC",
        bars=tuple(bars),
        retrieved_at=retrieved_at,
        available_at=retrieved_at,
        provider_adjusted=True,
        adjustment_version="TEST-1",
        adjustment_as_of=retrieved_at.date(),
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST_SYNTHETIC",
    )


def test_build_refuses_without_a_frozen_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_build_computes_every_real_event_against_synthetic_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        module, "credentials_from_env", lambda: ("key", "secret", "https://data.alpaca.markets")
    )

    def fake_fetch(symbol, events, **_kwargs):
        return _synthetic_series(symbol, events, retrieved_at=datetime.now(UTC))

    monkeypatch.setattr(module, "_fetch", fake_fetch)

    status = module.build()

    assert status["event_count"] == 120
    assert status["outcome_count"] == 120
    assert status["failed_count"] == 0
    assert len(status["outcomes"]) == 120
    event_ids = {o["event_id"] for o in status["outcomes"]}
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert event_ids == {e["event_id"] for e in manifest["events"]}
    assert status["cohort_sha256"] == manifest["cohort_sha256"]


def test_a_single_ticker_fetch_failure_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        module, "credentials_from_env", lambda: ("key", "secret", "https://data.alpaca.markets")
    )
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    failing_ticker = manifest["events"][0]["ticker"]
    failing_event_ids = {e["event_id"] for e in manifest["events"] if e["ticker"] == failing_ticker}

    def fake_fetch(symbol, events, **_kwargs):
        if symbol == failing_ticker:
            raise RuntimeError("simulated delisting: symbol not found")
        return _synthetic_series(symbol, events, retrieved_at=datetime.now(UTC))

    monkeypatch.setattr(module, "_fetch", fake_fetch)

    status = module.build()

    assert status["failed_count"] == len(failing_event_ids)
    assert status["outcome_count"] == 120 - len(failing_event_ids)
    failed_tickers = {f["ticker"] for f in status["failures"]}
    assert failed_tickers == {failing_ticker}
    assert all(f["stage"] == "fetch" for f in status["failures"])
    outcome_event_ids = {o["event_id"] for o in status["outcomes"]}
    assert outcome_event_ids.isdisjoint(failing_event_ids)


def test_committed_outcomes_file_is_structurally_current() -> None:
    """Real committed artifact regression: does not re-fetch live data, but
    checks the last real run is still consistent with the frozen cohort and
    reports full, unfailed coverage."""
    status = json.loads((ROOT / "validation/m7/historical-outcomes.json").read_bytes())
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    assert status["outcome_count"] == status["event_count"]
    assert status["failed_count"] == 0
    assert {o["event_id"] for o in status["outcomes"]} == {
        e["event_id"] for e in manifest["events"]
    }
    for outcome in status["outcomes"]:
        assert isinstance(outcome["severe_loss"], bool)
        assert isinstance(outcome["swing_success"], bool)
        date.fromisoformat(outcome["t0_session"])
