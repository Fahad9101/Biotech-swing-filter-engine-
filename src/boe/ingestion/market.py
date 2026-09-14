"""Validation-path market adapter for immutable Stooq bulk snapshots.

The BOE validation path intentionally does not automate Stooq downloads. The
operator supplies a bulk historical snapshot obtained under the provider's
applicable terms. This avoids silently depending on an undocumented endpoint,
an API key, or a provider whose commercial rights have not been approved.
"""

from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from boe.market import (
    MarketDataLicenseAudit,
    MarketSeries,
    RawMarketBar,
    normalize_provider_adjusted_bars,
)

PROVIDER = "STOOQ_BULK"
SOURCE_URL = "https://stooq.com/db/h/"
TERMS_REVIEW_URL = "https://stooq.com/"


def stooq_validation_license(reviewed_at: datetime) -> MarketDataLicenseAudit:
    return MarketDataLicenseAudit(
        provider=PROVIDER,
        reviewed_at=reviewed_at,
        source_url=SOURCE_URL,
        terms_url=TERMS_REVIEW_URL,
        api_key_required=False,
        automated_access_approved=False,
        commercial_use_approved=False,
        redistribution_approved=False,
        validation_path_approved=True,
        access_mode="LOCAL_BULK_SNAPSHOT",
        notes=(
            "Milestone 6 uses operator-supplied bulk history only; BOE performs no automated download.",
            "BOE assumes no commercial rights; the operator must obtain the snapshot under applicable terms.",
            "Commercial production remains blocked pending an explicitly licensed market-data source.",
            "Historical point-in-time use requires an archived snapshot from the relevant cutoff date.",
        ),
    )


def parse_stooq_bulk_text(
    text: str,
    *,
    symbol: str,
    retrieved_at: datetime,
    available_at: datetime | None = None,
) -> MarketSeries:
    raw_bytes = text.encode()
    raw_bars = _parse_rows(text, symbol=symbol)
    return normalize_provider_adjusted_bars(
        symbol=symbol,
        provider=PROVIDER,
        bars=raw_bars,
        retrieved_at=retrieved_at,
        available_at=available_at or retrieved_at,
        raw_blob_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        license_audit_provider=PROVIDER,
        adjustment_version="STOOQ-BULK-SNAPSHOT-1",
    )


def parse_stooq_bulk_file(
    path: str | Path,
    *,
    symbol: str,
    retrieved_at: datetime | None = None,
    member: str | None = None,
) -> MarketSeries:
    resolved = Path(path)
    stamp = retrieved_at or datetime.fromtimestamp(resolved.stat().st_mtime, tz=UTC)
    if resolved.suffix.lower() == ".zip":
        with zipfile.ZipFile(resolved) as archive:
            selected = member or _select_member(archive.namelist(), symbol)
            text = archive.read(selected).decode("utf-8-sig")
    else:
        text = resolved.read_text(encoding="utf-8-sig")
    return parse_stooq_bulk_text(text, symbol=symbol, retrieved_at=stamp)


def _select_member(names: list[str], symbol: str) -> str:
    normalized = symbol.lower().replace(".", "_")
    candidates = [
        name
        for name in names
        if name.lower().endswith((".txt", ".csv")) and normalized in Path(name).stem.lower()
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(f"no Stooq bulk member found for {symbol}")
    raise ValueError(f"multiple Stooq bulk members found for {symbol}; specify member explicitly")


def _parse_rows(text: str, *, symbol: str) -> tuple[RawMarketBar, ...]:
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if row and not row[0].lstrip().startswith("#")]
    if not rows:
        raise ValueError("Stooq bulk snapshot is empty")
    first = [item.strip().upper().strip("<>") for item in rows[0]]
    has_header = "DATE" in first and "CLOSE" in first
    data_rows = rows[1:] if has_header else rows
    header = {name: index for index, name in enumerate(first)} if has_header else {}
    parsed: list[RawMarketBar] = []
    for row_number, row in enumerate(data_rows, start=2 if has_header else 1):
        try:
            if has_header:
                ticker = row[header.get("TICKER", 0)].strip().upper()
                date_text = row[header["DATE"]].strip()
                open_text = row[header["OPEN"]].strip()
                high_text = row[header["HIGH"]].strip()
                low_text = row[header["LOW"]].strip()
                close_text = row[header["CLOSE"]].strip()
                volume_text = row[header["VOL"] if "VOL" in header else header["VOLUME"]].strip()
            else:
                if len(row) < 8:
                    raise ValueError("expected at least 8 Stooq fields")
                ticker = row[0].strip().upper()
                date_text, open_text, high_text, low_text, close_text, volume_text = (
                    row[2].strip(),
                    row[3].strip(),
                    row[4].strip(),
                    row[5].strip(),
                    row[6].strip(),
                    row[7].strip(),
                )
        except (IndexError, KeyError) as exc:
            raise ValueError(f"invalid Stooq row {row_number}") from exc
        if ticker not in {symbol.upper(), f"{symbol.upper()}.US"}:
            continue
        parsed.append(
            RawMarketBar(
                symbol=symbol.upper(),
                session_date=_parse_date(date_text),
                open=Decimal(open_text),
                high=Decimal(high_text),
                low=Decimal(low_text),
                close=Decimal(close_text),
                volume=int(Decimal(volume_text)),
            )
        )
    if not parsed:
        raise ValueError(f"Stooq bulk snapshot contains no rows for {symbol}")
    return tuple(sorted(parsed, key=lambda item: item.session_date))


def _parse_date(value: str):
    from datetime import date

    stripped = value.strip()
    if len(stripped) == 8 and stripped.isdigit():
        return date(int(stripped[:4]), int(stripped[4:6]), int(stripped[6:8]))
    return date.fromisoformat(stripped)
