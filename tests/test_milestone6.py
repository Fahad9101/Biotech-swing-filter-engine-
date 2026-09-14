from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from boe.contracts import load_scorecard
from boe.ingestion.market import (
    PROVIDER,
    parse_stooq_bulk_file,
    parse_stooq_bulk_text,
    stooq_validation_license,
)
from boe.market import (
    RawMarketBar,
    SplitEvent,
    adjust_raw_bars_for_splits,
    point_in_time_series,
)
from boe.scoring import score_technicals
from boe.technicals import (
    PivotSupportEvidence,
    build_technical_snapshot,
    investability_market_inputs,
    technical_evidence,
    technical_score_input,
)

AS_OF = datetime(2026, 4, 23, 22, 0, tzinfo=UTC)
RULES_RAW_SHA = "11cffb776ffd6bbd943b1d23dfcf6541ab02fcbfec753f13d00a7f4acee8b569"
EVIDENCE_ID = UUID("00000000-0000-0000-0000-000000000601")


def _fixture_text(repository_root: Path, name: str) -> str:
    return (repository_root / "tests" / "fixtures" / name).read_text()


def _synthetic_stooq_text(symbol: str) -> str:
    sessions: list[date] = []
    current = date(2026, 1, 2)
    while len(sessions) < 80:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)

    lines = ["<TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>"]
    for index, session in enumerate(sessions):
        if symbol == "ABC":
            cycle = (
                Decimal("0.00"),
                Decimal("0.08"),
                Decimal("-0.05"),
                Decimal("0.12"),
                Decimal("-0.02"),
            )[index % 5]
            close = (
                Decimal("10.00") + Decimal("0.075") * index + cycle
            ).quantize(Decimal("0.01"))
            open_ = (
                close - Decimal("0.06") if index % 2 == 0 else close + Decimal("0.04")
            ).quantize(Decimal("0.01"))
            high = (max(open_, close) + Decimal("0.18")).quantize(Decimal("0.01"))
            low = (min(open_, close) - Decimal("0.16")).quantize(Decimal("0.01"))
            volume = 1_100_000 + (index % 7) * 70_000 + (index // 10) * 25_000
        elif symbol == "XBI":
            cycle = (
                Decimal("0.00"),
                Decimal("0.10"),
                Decimal("-0.08"),
                Decimal("0.06"),
                Decimal("-0.03"),
            )[index % 5]
            close = (
                Decimal("100.00") + Decimal("0.18") * index + cycle
            ).quantize(Decimal("0.01"))
            open_ = (
                close - Decimal("0.12") if index % 2 == 0 else close + Decimal("0.10")
            ).quantize(Decimal("0.01"))
            high = (max(open_, close) + Decimal("0.35")).quantize(Decimal("0.01"))
            low = (min(open_, close) - Decimal("0.32")).quantize(Decimal("0.01"))
            volume = 5_000_000 + (index % 5) * 100_000
        else:
            raise ValueError("unsupported synthetic symbol")
        lines.append(
            f"{symbol}.US,D,{session:%Y%m%d},000000,{open_},{high},{low},{close},{volume},0"
        )
    return "\n".join(lines) + "\n"


def _series(symbol: str):
    return parse_stooq_bulk_text(
        _synthetic_stooq_text(symbol),
        symbol=symbol,
        retrieved_at=AS_OF,
    )


def test_provider_audit_is_explicitly_validation_only_and_keyless():
    audit = stooq_validation_license(AS_OF)
    assert audit.provider == PROVIDER
    assert audit.api_key_required is False
    assert audit.validation_path_approved is True
    assert audit.automated_access_approved is False
    assert audit.commercial_use_approved is False
    assert audit.redistribution_approved is False
    assert audit.access_mode == "LOCAL_BULK_SNAPSHOT"


def test_stooq_bulk_parser_and_zip_are_deterministic(tmp_path: Path):
    text = _synthetic_stooq_text("ABC")
    direct = parse_stooq_bulk_text(text, symbol="ABC", retrieved_at=AS_OF)
    assert len(direct.bars) == 80
    assert direct.bars[-1].session_date == date(2026, 4, 23)
    assert direct.bars[-1].adjusted_close == Decimal("15.90")

    archive = tmp_path / "bulk.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("abc.us.txt", text)
    zipped = parse_stooq_bulk_file(
        archive,
        symbol="ABC",
        retrieved_at=AS_OF,
    )
    assert zipped.bars == direct.bars
    assert zipped.raw_blob_sha256 == direct.raw_blob_sha256


def test_independent_indicator_recomputation_matches_golden(repository_root: Path):
    golden = json.loads(_fixture_text(repository_root, "milestone6_golden.json"))
    security = _series("ABC")
    benchmark = _series("XBI")
    snapshot = build_technical_snapshot(
        security,
        benchmark,
        as_of=AS_OF,
        expected_latest_session=date(2026, 4, 23),
    )

    abc_rows = _independent_rows(_synthetic_stooq_text("ABC"))
    xbi_rows = _independent_rows(_synthetic_stooq_text("XBI"))
    independently = _independent_metrics(abc_rows, xbi_rows)

    assert security.raw_blob_sha256 == golden["abc_sha256"]
    assert benchmark.raw_blob_sha256 == golden["xbi_sha256"]
    for key in (
        "close",
        "sma20",
        "sma50",
        "rsi14",
        "atr14",
        "security_return_20d_pct",
        "xbi_return_20d_pct",
        "xbi_relative_return_20d_pct",
        "up_down_dollar_volume_ratio",
        "obv_slope",
    ):
        actual = getattr(snapshot, key)
        expected = Decimal(golden[key])
        independent = independently[key]
        assert abs(actual - expected) < Decimal("1e-20")
        assert abs(actual - independent) < Decimal("1e-20")
    assert snapshot.support == Decimal(golden["validated_support"])
    assert snapshot.stale is False


def test_frozen_technical_score_consumes_m6_snapshot(
    repository_root: Path,
    scorecard_path: Path,
):
    security = _series("ABC")
    benchmark = _series("XBI")
    snapshot = build_technical_snapshot(
        security,
        benchmark,
        as_of=AS_OF,
        expected_latest_session=date(2026, 4, 23),
    )
    evidence = technical_evidence(EVIDENCE_ID)
    score = score_technicals(
        technical_score_input(
            snapshot,
            base_success_target=Decimal("20"),
            evidence=evidence,
        ),
        load_scorecard(scorecard_path).contract,
    )
    golden = json.loads(_fixture_text(repository_root, "milestone6_golden.json"))
    assert score.points == golden["technical_score_with_base_target_20"]
    assert {item.code: item.points for item in score.subfactors} == {
        "TREND": 2,
        "RELATIVE_STRENGTH": 1,
        "ACCUMULATION": 1,
        "STRUCTURE": 2,
        "EXTENSION": 0,
    }


def test_explicit_pivot_can_raise_validated_support_without_hidden_detector():
    security = _series("ABC")
    benchmark = _series("XBI")
    pivot = PivotSupportEvidence(
        level=Decimal("15.60"),
        tested_sessions=(date(2026, 4, 15), date(2026, 4, 16)),
    )
    snapshot = build_technical_snapshot(
        security,
        benchmark,
        as_of=AS_OF,
        expected_latest_session=date(2026, 4, 23),
        pivot_support=pivot,
    )
    assert snapshot.support == Decimal("15.60")
    assert snapshot.resistance is None

    invalid = PivotSupportEvidence(
        level=Decimal("15.60"),
        tested_sessions=(date(2026, 1, 5), date(2026, 4, 16)),
    )
    with pytest.raises(ValueError, match="prior 60"):
        build_technical_snapshot(
            security,
            benchmark,
            as_of=AS_OF,
            expected_latest_session=date(2026, 4, 23),
            pivot_support=invalid,
        )


def test_stale_and_missing_session_controls_block_score_input():
    security = _series("ABC")
    benchmark = _series("XBI")
    stale = build_technical_snapshot(
        security,
        benchmark,
        as_of=AS_OF + timedelta(days=1),
        expected_latest_session=date(2026, 4, 24),
    )
    assert stale.stale is True
    with pytest.raises(ValueError, match="stale"):
        technical_score_input(
            stale,
            base_success_target=Decimal("20"),
            evidence=technical_evidence(EVIDENCE_ID),
        )

    short = security.model_copy(update={"bars": security.bars[-59:]})
    with pytest.raises(ValueError, match="60 aligned"):
        build_technical_snapshot(
            short,
            benchmark,
            as_of=AS_OF,
            expected_latest_session=date(2026, 4, 23),
        )


def test_provider_adjusted_historical_snapshot_cannot_leak_future_split_state():
    current_snapshot = _series("ABC")
    with pytest.raises(ValueError, match="post-dates"):
        point_in_time_series(current_snapshot, date(2026, 3, 31))


def test_raw_split_adjustment_uses_only_splits_known_by_cutoff():
    raw = (
        RawMarketBar(
            symbol="ABC",
            session_date=date(2026, 4, 20),
            open=Decimal("100"),
            high=Decimal("104"),
            low=Decimal("98"),
            close=Decimal("102"),
            volume=1000,
        ),
        RawMarketBar(
            symbol="ABC",
            session_date=date(2026, 4, 21),
            open=Decimal("51"),
            high=Decimal("53"),
            low=Decimal("50"),
            close=Decimal("52"),
            volume=2200,
        ),
    )
    split = SplitEvent(
        symbol="ABC",
        effective_session=date(2026, 4, 21),
        ratio_new_for_old=Decimal("2"),
        known_at=datetime(2026, 4, 20, 18, 0, tzinfo=UTC),
        evidence_id="split-2-for-1",
    )
    adjusted = adjust_raw_bars_for_splits(
        symbol="ABC",
        provider="FIXTURE",
        bars=raw,
        splits=(split,),
        cutoff=datetime(2026, 4, 21, 20, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 4, 21, 22, 0, tzinfo=UTC),
        available_at=datetime(2026, 4, 21, 22, 0, tzinfo=UTC),
        raw_blob_sha256="1" * 64,
        license_audit_provider="FIXTURE",
    )
    assert adjusted.bars[0].adjusted_close == Decimal("51")
    assert adjusted.bars[0].volume == 2000
    assert adjusted.bars[1].adjusted_close == Decimal("52")

    future_known = split.model_copy(
        update={"known_at": datetime(2026, 4, 21, 21, 0, tzinfo=UTC)}
    )
    unadjusted = adjust_raw_bars_for_splits(
        symbol="ABC",
        provider="FIXTURE",
        bars=raw,
        splits=(future_known,),
        cutoff=datetime(2026, 4, 21, 20, 0, tzinfo=UTC),
        retrieved_at=datetime(2026, 4, 21, 22, 0, tzinfo=UTC),
        available_at=datetime(2026, 4, 21, 22, 0, tzinfo=UTC),
        raw_blob_sha256="2" * 64,
        license_audit_provider="FIXTURE",
    )
    assert unadjusted.bars[0].adjusted_close == Decimal("102")
    assert unadjusted.bars[0].volume == 1000


def test_investability_inputs_use_adjusted_close_liquidity_and_session_count(
    repository_root: Path,
):
    security = _series("ABC")
    inputs = investability_market_inputs(
        security,
        as_of_session=date(2026, 4, 23),
        expected_latest_session=date(2026, 4, 23),
        shares_outstanding=Decimal("10000000"),
    )
    golden = json.loads(_fixture_text(repository_root, "milestone6_golden.json"))
    assert inputs.adjusted_close == Decimal("15.90")
    assert inputs.median_dollar_volume_20d == Decimal(golden["median_dollar_volume_20d"])
    assert inputs.valid_trading_sessions == 80
    assert inputs.market_cap == Decimal("159000000")
    assert inputs.stale is False


def test_scorecard_checksum_remains_frozen(scorecard_path: Path):
    loaded = load_scorecard(scorecard_path)
    assert loaded.raw_sha256 == RULES_RAW_SHA


def _independent_rows(text: str):
    reader = csv.DictReader(io.StringIO(text))
    result = []
    for row in reader:
        result.append(
            {
                "date": date(
                    int(row["<DATE>"][:4]),
                    int(row["<DATE>"][4:6]),
                    int(row["<DATE>"][6:8]),
                ),
                "open": Decimal(row["<OPEN>"]),
                "high": Decimal(row["<HIGH>"]),
                "low": Decimal(row["<LOW>"]),
                "close": Decimal(row["<CLOSE>"]),
                "volume": int(row["<VOL>"]),
            }
        )
    return result


def _independent_metrics(security, benchmark):
    closes = [item["close"] for item in security]
    bench = [item["close"] for item in benchmark]
    sma20 = sum(closes[-20:], Decimal("0")) / Decimal(20)
    sma50 = sum(closes[-50:], Decimal("0")) / Decimal(50)
    security_return = (closes[-1] / closes[-21] - 1) * 100
    benchmark_return = (bench[-1] / bench[-21] - 1) * 100

    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(change, Decimal("0")) for change in changes]
    losses = [max(-change, Decimal("0")) for change in changes]
    avg_gain = sum(gains[:14], Decimal("0")) / Decimal(14)
    avg_loss = sum(losses[:14], Decimal("0")) / Decimal(14)
    for gain, loss in zip(gains[14:], losses[14:]):
        avg_gain = (avg_gain * 13 + gain) / 14
        avg_loss = (avg_loss * 13 + loss) / 14
    if avg_loss == 0:
        rsi = Decimal("100") if avg_gain > 0 else Decimal("50")
    else:
        rs = avg_gain / avg_loss
        rsi = Decimal("100") - Decimal("100") / (Decimal("1") + rs)

    true_ranges = []
    for index in range(1, len(security)):
        item = security[index]
        previous_close = security[index - 1]["close"]
        true_ranges.append(
            max(
                item["high"] - item["low"],
                abs(item["high"] - previous_close),
                abs(item["low"] - previous_close),
            )
        )
    atr = sum(true_ranges[:14], Decimal("0")) / Decimal(14)
    for true_range in true_ranges[14:]:
        atr = (atr * 13 + true_range) / 14

    up = Decimal("0")
    down = Decimal("0")
    window = security[-21:]
    obv = Decimal("0")
    obv_values = []
    for previous, current in zip(window, window[1:]):
        dollar_volume = current["close"] * Decimal(current["volume"])
        if current["close"] > previous["close"]:
            up += dollar_volume
            obv += Decimal(current["volume"])
        elif current["close"] < previous["close"]:
            down += dollar_volume
            obv -= Decimal(current["volume"])
        obv_values.append(obv)
    ratio = up / down

    xs = [Decimal(index) for index in range(20)]
    x_mean = sum(xs, Decimal("0")) / Decimal(20)
    y_mean = sum(obv_values, Decimal("0")) / Decimal(20)
    obv_slope = sum(
        (x - x_mean) * (y - y_mean) for x, y in zip(xs, obv_values)
    ) / sum((x - x_mean) ** 2 for x in xs)

    return {
        "close": closes[-1],
        "sma20": sma20,
        "sma50": sma50,
        "rsi14": rsi,
        "atr14": atr,
        "security_return_20d_pct": security_return,
        "xbi_return_20d_pct": benchmark_return,
        "xbi_relative_return_20d_pct": security_return - benchmark_return,
        "up_down_dollar_volume_ratio": ratio,
        "obv_slope": obv_slope,
    }
