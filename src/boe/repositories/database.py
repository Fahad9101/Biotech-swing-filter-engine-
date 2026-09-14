"""SQLAlchemy persistence for Milestone 2 identity and evidence records."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from boe.evidence import Claim, EvidenceItem, RawPayloadRecord
from boe.universe import (
    BusinessEvidence,
    ListingRecord,
    SecSubmissionProfile,
    UniverseDecision,
)


class Base(DeclarativeBase):
    pass


class RawPayloadRow(Base):
    __tablename__ = "raw_payloads"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int]
    media_type: Mapped[str | None]
    source_url: Mapped[str] = mapped_column(Text)
    retrieved_at: Mapped[str] = mapped_column(String(40))
    available_at: Mapped[str] = mapped_column(String(40))
    relative_path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class EvidenceItemRow(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evidence_type: Mapped[str]
    source_tier: Mapped[int]
    title: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str]
    source_url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str | None] = mapped_column(String(40))
    available_at: Mapped[str] = mapped_column(String(40), index=True)
    retrieved_at: Mapped[str] = mapped_column(String(40))
    accession_or_external_id: Mapped[str | None]
    raw_blob_sha256: Mapped[str] = mapped_column(ForeignKey("raw_payloads.sha256"))
    excerpt_locator: Mapped[str | None] = mapped_column(Text)
    supports_claim: Mapped[str] = mapped_column(Text)
    quality_flag: Mapped[str | None]
    supersedes_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_items.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class ClaimRow(Base):
    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "field_name",
            "known_at",
            "evidence_id",
            name="uq_claim_observation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_type: Mapped[str]
    subject_id: Mapped[str]
    field_name: Mapped[str]
    typed_value_json: Mapped[str] = mapped_column(Text)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"))
    valid_from: Mapped[str] = mapped_column(String(40))
    known_at: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[str] = mapped_column(String(40))


class IssuerRow(Base):
    __tablename__ = "issuers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    legal_name: Mapped[str]
    country: Mapped[str | None]
    sic: Mapped[str | None]
    filer_type: Mapped[str | None]
    reporting_currency: Mapped[str | None]
    business_class: Mapped[str | None]
    universe_status: Mapped[str | None]
    classification_rationale: Mapped[str | None] = mapped_column(Text)
    latest_periodic_filing_date: Mapped[str | None]
    latest_periodic_form: Mapped[str | None]
    reporting_current: Mapped[bool | None]
    source_raw_blob_sha256: Mapped[str] = mapped_column(ForeignKey("raw_payloads.sha256"))
    source_available_at: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class SecurityRow(Base):
    __tablename__ = "securities"
    __table_args__ = (UniqueConstraint("ticker", "exchange_code", name="uq_security_symbol"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(14), index=True)
    exchange: Mapped[str | None]
    exchange_code: Mapped[str]
    security_name: Mapped[str]
    security_kind: Mapped[str]
    adr_flag: Mapped[bool] = mapped_column(Boolean)
    listing_status: Mapped[str]
    first_trade_date: Mapped[str | None]
    last_trade_date: Mapped[str | None]
    test_issue: Mapped[bool] = mapped_column(Boolean)
    etf: Mapped[bool] = mapped_column(Boolean)
    next_shares: Mapped[bool] = mapped_column(Boolean)
    source_raw_blob_sha256: Mapped[str] = mapped_column(ForeignKey("raw_payloads.sha256"))
    source_row: Mapped[int]
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class UniverseSnapshotRow(Base):
    __tablename__ = "universe_snapshots"
    __table_args__ = (
        UniqueConstraint("as_of", "security_id", "rules_version", name="uq_universe_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(40), index=True)
    security_id: Mapped[str] = mapped_column(ForeignKey("securities.id"), index=True)
    eligible: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str]
    investability_floor_status: Mapped[str]
    reason_codes_json: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    supporting_claim_ids_json: Mapped[str] = mapped_column(Text)
    rules_version: Mapped[str]
    created_at: Mapped[str] = mapped_column(String(40))


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)

    @classmethod
    def sqlite(cls, path: str | Path) -> Database:
        resolved = Path(path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return cls(f"sqlite+pysqlite:///{resolved}")

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            with session.begin():
                yield session


class Milestone2Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add_raw_payload(self, record: RawPayloadRecord) -> None:
        with self.database.session() as session:
            existing = session.get(RawPayloadRow, record.sha256)
            if existing is not None:
                if existing.size_bytes != record.size_bytes:
                    raise ValueError("raw-payload digest exists with a different size")
                return
            session.add(
                RawPayloadRow(
                    sha256=record.sha256,
                    size_bytes=record.size_bytes,
                    media_type=record.media_type,
                    source_url=str(record.source_url),
                    retrieved_at=_iso(record.retrieved_at),
                    available_at=_iso(record.available_at),
                    relative_path=record.relative_path,
                    created_at=_now_iso(),
                )
            )

    def add_evidence(self, item: EvidenceItem) -> None:
        with self.database.session() as session:
            if session.get(EvidenceItemRow, str(item.id)) is not None:
                raise ValueError("evidence IDs are append-only and must be unique")
            if session.get(RawPayloadRow, item.raw_blob_sha256) is None:
                raise ValueError("evidence references an absent raw payload")
            session.add(
                EvidenceItemRow(
                    id=str(item.id),
                    evidence_type=item.evidence_type,
                    source_tier=int(item.source_tier),
                    title=item.title,
                    publisher=item.publisher,
                    source_url=str(item.source_url),
                    published_at=_iso(item.published_at),
                    available_at=_iso(item.available_at),
                    retrieved_at=_iso(item.retrieved_at),
                    accession_or_external_id=item.accession_or_external_id,
                    raw_blob_sha256=item.raw_blob_sha256,
                    excerpt_locator=item.excerpt_locator,
                    supports_claim=item.supports_claim,
                    quality_flag=item.quality_flag,
                    supersedes_id=str(item.supersedes_id) if item.supersedes_id else None,
                    created_at=_now_iso(),
                )
            )

    def add_claim(self, claim: Claim) -> None:
        with self.database.session() as session:
            if session.get(ClaimRow, str(claim.id)) is not None:
                raise ValueError("claim IDs are append-only and must be unique")
            if session.get(EvidenceItemRow, str(claim.evidence_id)) is None:
                raise ValueError("claim references absent evidence")
            session.add(
                ClaimRow(
                    id=str(claim.id),
                    subject_type=claim.subject_type,
                    subject_id=claim.subject_id,
                    field_name=claim.field_name,
                    typed_value_json=json.dumps(
                        claim.typed_value, sort_keys=True, separators=(",", ":"), default=str
                    ),
                    evidence_id=str(claim.evidence_id),
                    valid_from=_iso(claim.valid_from),
                    known_at=_iso(claim.known_at),
                    confidence=claim.confidence.value,
                    status=claim.status.value,
                    created_at=_now_iso(),
                )
            )

    def upsert_issuer(
        self,
        profile: SecSubmissionProfile,
        evidence: BusinessEvidence | None,
        decision: UniverseDecision | None,
        *,
        source_raw_blob_sha256: str,
    ) -> str:
        with self.database.session() as session:
            if session.get(RawPayloadRow, source_raw_blob_sha256) is None:
                raise ValueError("issuer references an absent raw payload")
            row = session.scalar(select(IssuerRow).where(IssuerRow.cik == profile.cik))
            now = _now_iso()
            if row is None:
                row = IssuerRow(
                    id=str(uuid4()),
                    cik=profile.cik,
                    legal_name=profile.legal_name,
                    source_available_at=profile.source_available_at.isoformat(),
                    source_raw_blob_sha256=source_raw_blob_sha256,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            row.legal_name = profile.legal_name
            row.country = profile.country
            row.sic = profile.sic
            row.filer_type = profile.filer_category
            row.reporting_currency = None
            row.business_class = (
                evidence.lead_economic_asset_type.value if evidence is not None else None
            )
            row.universe_status = decision.status.value if decision is not None else None
            row.classification_rationale = decision.rationale if decision is not None else None
            row.latest_periodic_filing_date = (
                profile.latest_periodic_filing_date.isoformat()
                if profile.latest_periodic_filing_date
                else None
            )
            row.latest_periodic_form = profile.latest_periodic_form
            row.reporting_current = profile.reporting_current
            row.source_raw_blob_sha256 = source_raw_blob_sha256
            row.source_available_at = profile.source_available_at.isoformat()
            row.updated_at = now
            session.flush()
            return row.id

    def upsert_security(
        self,
        issuer_id: str,
        listing: ListingRecord,
        *,
        source_raw_blob_sha256: str,
    ) -> str:
        with self.database.session() as session:
            if session.get(RawPayloadRow, source_raw_blob_sha256) is None:
                raise ValueError("security references an absent raw payload")
            row = session.scalar(
                select(SecurityRow).where(
                    SecurityRow.ticker == listing.ticker,
                    SecurityRow.exchange_code == listing.exchange_code,
                )
            )
            now = _now_iso()
            if row is None:
                row = SecurityRow(
                    id=str(uuid4()),
                    ticker=listing.ticker,
                    exchange_code=listing.exchange_code,
                    issuer_id=issuer_id,
                    exchange=listing.exchange.value if listing.exchange else None,
                    security_name=listing.security_name,
                    security_kind=listing.security_kind.value,
                    adr_flag=listing.security_kind.value == "ADR",
                    listing_status="ACTIVE",
                    test_issue=listing.test_issue,
                    etf=listing.etf,
                    next_shares=listing.next_shares,
                    source_raw_blob_sha256=source_raw_blob_sha256,
                    source_row=listing.source_row,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            elif row.issuer_id != issuer_id:
                raise ValueError("ticker/exchange maps to a different issuer")
            row.exchange = listing.exchange.value if listing.exchange else None
            row.security_name = listing.security_name
            row.security_kind = listing.security_kind.value
            row.adr_flag = listing.security_kind.value == "ADR"
            row.listing_status = "ACTIVE"
            row.test_issue = listing.test_issue
            row.etf = listing.etf
            row.next_shares = listing.next_shares
            row.source_raw_blob_sha256 = source_raw_blob_sha256
            row.source_row = listing.source_row
            row.updated_at = now
            session.flush()
            return row.id

    def add_universe_snapshot(
        self,
        security_id: str,
        decision: UniverseDecision,
        *,
        rules_version: str = "BOE-1.0.0",
    ) -> str:
        with self.database.session() as session:
            if session.get(SecurityRow, security_id) is None:
                raise ValueError("universe snapshot references absent security")
            absent_claim_ids = [
                claim_id
                for claim_id in decision.supporting_claim_ids
                if session.get(ClaimRow, claim_id) is None
            ]
            if absent_claim_ids:
                raise ValueError(f"universe snapshot references absent claims: {absent_claim_ids}")
            row = UniverseSnapshotRow(
                id=str(uuid4()),
                as_of=_iso(decision.as_of),
                security_id=security_id,
                eligible=decision.eligible,
                status=decision.status.value,
                investability_floor_status=decision.investability_floor_status.value,
                reason_codes_json=json.dumps(decision.reason_codes),
                rationale=decision.rationale,
                supporting_claim_ids_json=json.dumps(decision.supporting_claim_ids),
                rules_version=rules_version,
                created_at=_now_iso(),
            )
            session.add(row)
            session.flush()
            return row.id

    def count(self, table: type[Base]) -> int:
        with self.database.session() as session:
            return len(session.scalars(select(table)).all())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
