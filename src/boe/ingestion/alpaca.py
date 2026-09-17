"""Validation-path market adapter for the Alpaca Market Data API.

Unlike this package's Stooq adapter (market.py: an operator-supplied bulk
snapshot, no automated access at all), Alpaca's historical bars are reached
through its documented, officially supported REST API using an
operator-provided API key. The free "Basic" plan - the default on a
zero-funding-required paper trading account - serves full CTA/UTP
consolidated-tape ("SIP") historical daily bars back to 2016, with no
restriction other than the most recent 15 minutes of data. That was verified
directly against the live API for this project (a real AAPL bar fetch, and a
raw/split/all adjustment comparison across AAPL's August 2020 4-for-1 split),
not assumed from marketing copy. See alpaca_validation_license() below for
what remains explicitly unapproved (commercial use, redistribution).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from boe.market import (
    MarketDataLicenseAudit,
    MarketSeries,
    RawMarketBar,
    adjust_raw_bars_for_splits,
    normalize_provider_adjusted_bars,
)

PROVIDER = "ALPACA_MARKET_DATA"
DATA_HOST = "data.alpaca.markets"
DEFAULT_DATA_URL = f"https://{DATA_HOST}"
SOURCE_URL = "https://docs.alpaca.markets/docs/about-market-data-api"
TERMS_URL = "https://alpaca.markets/disclosures"

# Full consolidated tape (CTA + UTP), split- and dividend-adjusted - the
# "split-adjusted total returns" series VALIDATION-AND-MILESTONES.md section
# 4 requires, not Alpaca's unadjusted default.
_FEED = "sip"
_ADJUSTMENT = "all"
_PAGE_LIMIT = 10_000


def alpaca_validation_license(reviewed_at: datetime) -> MarketDataLicenseAudit:
    return MarketDataLicenseAudit(
        provider=PROVIDER,
        reviewed_at=reviewed_at,
        source_url=SOURCE_URL,
        terms_url=TERMS_URL,
        api_key_required=True,
        automated_access_approved=True,
        commercial_use_approved=False,
        redistribution_approved=False,
        validation_path_approved=True,
        access_mode="HTTP_API",
        notes=(
            "Automated historical access via a free, zero-funding-required "
            "Basic-plan API key is the documented, intended use of Alpaca's "
            "Market Data API - unlike Stooq's undocumented bulk endpoint, "
            "this is not a workaround.",
            "Historical daily bars are available from 2016 onward on the "
            "free plan; only the most recent 15 minutes of SIP data require "
            "a paid subscription, which does not affect 2018-2025 "
            "historical reconstruction.",
            "feed=sip, adjustment=all requests the full consolidated tape, "
            "split- and dividend-adjusted - confirmed against the live API "
            "for a known 2020 AAPL split rather than assumed from docs.",
            "BOE assumes no commercial or redistribution rights; production "
            "use requires a separate, explicitly licensed agreement.",
        ),
    )


def credentials_from_env() -> tuple[str, str, str]:
    """Read (api_key_id, api_secret_key, data_url) from the environment.

    Callers must not print, log, or persist the returned secret key.
    """
    key_id = os.environ.get("ALPACA_API_KEY_ID")
    secret_key = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key_id or not secret_key:
        raise ValueError(
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY must be set in the environment"
        )
    data_url = os.environ.get("ALPACA_DATA_URL", DEFAULT_DATA_URL)
    return key_id, secret_key, data_url


def fetch_daily_bars(
    symbol: str,
    *,
    start: date,
    end: date,
    api_key_id: str,
    api_secret_key: str,
    data_url: str = DEFAULT_DATA_URL,
    retrieved_at: datetime | None = None,
    client: httpx.Client | None = None,
) -> MarketSeries:
    """Fetch and normalize real split/dividend-adjusted daily bars for one symbol."""
    if end < start:
        raise ValueError("end must not precede start")
    parsed_host = urlparse(data_url)
    if parsed_host.scheme != "https" or parsed_host.hostname != DATA_HOST:
        raise ValueError(f"data_url must be an https://{DATA_HOST} URL")

    stamp = retrieved_at or datetime.now(UTC)
    headers = {"APCA-API-KEY-ID": api_key_id, "APCA-API-SECRET-KEY": api_secret_key}
    owns_client = client is None
    http_client = client or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        pages = _fetch_pages(
            http_client, symbol, start=start, end=end, headers=headers, data_url=data_url
        )
    finally:
        if owns_client:
            http_client.close()

    raw_bytes = json.dumps(pages, sort_keys=True).encode()
    raw_bars = _parse_pages(pages, symbol=symbol)
    return normalize_provider_adjusted_bars(
        symbol=symbol.upper(),
        provider=PROVIDER,
        bars=raw_bars,
        retrieved_at=stamp,
        available_at=stamp,
        raw_blob_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        license_audit_provider=PROVIDER,
        adjustment_version="ALPACA-SIP-ADJUSTMENT-ALL-1",
    )


def fetch_point_in_time_bars(
    symbol: str,
    *,
    start: date,
    end: date,
    as_of: datetime,
    api_key_id: str,
    api_secret_key: str,
    data_url: str = DEFAULT_DATA_URL,
    retrieved_at: datetime | None = None,
    client: httpx.Client | None = None,
) -> MarketSeries:
    """Fetch real, unadjusted daily bars - safe for point-in-time technical
    reconstruction as of a historical cutoff, unlike fetch_daily_bars().

    fetch_daily_bars()'s adjustment=all reflects every split/dividend known
    TODAY, including ones after any historical as_of - correct for computing
    real total returns after the fact (scripts/m7_build_outcomes.py), wrong
    for reconstructing what technical indicators would have looked like at
    the time (boe.market.point_in_time_series() enforces exactly this and
    would reject an "all"-adjusted series for a past cutoff). This function
    requests Alpaca's adjustment=raw bars instead and passes them through
    adjust_raw_bars_for_splits() with an empty split list (no real
    split-event source exists for this project) - genuinely unadjusted,
    provider_adjusted=False, honestly not incorporating any post-cutoff
    knowledge. A real stock split within the lookback window would still
    distort raw price levels; callers should treat extreme single-session
    moves as a signal to investigate, not trust blindly.
    """
    if end < start:
        raise ValueError("end must not precede start")
    parsed_host = urlparse(data_url)
    if parsed_host.scheme != "https" or parsed_host.hostname != DATA_HOST:
        raise ValueError(f"data_url must be an https://{DATA_HOST} URL")

    stamp = retrieved_at or datetime.now(UTC)
    headers = {"APCA-API-KEY-ID": api_key_id, "APCA-API-SECRET-KEY": api_secret_key}
    owns_client = client is None
    http_client = client or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        pages = _fetch_pages(
            http_client,
            symbol,
            start=start,
            end=end,
            headers=headers,
            data_url=data_url,
            adjustment="raw",
        )
    finally:
        if owns_client:
            http_client.close()

    raw_bytes = json.dumps(pages, sort_keys=True).encode()
    raw_bars = _parse_pages(pages, symbol=symbol)
    return adjust_raw_bars_for_splits(
        symbol=symbol.upper(),
        provider=PROVIDER,
        bars=raw_bars,
        splits=(),
        cutoff=as_of,
        retrieved_at=stamp,
        available_at=stamp,
        raw_blob_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        license_audit_provider=PROVIDER,
        adjustment_version="ALPACA-RAW-UNADJUSTED-1",
    )


def fetch_split_adjusted_closes(
    symbol: str,
    *,
    start: date,
    end: date,
    api_key_id: str,
    api_secret_key: str,
    data_url: str = DEFAULT_DATA_URL,
    client: httpx.Client | None = None,
) -> dict[date, Decimal]:
    """Real, split-only-adjusted closes (adjustment=split), keyed by session
    date - not wrapped in a MarketSeries, and not itself safe for point-in-
    time scoring (like fetch_daily_bars(), it reflects every split known
    today). Intended only for comparison against fetch_point_in_time_bars()'s
    genuinely unadjusted closes, to find real split effective dates by where
    the two series diverge - see scripts/m7_build_technical_snapshots.py.
    """
    if end < start:
        raise ValueError("end must not precede start")
    parsed_host = urlparse(data_url)
    if parsed_host.scheme != "https" or parsed_host.hostname != DATA_HOST:
        raise ValueError(f"data_url must be an https://{DATA_HOST} URL")

    headers = {"APCA-API-KEY-ID": api_key_id, "APCA-API-SECRET-KEY": api_secret_key}
    owns_client = client is None
    http_client = client or httpx.Client(timeout=httpx.Timeout(30.0))
    try:
        pages = _fetch_pages(
            http_client,
            symbol,
            start=start,
            end=end,
            headers=headers,
            data_url=data_url,
            adjustment="split",
        )
    finally:
        if owns_client:
            http_client.close()
    bars = _parse_pages(pages, symbol=symbol)
    return {bar.session_date: bar.close for bar in bars}


def _fetch_pages(
    http_client: httpx.Client,
    symbol: str,
    *,
    start: date,
    end: date,
    headers: dict[str, str],
    data_url: str,
    adjustment: str = _ADJUSTMENT,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, str | int] = {
            "feed": _FEED,
            "timeframe": "1Day",
            "adjustment": adjustment,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": _PAGE_LIMIT,
        }
        if page_token:
            params["page_token"] = page_token
        response = http_client.get(
            f"{data_url}/v2/stocks/{symbol}/bars", params=params, headers=headers
        )
        response.raise_for_status()
        payload = response.json()
        pages.append(payload)
        page_token = payload.get("next_page_token")
        if not page_token:
            return pages


def _parse_pages(pages: list[dict[str, Any]], *, symbol: str) -> tuple[RawMarketBar, ...]:
    parsed: list[RawMarketBar] = []
    for payload in pages:
        for bar in payload.get("bars") or []:
            parsed.append(
                RawMarketBar(
                    symbol=symbol.upper(),
                    session_date=datetime.fromisoformat(bar["t"]).date(),
                    open=Decimal(str(bar["o"])),
                    high=Decimal(str(bar["h"])),
                    low=Decimal(str(bar["l"])),
                    close=Decimal(str(bar["c"])),
                    volume=int(bar["v"]),
                )
            )
    if not parsed:
        raise ValueError(f"Alpaca returned no bars for {symbol}")
    return tuple(sorted(parsed, key=lambda item: item.session_date))
