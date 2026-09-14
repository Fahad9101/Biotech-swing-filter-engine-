"""Parsers for official Nasdaq Trader symbol-directory files."""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from typing import Self

from pydantic import Field, model_validator

from boe.enums import Exchange, SecurityKind
from boe.models import ContractModel
from boe.universe import ListingRecord

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

EXCLUDED_NAME_MARKERS = (
    " warrant",
    " warrants",
    " right",
    " rights",
    " unit",
    " units",
    " preferred",
    " preference",
    " notes due",
    " bond",
    " exchange traded fund",
    " etf",
    " acquisition corp",
    " acquisition corporation",
    " blank check",
)
ADR_MARKERS = ("american depositary share", "american depositary receipt", " adr")
COMMON_MARKERS = ("common stock", "common shares", "ordinary shares", "voting shares")


class SymbolDirectorySnapshot(ContractModel):
    source_url: str
    retrieved_at: datetime
    file_creation_time: str
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    listings: tuple[ListingRecord, ...]
    excluded_exchange_rows: int = Field(ge=0)

    @model_validator(mode="after")
    def unique_tickers(self) -> Self:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        keys = [(item.ticker, item.exchange_code) for item in self.listings]
        if len(set(keys)) != len(keys):
            raise ValueError("symbol directory contains duplicate ticker/exchange rows")
        return self


def infer_security_kind(name: str, *, etf: bool) -> SecurityKind:
    normalized = f" {name.casefold()}"
    if etf:
        return SecurityKind.EXCLUDED_INSTRUMENT
    if any(marker in normalized for marker in ADR_MARKERS):
        return SecurityKind.ADR
    if "depositary shares" in normalized and "preferred" in normalized:
        return SecurityKind.EXCLUDED_INSTRUMENT
    if any(marker in normalized for marker in EXCLUDED_NAME_MARKERS):
        return SecurityKind.EXCLUDED_INSTRUMENT
    if any(marker in normalized for marker in COMMON_MARKERS):
        return SecurityKind.COMMON_STOCK
    return SecurityKind.UNKNOWN


def parse_nasdaq_listed(
    content: bytes,
    *,
    retrieved_at: datetime,
    source_url: str = NASDAQ_LISTED_URL,
) -> SymbolDirectorySnapshot:
    return _parse_directory(
        content,
        retrieved_at=retrieved_at,
        source_url=source_url,
        ticker_column="Symbol",
        exchange_column=None,
    )


def parse_other_listed(
    content: bytes,
    *,
    retrieved_at: datetime,
    source_url: str = OTHER_LISTED_URL,
) -> SymbolDirectorySnapshot:
    return _parse_directory(
        content,
        retrieved_at=retrieved_at,
        source_url=source_url,
        ticker_column="ACT Symbol",
        exchange_column="Exchange",
    )


def _parse_directory(
    content: bytes,
    *,
    retrieved_at: datetime,
    source_url: str,
    ticker_column: str,
    exchange_column: str | None,
) -> SymbolDirectorySnapshot:
    text = content.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text), delimiter="|"))
    if not rows:
        raise ValueError("symbol directory is empty")

    trailer = rows[-1]
    trailer_value = trailer.get(ticker_column, "")
    if not trailer_value.startswith("File Creation Time"):
        raise ValueError("symbol directory lacks a File Creation Time trailer")
    file_creation_time = trailer_value.split(":", 1)[-1].strip()

    listings: list[ListingRecord] = []
    excluded_exchange_rows = 0
    for row_number, row in enumerate(rows[:-1], start=2):
        ticker = (row.get(ticker_column) or "").strip().upper()
        name = (row.get("Security Name") or "").strip()
        if not ticker or not name:
            raise ValueError(f"invalid symbol-directory row {row_number}")
        exchange_code = "Q" if exchange_column is None else (row.get(exchange_column) or "")
        exchange = _map_exchange(exchange_code)
        if exchange is None:
            excluded_exchange_rows += 1
        etf = (row.get("ETF") or "N").strip() == "Y"
        listings.append(
            ListingRecord(
                ticker=ticker,
                security_name=name,
                exchange=exchange,
                exchange_code=exchange_code or "?",
                security_kind=infer_security_kind(name, etf=etf),
                test_issue=(row.get("Test Issue") or "N").strip() == "Y",
                etf=etf,
                next_shares=(row.get("NextShares") or "N").strip() == "Y",
                financial_status=(row.get("Financial Status") or "").strip() or None,
                source_row=row_number,
            )
        )

    return SymbolDirectorySnapshot(
        source_url=source_url,
        retrieved_at=retrieved_at,
        file_creation_time=file_creation_time,
        raw_sha256=hashlib.sha256(content).hexdigest(),
        listings=tuple(listings),
        excluded_exchange_rows=excluded_exchange_rows,
    )


def _map_exchange(code: str) -> Exchange | None:
    normalized = code.strip().upper()
    if normalized == "Q":
        return Exchange.NASDAQ
    if normalized == "N":
        return Exchange.NYSE
    if normalized == "A":
        return Exchange.NYSE_AMERICAN
    return None
