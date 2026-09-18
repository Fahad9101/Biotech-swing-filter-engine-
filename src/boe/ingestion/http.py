"""Bounded HTTP client for explicitly allowlisted public BOE sources."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Self
from urllib.parse import urlparse

import httpx
from pydantic import Field, HttpUrl, model_validator

from boe.models import ContractModel

ALLOWED_HOSTS = frozenset(
    {
        "api.fda.gov",
        "clinicaltrials.gov",
        "data.sec.gov",
        "efts.sec.gov",
        "nasdaqtrader.com",
        "www.clinicaltrials.gov",
        "www.fda.gov",
        "www.nasdaqtrader.com",
        "www.sec.gov",
    }
)
SEC_HOSTS = frozenset({"data.sec.gov", "efts.sec.gov", "www.sec.gov"})
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class FetchedPayload(ContractModel):
    url: HttpUrl
    content: bytes
    media_type: str | None
    retrieved_at: datetime
    available_at: datetime
    status_code: int = Field(ge=200, lt=300)

    @model_validator(mode="after")
    def valid_timestamps(self) -> Self:
        if self.available_at > self.retrieved_at:
            raise ValueError("available_at cannot be after retrieved_at")
        return self


class PublicDataClient:
    """Synchronous, rate-controlled client with no arbitrary-URL access."""

    def __init__(
        self,
        user_agent: str,
        *,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if "@" not in user_agent or len(user_agent.strip()) < 8:
            raise ValueError("user_agent must identify the application and a contact email")
        if max_attempts < 1 or max_attempts > 5:
            raise ValueError("max_attempts must be between 1 and 5")
        self._user_agent = user_agent.strip()
        self._max_attempts = max_attempts
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            transport=transport,
            headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        self._lock = threading.Lock()
        self._last_sec_request = 0.0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchedPayload:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
            raise ValueError("URL must use HTTPS and an approved BOE public-data host")

        last_response: httpx.Response | None = None
        for attempt in range(1, self._max_attempts + 1):
            if host in SEC_HOSTS:
                self._pace_sec_request()
            response = self._client.get(url)
            last_response = response
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return self._payload_from_response(response)
            if attempt < self._max_attempts:
                time.sleep(self._retry_delay(response, attempt))

        assert last_response is not None
        last_response.raise_for_status()
        raise AssertionError("unreachable")

    def _pace_sec_request(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = 0.11 - (now - self._last_sec_request)
            if delay > 0:
                time.sleep(delay)
            self._last_sec_request = time.monotonic()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), 30.0)
            except ValueError:
                pass
        return min(0.25 * float(2 ** (attempt - 1)), 2.0)

    @staticmethod
    def _payload_from_response(response: httpx.Response) -> FetchedPayload:
        retrieved_at = datetime.now(UTC)
        last_modified = response.headers.get("Last-Modified")
        available_at = retrieved_at
        if last_modified:
            try:
                parsed = parsedate_to_datetime(last_modified)
                available_at = parsed.astimezone(UTC)
                if available_at > retrieved_at:
                    available_at = retrieved_at
            except (TypeError, ValueError, OverflowError):
                available_at = retrieved_at
        media_type = response.headers.get("Content-Type")
        if media_type:
            media_type = media_type.split(";", 1)[0].strip().lower()
        return FetchedPayload(
            url=str(response.url),
            content=response.content,
            media_type=media_type,
            retrieved_at=retrieved_at,
            available_at=available_at,
            status_code=response.status_code,
        )
