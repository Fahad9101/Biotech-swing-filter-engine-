"""Parsers and identity helpers for SEC public JSON datasets."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from boe.universe import SecSubmissionProfile, SecTickerMapping

SEC_TICKER_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "40-F"})


def sec_submissions_url(cik: str | int) -> str:
    normalized = _normalize_cik(cik)
    return f"https://data.sec.gov/submissions/CIK{normalized}.json"


def parse_sec_ticker_exchange(content: bytes) -> tuple[SecTickerMapping, ...]:
    payload = _json_object(content)
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise ValueError("SEC ticker exchange payload lacks fields/data arrays")
    required = {"cik", "name", "ticker", "exchange"}
    if not required.issubset(set(fields)):
        raise ValueError("SEC ticker exchange payload lacks required columns")

    mappings: list[SecTickerMapping] = []
    seen: set[tuple[str, str]] = set()
    for row in data:
        if not isinstance(row, list) or len(row) != len(fields):
            raise ValueError("SEC ticker exchange row does not align with fields")
        item = dict(zip(fields, row, strict=True))
        mapping = SecTickerMapping(
            cik=_normalize_cik(item["cik"]),
            legal_name=str(item["name"]).strip(),
            ticker=str(item["ticker"]).strip().upper(),
            exchange=str(item["exchange"]).strip(),
        )
        key = (mapping.ticker, mapping.exchange)
        if key in seen:
            raise ValueError(f"duplicate SEC ticker/exchange mapping: {key}")
        seen.add(key)
        mappings.append(mapping)
    return tuple(mappings)


def parse_sec_submissions(
    content: bytes,
    *,
    source_available_at: datetime,
    as_of: datetime,
) -> SecSubmissionProfile:
    if source_available_at.tzinfo is None or as_of.tzinfo is None:
        raise ValueError("source_available_at and as_of must be timezone-aware")
    if source_available_at > as_of:
        raise ValueError("SEC submissions payload was unavailable at as_of")
    payload = _json_object(content)
    cik = _normalize_cik(payload.get("cik"))
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    latest_periodic, latest_periodic_form = _latest_periodic_filing(recent, as_of)
    entity_type = _optional_string(payload.get("entityType"))
    reporting_current = _reporting_current(latest_periodic, latest_periodic_form, as_of.date())

    tickers = tuple(str(value).strip().upper() for value in payload.get("tickers", []))
    exchanges = tuple(str(value).strip() for value in payload.get("exchanges", []))
    return SecSubmissionProfile(
        cik=cik,
        legal_name=str(payload.get("name") or "").strip(),
        sic=_normalize_sic(payload.get("sic")),
        sic_description=_optional_string(payload.get("sicDescription")),
        entity_type=entity_type,
        filer_category=_optional_string(payload.get("category")),
        country=_optional_string(payload.get("stateOfIncorporation")),
        tickers=tickers,
        exchanges=exchanges,
        latest_periodic_filing_date=latest_periodic,
        latest_periodic_form=latest_periodic_form,
        reporting_current=reporting_current,
        source_available_at=source_available_at,
    )


def _latest_periodic_filing(recent: object, as_of: datetime) -> tuple[date | None, str | None]:
    if not isinstance(recent, dict):
        return None, None
    forms = recent.get("form")
    filing_dates = recent.get("filingDate")
    acceptance_times = recent.get("acceptanceDateTime")
    if not isinstance(forms, list) or not isinstance(filing_dates, list):
        return None, None
    if len(forms) != len(filing_dates):
        raise ValueError("SEC recent filing form/date arrays do not align")
    if not isinstance(acceptance_times, list) or len(acceptance_times) != len(forms):
        acceptance_times = [None] * len(forms)

    known_filings: list[tuple[date, str]] = []
    for form, filing_date, accepted in zip(forms, filing_dates, acceptance_times, strict=True):
        normalized_form = str(form).removesuffix("/A")
        if normalized_form not in PERIODIC_FORMS:
            continue
        filed = date.fromisoformat(str(filing_date))
        available = _acceptance_datetime(accepted, filed)
        if available <= as_of:
            known_filings.append((filed, normalized_form))
    if not known_filings:
        return None, None
    return max(known_filings, key=lambda item: item[0])


def _reporting_current(
    latest_periodic: date | None,
    latest_periodic_form: str | None,
    as_of: date,
) -> bool | None:
    if latest_periodic is None:
        return None
    age = as_of - latest_periodic
    threshold = timedelta(days=550 if latest_periodic_form in {"20-F", "40-F"} else 140)
    return age <= threshold


def _acceptance_datetime(value: object, filed: date) -> datetime:
    if value:
        text = str(value).strip()
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
            if len(text) == 14 and text.isdigit():
                return datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            pass
    return datetime.combine(filed, time.max, tzinfo=UTC)


def _json_object(content: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid SEC JSON payload") from exc
    if not isinstance(payload, dict):
        raise ValueError("SEC JSON payload must be an object")
    return payload


def _normalize_cik(value: object) -> str:
    text = str(value).strip()
    if not text.isdigit() or len(text) > 10:
        raise ValueError(f"invalid CIK: {value!r}")
    return text.zfill(10)


def _normalize_sic(value: object) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if not text.isdigit() or len(text) > 4:
        raise ValueError(f"invalid SIC: {value!r}")
    return text.zfill(4)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
