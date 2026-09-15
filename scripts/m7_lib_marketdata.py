"""Shared Alpaca/SEC primary-source helpers for M7 historical-universe verification.

Not wired into the CI-run readiness generator; used interactively/in batch
scripts to produce validation/m7/promotion/historical-universe-ledger-*.json
rows with the frozen investability-floor thresholds from
contracts/boe-scorecard.v1.0.0.json (investability_floor).

Uses raw (split/dividend-unadjusted) SIP daily bars, matching the
"RAW_AS_TRADED" provenance already recorded in the earlier ledger rows.
Credentials are read from environment variables only; never hardcode keys.
"""

from __future__ import annotations

import json
import os
import statistics
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEC_UA = {"User-Agent": "BOE-M7-Research research@example.com"}


def _load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    values: dict[str, str] = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip() and "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                values.setdefault(k.strip(), v.strip())
    return values


_ENV = _load_env()
_ALPACA_HEADERS = {
    "APCA-API-KEY-ID": _ENV.get("ALPACA_API_KEY_ID", ""),
    "APCA-API-SECRET-KEY": _ENV.get("ALPACA_API_SECRET_KEY", ""),
}


def _get(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def alpaca_daily_bars(ticker: str, start: str, end: str, feed: str = "sip") -> list[dict]:
    """Raw (unadjusted) daily bars from start through end (inclusive), SIP feed."""
    url = (
        f"https://data.alpaca.markets/v2/stocks/{ticker}/bars"
        f"?start={start}&end={end}&timeframe=1Day&feed={feed}&adjustment=raw&limit=10000"
    )
    bars: list[dict] = []
    page_token = None
    while True:
        u = url + (f"&page_token={page_token}" if page_token else "")
        d = _get(u, _ALPACA_HEADERS)
        bars.extend(d.get("bars") or [])
        page_token = d.get("next_page_token")
        if not page_token:
            break
    return bars


# Tried in order: the standard dei cover-page concept first, then the two
# most common fallbacks for filers that don't tag it (domestic GAAP filers
# tagging only the balance-sheet concept; IFRS-taxonomy foreign filers).
_SHARES_OUTSTANDING_CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
    ("ifrs-full", "NumberOfSharesOutstanding"),
]


def sec_shares_outstanding_history(cik: str) -> tuple[list[dict], str | None]:
    """(rows, concept_used) from SEC XBRL company facts, oldest first. rows is []
    and concept_used is None if the issuer tags none of the known concepts.

    Uses the bulk companyfacts endpoint rather than per-tag companyconcept: the
    latter has been observed to return an empty {} units object for a tag that
    companyfacts shows has real data (e.g. Incyte's us-gaap:CommonStockSharesOutstanding),
    an apparent SEC-side inconsistency between the two endpoints.
    """
    cik10 = cik.zfill(10)
    try:
        d = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json", SEC_UA)
    except urllib.error.HTTPError:
        return [], None
    facts = d.get("facts", {})
    for ns, tag in _SHARES_OUTSTANDING_CONCEPTS:
        units = facts.get(ns, {}).get(tag, {}).get("units", {}).get("shares", [])
        if units:
            return sorted(units, key=lambda x: x["end"]), f"{ns}:{tag}"
    return [], None


def latest_shares_outstanding_before(cik: str, cutoff_date: str) -> dict | None:
    """Most recent disclosed share count whose FILING date is <= cutoff_date (point-in-time).
    Returned dict includes a "concept" key naming the XBRL tag it came from.

    Skips non-positive values: SEC XBRL occasionally contains a filer's tagging
    error (observed: a Summit Therapeutics 6-K tagged
    dei:EntityCommonStockSharesOutstanding=0, evidently a boilerplate/blank cover
    page default, while its adjacent 20-F correctly showed ~73.6M) - a company
    with 0 shares outstanding while actively trading is definitionally wrong, so
    such rows are excluded rather than trusted at face value.

    Among eligible rows, selects by latest "end" (period-end) date, not latest
    "filed" date: a single 10-K/10-Q reports several comparative-year period-end
    values that all share the same filed date (observed for Biogen: one FY2020
    10-K, filed once, tags 197.2M for FY2018, 174.2M for FY2019 and 152.4M for
    FY2020 as of the *same* filed date), so picking by filed date alone can pick
    an arbitrary stale comparative-year figure instead of the most current one.
    """
    history, concept = sec_shares_outstanding_history(cik)
    eligible = [h for h in history if h["filed"] <= cutoff_date and h["val"] > 0]
    if not eligible:
        return None
    row = max(eligible, key=lambda x: (x["end"], x["filed"]))
    return {**row, "concept": concept}


