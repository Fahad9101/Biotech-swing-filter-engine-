from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest

from boe.ingestion.http import PublicDataClient


def test_http_client_enforces_identity_and_allowlist():
    with pytest.raises(ValueError, match="contact email"):
        PublicDataClient("anonymous")

    with PublicDataClient(
        "BOE test test@example.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    ) as client:
        with pytest.raises(ValueError, match="approved"):
            client.fetch("https://example.com/data.json")


def test_http_client_retries_and_preserves_availability_time(monkeypatch):
    calls = 0
    modified = datetime(2026, 9, 1, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(
            200,
            content=b"payload",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Last-Modified": format_datetime(modified, usegmt=True),
            },
            request=request,
        )

    monkeypatch.setattr("boe.ingestion.http.time.sleep", lambda _: None)
    with PublicDataClient(
        "BOE test test@example.com",
        max_attempts=2,
        transport=httpx.MockTransport(handler),
    ) as client:
        payload = client.fetch("https://www.nasdaqtrader.com/data.json")

    assert calls == 2
    assert payload.content == b"payload"
    assert payload.available_at == modified
    assert payload.media_type == "application/json"
