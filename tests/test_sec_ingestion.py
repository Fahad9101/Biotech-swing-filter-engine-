from datetime import UTC, datetime
from pathlib import Path

import pytest

from boe.enums import Exchange, SecurityKind
from boe.ingestion.sec import (
    parse_sec_submissions,
    parse_sec_ticker_exchange,
    sec_submissions_url,
)
from boe.universe import ListingRecord, resolve_sec_mapping

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "universe"
AS_OF = datetime(2026, 9, 14, 20, tzinfo=UTC)


def test_parse_sec_identity_and_resolve_exact_exchange():
    mappings = parse_sec_ticker_exchange(
        (FIXTURE_DIR / "company_tickers_exchange.json").read_bytes()
    )
    listing = ListingRecord(
        ticker="ARWX",
        security_name="Arrow Example Therapeutics Common Stock",
        exchange=Exchange.NASDAQ,
        exchange_code="Q",
        security_kind=SecurityKind.COMMON_STOCK,
        test_issue=False,
        etf=False,
        next_shares=False,
        financial_status=None,
        source_row=2,
    )

    match = resolve_sec_mapping(listing, mappings)
    assert match is not None
    assert match.cik == "0000000001"
    assert sec_submissions_url(match.cik).endswith("CIK0000000001.json")

    mismatched = listing.model_copy(update={"exchange": Exchange.NYSE})
    assert resolve_sec_mapping(mismatched, mappings) is None


def test_sec_submissions_is_point_in_time_and_reporting_current():
    profile = parse_sec_submissions(
        (FIXTURE_DIR / "submissions.json").read_bytes(),
        source_available_at=AS_OF,
        as_of=AS_OF,
    )

    assert profile.cik == "0000000001"
    assert profile.latest_periodic_filing_date.isoformat() == "2026-08-08"
    assert profile.latest_periodic_form == "10-Q"
    assert profile.reporting_current is True


def test_sec_submissions_rejects_future_payload():
    with pytest.raises(ValueError, match="unavailable"):
        parse_sec_submissions(
            (FIXTURE_DIR / "submissions.json").read_bytes(),
            source_available_at=datetime(2026, 9, 15, tzinfo=UTC),
            as_of=AS_OF,
        )


def test_sec_reporting_recency_fails_closed_after_140_days():
    content = b"""{
      "cik":"1", "name":"Stale Example", "tickers":["OLD"],
      "exchanges":["Nasdaq"], "filings":{"recent":{
        "form":["10-Q/A"], "filingDate":["2026-01-01"],
        "acceptanceDateTime":["20260102120000"]}}
    }"""
    profile = parse_sec_submissions(
        content,
        source_available_at=AS_OF,
        as_of=AS_OF,
    )

    assert profile.latest_periodic_form == "10-Q"
    assert profile.reporting_current is False


def test_sec_mapping_rejects_misaligned_rows():
    with pytest.raises(ValueError, match="does not align"):
        parse_sec_ticker_exchange(b'{"fields":["cik","name","ticker","exchange"],"data":[[1,"X"]]}')