def sec_submissions(cik: str) -> dict:
    cik10 = cik.zfill(10)
    return _get(f"https://data.sec.gov/submissions/CIK{cik10}.json", SEC_UA)


@dataclass
class UniverseCheck:
    ticker: str
    cutoff_session: str
    first_trade_session: str | None
    valid_sessions_through_cutoff: int
    session_continuity_pass: bool
    last_raw_close_usd: float | None
    price_floor_pass: bool | None
    liquidity_window_start: str | None
    liquidity_window_end: str | None
    median_close_x_volume_usd: float | None
    median_vwap_x_volume_usd: float | None
    liquidity_floor_pass: bool | None
    shares_outstanding: int | None
    shares_source_date: str | None
    shares_source_form: str | None
    shares_source_accn: str | None
    shares_source_concept: str | None
    market_cap_proxy_usd: float | None
    market_cap_floor_pass: bool | None
    all_floors_pass: bool
    bar_count_total: int


PRICE_FLOOR = 1.0
LIQUIDITY_FLOOR = 2_000_000.0
MARKET_CAP_FLOOR = 50_000_000.0
SESSION_FLOOR = 60


def run_universe_check(
    ticker: str,
    cik: str,
    cutoff_session: str,
    listing_lookback_start: str,
) -> UniverseCheck:
    """cutoff_session: last complete regular session before the event (YYYY-MM-DD).
    listing_lookback_start: a date known to be on/before the security's first trade
    session (e.g. from SEC 8-A/424B4 filing date), used to bound the bar fetch.
    """
    bars = alpaca_daily_bars(ticker, listing_lookback_start, cutoff_session)
    bars = [b for b in bars if b["t"][:10] <= cutoff_session]
    bar_count_total = len(bars)
    first_trade_session = bars[0]["t"][:10] if bars else None
    valid_sessions = len(bars)
    session_pass = valid_sessions >= SESSION_FLOOR

    last_close = bars[-1]["c"] if bars else None
    price_pass = (last_close >= PRICE_FLOOR) if last_close is not None else None

    window = bars[-20:] if len(bars) >= 20 else bars
    med_close_vol = statistics.median([b["c"] * b["v"] for b in window]) if window else None
    med_vwap_vol = statistics.median([b["vw"] * b["v"] for b in window]) if window else None
    liq_pass = (med_close_vol >= LIQUIDITY_FLOOR) if med_close_vol is not None else None

    shares_row = latest_shares_outstanding_before(cik, cutoff_session)
    shares = shares_row["val"] if shares_row else None
    mcap = (last_close * shares) if (last_close is not None and shares is not None) else None
    mcap_pass = (mcap >= MARKET_CAP_FLOOR) if mcap is not None else None

    all_pass = bool(session_pass and price_pass and liq_pass and mcap_pass)

    return UniverseCheck(
        ticker=ticker,
        cutoff_session=cutoff_session,
        first_trade_session=first_trade_session,
        valid_sessions_through_cutoff=valid_sessions,
        session_continuity_pass=session_pass,
        last_raw_close_usd=last_close,
        price_floor_pass=price_pass,
        liquidity_window_start=window[0]["t"][:10] if window else None,
        liquidity_window_end=window[-1]["t"][:10] if window else None,
        median_close_x_volume_usd=med_close_vol,
        median_vwap_x_volume_usd=med_vwap_vol,
        liquidity_floor_pass=liq_pass,
        shares_outstanding=shares,
        shares_source_date=shares_row["end"] if shares_row else None,
        shares_source_form=shares_row["form"] if shares_row else None,
        shares_source_accn=shares_row["accn"] if shares_row else None,
        shares_source_concept=shares_row["concept"] if shares_row else None,
        market_cap_proxy_usd=mcap,
        market_cap_floor_pass=mcap_pass,
        all_floors_pass=all_pass,
        bar_count_total=bar_count_total,
    )


def last_complete_session_before(
    event_timestamp: str, market_calendar_probe_ticker: str = "XBI"
) -> str:
    """Given an ISO event timestamp with UTC offset, return the last complete regular
    session (YYYY-MM-DD) before it: previous session if event is pre-market or during
    market hours, same session only if event is strictly after the 16:00 ET close.
    """
    dt = datetime.fromisoformat(event_timestamp)
    market_close_same_day = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    probe_end = dt.date().isoformat()
    probe_start = (dt.date() - timedelta(days=14)).isoformat()
    bars = alpaca_daily_bars(market_calendar_probe_ticker, probe_start, probe_end)
    sessions = [b["t"][:10] for b in bars]
    if dt <= market_close_same_day:
        prior = [s for s in sessions if s < dt.date().isoformat()]
        return prior[-1]
    else:
        same_or_prior = [s for s in sessions if s <= dt.date().isoformat()]
        return same_or_prior[-1]
