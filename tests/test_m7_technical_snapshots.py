"""Regressions for the real, live-price-dependent technical snapshot script.

Network access is always mocked - see scripts/m7_build_technical_snapshots.py
for why this script is not exercised live by CI.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "m7_technical_snapshots", ROOT / "scripts/m7_build_technical_snapshots.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

from boe.historical_validation import HistoricalEvent  # noqa: E402
from boe.market import MarketBar, MarketSeries  # noqa: E402


def _synthetic_series(symbol: str, start: date, end: date, *, base_price: Decimal) -> MarketSeries:
    bars = []
    current = start
    price = base_price
    while current <= end:
        bars.append(
            MarketBar(
                symbol=symbol,
                session_date=current,
                open=price,
                high=price + 1,
                low=max(price - 1, Decimal("0.01")),
                close=price,
                adjusted_close=price,
                volume=100_000,
            )
        )
        current += timedelta(days=1)
        price += Decimal("0.01")  # gentle, non-round drift - never a split-like ratio
    stamp = datetime.now(UTC)
    return MarketSeries(
        symbol=symbol,
        provider="TEST_SYNTHETIC",
        bars=tuple(bars),
        retrieved_at=stamp,
        available_at=stamp,
        provider_adjusted=False,
        adjustment_version="TEST-1",
        adjustment_as_of=start,
        raw_blob_sha256="0" * 64,
        license_audit_provider="TEST_SYNTHETIC",
    )


def _fake_fetch(symbol, events, **_kwargs):
    latest_t30 = max(e.event_at for e in events) - timedelta(days=module.SNAPSHOT_LOOKBACK_DAYS)
    earliest_t30 = min(e.event_at for e in events) - timedelta(days=module.SNAPSHOT_LOOKBACK_DAYS)
    start = (earliest_t30 - timedelta(days=module.FETCH_WINDOW_DAYS)).date()
    end = latest_t30.date()
    return _synthetic_series(symbol, start, end, base_price=Decimal("50"))


def test_split_boundary_dates_finds_a_real_ratio_step() -> None:
    d1, d2, d3 = date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)
    raw = {d1: Decimal("100"), d2: Decimal("50"), d3: Decimal("51")}
    # A 2-for-1 split effective on d2: split-adjusted halves everything
    # before it, so the ratio steps from 0.5 to 1.0 at d2.
    split_adjusted = {d1: Decimal("50"), d2: Decimal("50"), d3: Decimal("51")}
    boundaries = module._split_boundary_dates(raw, split_adjusted)
    assert boundaries == (d2,)


def test_split_boundary_dates_finds_nothing_when_series_agree() -> None:
    d1, d2 = date(2024, 1, 1), date(2024, 1, 2)
    raw = {d1: Decimal("100"), d2: Decimal("140")}
    split_adjusted = {d1: Decimal("100"), d2: Decimal("140")}
    assert module._split_boundary_dates(raw, split_adjusted) == ()


def test_refuses_without_a_frozen_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "cohort-manifest.json")
    with pytest.raises(ValueError, match="not frozen yet"):
        module.build()


def test_build_computes_every_real_event_against_synthetic_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "credentials_from_env", lambda: ("key", "secret", "url"))
    monkeypatch.setattr(module, "_fetch", _fake_fetch)
    monkeypatch.setattr(
        module,
        "fetch_split_adjusted_closes",
        lambda symbol, *, start, end, **_kw: {
            bar.session_date: bar.close for bar in _fake_fetch(symbol, _events_for(symbol)).bars
        },
    )

    status = module.build()

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["event_count"] == len(manifest["events"])
    assert status["snapshot_count"] == len(manifest["events"])
    assert status["insufficient_history_count"] == 0
    assert status["fetch_failure_count"] == 0
    assert status["possible_split_count"] == 0
    for snapshot in status["snapshots"]:
        assert 0 <= snapshot["technical_factor_points"] <= snapshot["technical_factor_max_points"]


def _events_for(symbol: str) -> list[HistoricalEvent]:
    """Reconstructs what build() would have passed to _fetch() for this
    symbol, so the fake fetchers below produce a series with the same
    window boundaries build() itself computes."""
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    events = [HistoricalEvent.model_validate(e) for e in manifest["events"]]
    if symbol == module.BENCHMARK_SYMBOL:
        return events
    return [e for e in events if e.ticker == symbol]


def test_a_real_split_boundary_excludes_only_the_affected_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "credentials_from_env", lambda: ("key", "secret", "url"))
    monkeypatch.setattr(module, "_fetch", _fake_fetch)

    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    target_ticker = manifest["events"][0]["ticker"]

    def fake_split_closes(symbol, *, start, end, **_kw):
        raw_series = _fake_fetch(symbol, _events_for(symbol))
        closes = {bar.session_date: bar.close for bar in raw_series.bars}
        if symbol == target_ticker and closes:
            # Inject a real-looking 2-for-1 boundary partway through.
            dates = sorted(closes)
            midpoint = dates[len(dates) // 2]
            for d in dates:
                if d < midpoint:
                    closes[d] = closes[d] / 2
        return closes

    monkeypatch.setattr(module, "fetch_split_adjusted_closes", fake_split_closes)

    status = module.build()

    excluded_tickers = {r["ticker"] for r in status["possible_splits"]}
    assert target_ticker in excluded_tickers
    assert status["possible_split_count"] >= 1
    assert status["possible_split_count"] < status["event_count"]


def test_committed_technical_snapshots_file_is_structurally_current() -> None:
    """Real committed artifact regression: does not re-fetch live data, but
    checks the last real run is still consistent with the frozen cohort and
    accounts for every event exactly once."""
    status = json.loads(module.OUTPUT_PATH.read_bytes())
    manifest = json.loads((ROOT / "validation/m7/cohort-manifest.json").read_bytes())
    assert status["cohort_sha256"] == manifest["cohort_sha256"]
    assert status["event_count"] == len(manifest["events"])
    total = (
        status["snapshot_count"]
        + status["insufficient_history_count"]
        + status["fetch_failure_count"]
        + status["possible_split_count"]
    )
    assert total == status["event_count"]
    seen = {s["event_id"] for s in status["snapshots"]}
    seen |= {r["event_id"] for r in status["insufficient_history"]}
    seen |= {r["event_id"] for r in status["fetch_failures"]}
    seen |= {r["event_id"] for r in status["possible_splits"]}
    assert seen == {e["event_id"] for e in manifest["events"]}
