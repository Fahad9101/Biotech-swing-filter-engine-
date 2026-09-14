from datetime import UTC, datetime
from pathlib import Path

import pytest

from boe.enums import Exchange, SecurityKind
from boe.ingestion.exchange import parse_nasdaq_listed, parse_other_listed

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "universe"
NOW = datetime(2026, 9, 14, 19, tzinfo=UTC)


def test_parse_official_symbol_directory_shapes():
    nasdaq = parse_nasdaq_listed((FIXTURE_DIR / "nasdaqlisted.txt").read_bytes(), retrieved_at=NOW)
    other = parse_other_listed((FIXTURE_DIR / "otherlisted.txt").read_bytes(), retrieved_at=NOW)

    assert nasdaq.file_creation_time == "0914202618:00"
    assert len(nasdaq.raw_sha256) == 64
    assert [item.security_kind for item in nasdaq.listings] == [
        SecurityKind.COMMON_STOCK,
        SecurityKind.EXCLUDED_INSTRUMENT,
        SecurityKind.EXCLUDED_INSTRUMENT,
        SecurityKind.COMMON_STOCK,
        SecurityKind.UNKNOWN,
    ]
    assert other.listings[0].exchange is Exchange.NYSE
    assert other.listings[0].security_kind is SecurityKind.ADR
    assert other.listings[1].exchange is Exchange.NYSE_AMERICAN
    assert other.listings[2].exchange is None
    assert other.excluded_exchange_rows == 1


def test_symbol_directory_requires_creation_trailer():
    content = b"Symbol|Security Name|ETF|Test Issue|NextShares\nABC|ABC Common Stock|N|N|N\n"
    with pytest.raises(ValueError, match="File Creation Time"):
        parse_nasdaq_listed(content, retrieved_at=NOW)
