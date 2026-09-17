from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from boe.ingestion.alpaca import (
    DATA_HOST,
    alpaca_validation_license,
    credentials_from_env,
    fetch_daily_bars,
    fetch_point_in_time_bars,
    fetch_split_adjusted_closes,
)

AUTH_HEADERS = {"APCA-API-KEY-ID": "key-123", "APCA-API-SECRET-KEY": "secret-456"}


def _bar(day: str, close: float) -> dict:
    return {
        "t": f"{day}T05:00:00Z",
        "o": close - 1,
        "h": close + 1,
        "l": close - 2,
        "c": close,
        "v": 1000,
    }


def test_fetch_daily_bars_parses_a_single_page():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["APCA-API-KEY-ID"] == "key-123"
        assert request.headers["APCA-API-SECRET-KEY"] == "secret-456"
        assert "feed=sip" in str(request.url)
        assert "adjustment=all" in str(request.url)
        return httpx.Response(
            200,
            json={"bars": [_bar("2024-01-02", 100.0), _bar("2024-01-03", 101.5)]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        series = fetch_daily_bars(
            "AAPL",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            api_key_id="key-123",
            api_secret_key="secret-456",
            client=client,
            retrieved_at=datetime(2024, 1, 6, tzinfo=UTC),
        )

    assert series.symbol == "AAPL"
    assert series.provider == "ALPACA_MARKET_DATA"
    assert [bar.session_date for bar in series.bars] == [date(2024, 1, 2), date(2024, 1, 3)]
    assert series.bars[0].adjusted_close == series.bars[0].close


def test_fetch_daily_bars_follows_pagination():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("page_token"))
        if request.url.params.get("page_token") is None:
            return httpx.Response(
                200,
                json={"bars": [_bar("2024-01-02", 100.0)], "next_page_token": "abc"},
                request=request,
            )
        return httpx.Response(
            200,
            json={"bars": [_bar("2024-01-03", 101.0)], "next_page_token": None},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        series = fetch_daily_bars(
            "AAPL",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            api_key_id="key-123",
            api_secret_key="secret-456",
            client=client,
        )

    assert calls == [None, "abc"]
    assert [bar.session_date for bar in series.bars] == [date(2024, 1, 2), date(2024, 1, 3)]


def test_fetch_daily_bars_rejects_inverted_range():
    with pytest.raises(ValueError, match="end must not precede start"):
        fetch_daily_bars(
            "AAPL",
            start=date(2024, 1, 5),
            end=date(2024, 1, 1),
            api_key_id="key-123",
            api_secret_key="secret-456",
        )


def test_fetch_daily_bars_rejects_a_non_alpaca_host():
    with pytest.raises(ValueError, match=DATA_HOST):
        fetch_daily_bars(
            "AAPL",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            api_key_id="key-123",
            api_secret_key="secret-456",
            data_url="https://evil.example.com",
        )


def test_fetch_daily_bars_rejects_empty_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bars": []}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="no bars"):
            fetch_daily_bars(
                "ZZZZ",
                start=date(2024, 1, 1),
                end=date(2024, 1, 5),
                api_key_id="key-123",
                api_secret_key="secret-456",
                client=client,
            )


def test_fetch_daily_bars_propagates_http_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_daily_bars(
                "AAPL",
                start=date(2024, 1, 1),
                end=date(2024, 1, 5),
                api_key_id="key-123",
                api_secret_key="secret-456",
                client=client,
            )


def test_fetch_point_in_time_bars_requests_raw_adjustment_and_is_not_provider_adjusted():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "adjustment=raw" in str(request.url)
        return httpx.Response(
            200,
            json={"bars": [_bar("2024-01-02", 100.0), _bar("2024-01-03", 101.5)]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        series = fetch_point_in_time_bars(
            "AAPL",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            as_of=datetime(2024, 1, 3, tzinfo=UTC),
            api_key_id="key-123",
            api_secret_key="secret-456",
            client=client,
        )

    assert series.provider_adjusted is False
    assert [bar.session_date for bar in series.bars] == [date(2024, 1, 2), date(2024, 1, 3)]


def test_fetch_point_in_time_bars_is_safe_for_a_historical_cutoff():
    """The whole point of this function: unlike fetch_daily_bars(), its
    output must pass point_in_time_series() for a cutoff far in the past."""
    from boe.market import point_in_time_series

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bars": [_bar("2018-01-02", 50.0)]}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        series = fetch_point_in_time_bars(
            "AAPL",
            start=date(2018, 1, 1),
            end=date(2018, 1, 5),
            as_of=datetime(2018, 1, 3, tzinfo=UTC),
            api_key_id="key-123",
            api_secret_key="secret-456",
            client=client,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),  # "today", far after as_of
        )

    point_in_time_series(series, date(2018, 1, 3))  # must not raise


def test_fetch_split_adjusted_closes_requests_split_adjustment():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "adjustment=split" in str(request.url)
        return httpx.Response(
            200,
            json={"bars": [_bar("2024-01-02", 100.0), _bar("2024-01-03", 101.5)]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        closes = fetch_split_adjusted_closes(
            "AAPL",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
            api_key_id="key-123",
            api_secret_key="secret-456",
            client=client,
        )

    assert closes == {date(2024, 1, 2): Decimal("100.0"), date(2024, 1, 3): Decimal("101.5")}


def test_alpaca_validation_license_is_self_consistent():
    audit = alpaca_validation_license(datetime(2026, 9, 17, tzinfo=UTC))
    assert audit.access_mode == "HTTP_API"
    assert audit.automated_access_approved is True
    assert audit.commercial_use_approved is False
    assert audit.redistribution_approved is False


def test_credentials_from_env_requires_both_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="ALPACA_API_KEY_ID"):
        credentials_from_env()


def test_credentials_from_env_reads_real_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALPACA_API_KEY_ID", "key-123")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "secret-456")
    monkeypatch.delenv("ALPACA_DATA_URL", raising=False)
    key_id, secret_key, data_url = credentials_from_env()
    assert key_id == "key-123"
    assert secret_key == "secret-456"
    assert data_url == "https://data.alpaca.markets"
