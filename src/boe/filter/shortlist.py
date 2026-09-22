"""SHORTLIST-1.0: narrows the full watchlist to catalysts worth chart time.

This is a *fit* filter, not a probability ranking. Every rule below is a
structural fact (is the catalyst dated inside the trading horizon? can the
stock plausibly move 20% and actually be traded?) - nothing here predicts
that a stock will rise. The historical validation of these same factors
found ~0 correlation between the combined score and returns, and this
module deliberately does not reintroduce one.

The definition is versioned and its parameters are recorded in every
forward-log snapshot (see boe.filter.forward): changing a threshold means
bumping SHORTLIST_DEFINITION, never editing history.

Tiers (by how well the disclosed catalyst date fits the horizon):
  1  exact date within [today, today + horizon_days]
  2  quarter-level guidance whose quarter overlaps that same span
  0  everything else (year-only guidance, or dated beyond the horizon)

Only tier 1 and 2 rows can be shortlisted, and only if they also pass the
size / tradeability checks. Unknown is not a failure: a row whose market
cap or technicals could not be computed is kept and flagged, never
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

SHORTLIST_DEFINITION = "SHORTLIST-1.0"

EXACT_DATE = "EXACT_DATE"
QUARTER = "QUARTER"

OUTSIDE_TIME_WINDOW = "OUTSIDE_TIME_WINDOW"
PRICE_BELOW_MIN = "PRICE_BELOW_MIN"
LIQUIDITY_BELOW_MIN = "LIQUIDITY_BELOW_MIN"
MARKET_CAP_BELOW_MIN = "MARKET_CAP_BELOW_MIN"
MARKET_CAP_ABOVE_MAX = "MARKET_CAP_ABOVE_MAX"

TECHNICALS_UNAVAILABLE = "TECHNICALS_UNAVAILABLE"
LIQUIDITY_UNKNOWN = "LIQUIDITY_UNKNOWN"
MARKET_CAP_UNKNOWN = "MARKET_CAP_UNKNOWN"
STALE_PRICE_DATA = "STALE_PRICE_DATA"


@dataclass(frozen=True)
class ShortlistParameters:
    """Defaults are judgment calls, not fitted values (nothing here was
    tuned on outcomes). min_median_dollar_volume is deliberately lenient
    because live bars come from the IEX feed, whose volume is a small
    fraction of consolidated volume: it only removes names with almost no
    trading, and is not a claim about real tradeable size."""

    horizon_days: int = 56
    min_price: Decimal = Decimal("2.00")
    min_market_cap: Decimal = Decimal("50000000")
    max_market_cap: Decimal = Decimal("10000000000")
    min_median_dollar_volume: Decimal = Decimal("20000")

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "min_price": str(self.min_price),
            "min_market_cap": str(self.min_market_cap),
            "max_market_cap": str(self.max_market_cap),
            "min_median_dollar_volume": str(self.min_median_dollar_volume),
        }


DEFAULT_PARAMETERS = ShortlistParameters()


def catalyst_key(row: dict[str, Any]) -> str:
    return f"{row['ticker']}|{row['catalyst_type']}|{row['window_start']}|{row['window_end']}"


def dedupe_catalysts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per real catalyst. The same disclosure is repeated across
    filings (an 8-K, then its exhibit, then the next quarter's 8-K); keep
    the most recent statement and record how many filings said it."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(catalyst_key(row), []).append(row)
    merged: list[dict[str, Any]] = []
    for key, group in grouped.items():
        latest = max(group, key=lambda r: (r.get("filing_date") or "", r.get("source_url") or ""))
        merged.append(
            {
                **latest,
                "catalyst_key": key,
                "source_count": len(group),
                "all_source_urls": sorted({r["source_url"] for r in group if r.get("source_url")}),
            }
        )
    merged.sort(key=lambda r: (r["window_start"], r["ticker"], r["catalyst_type"]))
    return merged


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def time_tier(row: dict[str, Any], *, today: date, parameters: ShortlistParameters) -> int:
    start = date.fromisoformat(row["window_start"])
    end = date.fromisoformat(row["window_end"])
    horizon_end = today + timedelta(days=parameters.horizon_days)
    precision = row["date_precision"]
    if precision == EXACT_DATE and today <= start <= horizon_end:
        return 1
    if precision == QUARTER and end >= today and start <= horizon_end:
        return 2
    return 0


def market_cap(row: dict[str, Any]) -> Decimal | None:
    shares = _decimal((row.get("cash_dilution_facts") or {}).get("shares_outstanding"))
    close = _decimal((row.get("technical_facts") or {}).get("close"))
    if shares is None or close is None or shares <= 0 or close <= 0:
        return None
    return shares * close


def annotate(
    row: dict[str, Any], *, today: date, parameters: ShortlistParameters
) -> dict[str, Any]:
    tier = time_tier(row, today=today, parameters=parameters)
    tech = row.get("technical_facts") or {}
    close = _decimal(tech.get("close"))
    dollar_volume = _decimal(tech.get("median_dollar_volume_20d"))
    cap = market_cap(row)

    reasons: list[str] = []
    flags: list[str] = []
    if tier == 0:
        reasons.append(OUTSIDE_TIME_WINDOW)
    else:
        if close is None:
            flags.append(TECHNICALS_UNAVAILABLE)
        else:
            if close < parameters.min_price:
                reasons.append(PRICE_BELOW_MIN)
            if dollar_volume is None:
                flags.append(LIQUIDITY_UNKNOWN)
            elif dollar_volume < parameters.min_median_dollar_volume:
                reasons.append(LIQUIDITY_BELOW_MIN)
            if tech.get("stale"):
                flags.append(STALE_PRICE_DATA)
        if cap is None:
            flags.append(MARKET_CAP_UNKNOWN)
        elif cap < parameters.min_market_cap:
            reasons.append(MARKET_CAP_BELOW_MIN)
        elif cap > parameters.max_market_cap:
            reasons.append(MARKET_CAP_ABOVE_MAX)

    shares_text = (row.get("cash_dilution_facts") or {}).get("shares_outstanding")
    return {
        **row,
        "tier": tier,
        "shortlisted": tier in (1, 2) and not reasons,
        "exclusion_reasons": reasons,
        "flags": flags,
        "shares_outstanding": shares_text,
        "market_cap_usd": str(cap.quantize(Decimal("1"))) if cap is not None else None,
        "median_dollar_volume_20d": tech.get("median_dollar_volume_20d"),
    }


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    # shortlisted first; tier 1 (exact dates) before tier 2 (quarter
    # guidance); soonest first within a tier. Never a score.
    return (
        not row["shortlisted"],
        row["tier"] if row["tier"] else 9,
        row["window_end"],
        row["window_start"],
        row["ticker"],
    )


def apply_shortlist(
    rows: list[dict[str, Any]],
    *,
    today: date,
    parameters: ShortlistParameters = DEFAULT_PARAMETERS,
) -> list[dict[str, Any]]:
    annotated = [
        annotate(row, today=today, parameters=parameters) for row in dedupe_catalysts(rows)
    ]
    annotated.sort(key=_sort_key)
    return annotated
