"""SQLAlchemy persistence for Milestone 4 financial-survival records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from boe.financials import (
    CapitalStructureSnapshot,
    CashBurnSnapshot,
    FinancialFact,
    FinancingFacility,
    FinancingFiling,
    FinancingRiskInputs,
    SurvivalSnapshot,
)
from boe.repositories.database import Base, Database


class FinancialFactRow(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "taxonomy",
            "concept",
            "unit",
            "accession",
            "period_start",
            "period_end",
            "instant",
            "value_decimal",
            name="uq_financial_fact_observation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    taxonomy: Mapped[str]
    concept: Mapped[str]
    value_decimal: Mapped[str] = mapped_column(Text)
    unit: Mapped[str]
    period_start: Mapped[str | None] = mapped_column(String(10))
    period_end: Mapped[str | None] = mapped_column(String(10))
    instant: Mapped[str | None] = mapped_column(String(10))
    form: Mapped[str]
    accession: Mapped[str] = mapped_column(index=True)
    filed_at: Mapped[str] = mapped_column(String(40))
    source_available_at: Mapped[str] = mapped_column(String(40), index=True)
    fiscal_year: Mapped[int | None]
    fiscal_period: Mapped[str | None]
    frame: Mapped[str | None]
    source_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"))
    created_at: Mapped[str] = mapped_column(String(40))


class CapitalStructureSnapshotRow(Base):
    __tablename__ = "capital_structure_snapshots"
    __table_args__ = (
        UniqueConstraint("issuer_id", "as_of", name="uq_capital_structure_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    basic_shares: Mapped[str] = mapped_column(Text)
    dilutive_options: Mapped[str] = mapped_column(Text)
    warrants: Mapped[str] = mapped_column(Text)
    rsus: Mapped[str] = mapped_column(Text)
    convertible_shares: Mapped[str] = mapped_column(Text)
    other_dilutive_shares: Mapped[str] = mapped_column(Text)
    expected_financing_shares: Mapped[str] = mapped_column(Text)
    fully_diluted_shares: Mapped[str] = mapped_column(Text)
    projected_fully_diluted_shares: Mapped[str] = mapped_column(Text)
    basic_share_fact_id: Mapped[str] = mapped_column(ForeignKey("financial_facts.id"))
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    calculation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class CashBurnSnapshotRow(Base):
    __tablename__ = "cash_burn_snapshots"
    __table_args__ = (UniqueConstraint("issuer_id", "as_of", name="uq_cash_burn_snapshot"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    quarters_json: Mapped[str] = mapped_column(Text)
    method: Mapped[str]
    confidence: Mapped[str]
    normalized_quarterly_burn: Mapped[str] = mapped_column(Text)
    calculation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class SurvivalSnapshotRow(Base):
    __tablename__ = "survival_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "issuer_id",
            "as_of",
            "catalyst_latest_date",
            name="uq_survival_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    catalyst_latest_date: Mapped[str] = mapped_column(String(10))
    liquidity: Mapped[str] = mapped_column(Text)
    normalized_quarterly_burn: Mapped[str] = mapped_column(Text)
    runway_months: Mapped[str] = mapped_column(Text)
    months_to_latest_catalyst: Mapped[str] = mapped_column(Text)
    runway_at_catalyst_months: Mapped[str] = mapped_column(Text)
    cash_position_evidence_ids_json: Mapped[str] = mapped_column(Text)
    burn_evidence_ids_json: Mapped[str] = mapped_column(Text)
    calculation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class FinancingFilingRow(Base):
    __tablename__ = "financing_filings"
    __table_args__ = (
        UniqueConstraint("issuer_id", "accession", name="uq_financing_filing_accession"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    cik: Mapped[str] = mapped_column(String(10))
    accession: Mapped[str]
    form: Mapped[str]
    filing_date: Mapped[str] = mapped_column(String(10))
    accepted_at: Mapped[str] = mapped_column(String(40), index=True)
    primary_document: Mapped[str]
    filing_url: Mapped[str] = mapped_column(Text)
    category: Mapped[str]
    created_at: Mapped[str] = mapped_column(String(40))


class FinancingFacilityRow(Base):
    __tablename__ = "financing_facilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    kind: Mapped[str]
    active: Mapped[bool] = mapped_column(Boolean)
    opened_at: Mapped[str] = mapped_column(String(10))
    capacity_usd: Mapped[str | None] = mapped_column(Text)
    used_usd: Mapped[str | None] = mapped_column(Text)
    remaining_usd: Mapped[str | None] = mapped_column(Text)
    observed_issuance_dependence: Mapped[bool] = mapped_column(Boolean)
    management_guided_use_before_catalyst: Mapped[bool] = mapped_column(Boolean)
    evidence_ids_json: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str]
    confirmed_at: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[str] = mapped_column(String(40))


class FinancingRiskSnapshotRow(Base):
    __tablename__ = "financing_risk_snapshots"
    __table_args__ = (
        UniqueConstraint("issuer_id", "as_of", name="uq_financing_risk_snapshot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(ForeignKey("issuers.id"), index=True)
    as_of: Mapped[str] = mapped_column(String(40))
    inputs_json: Mapped[str] = mapped_column(Text)
    calculation_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))


class Milestone4Repository:
    """Append-only persistence for point-in-time financial inputs and derivations."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def add_financial_fact(self, fact: FinancialFact) -> None:
        with self.database.session() as session:
            if session.get(FinancialFactRow, str(fact.id)) is not None:
                return
            session.add(
                FinancialFactRow(
                    id=str(fact.id),
                    issuer_id=fact.issuer_id,
                    taxonomy=fact.taxonomy,
                    concept=fact.concept,
                    value_decimal=str(fact.value),
                    unit=fact.unit,
                    period_start=fact.period_start.isoformat() if fact.period_start else None,
                    period_end=fact.period_end.isoformat() if fact.period_end else None,
                    instant=fact.instant.isoformat() if fact.instant else None,
                    form=fact.form,
                    accession=fact.accession,
                    filed_at=fact.filed_at.isoformat(),
                    source_available_at=fact.source_available_at.isoformat(),
                    fiscal_year=fact.fiscal_year,
                    fiscal_period=fact.fiscal_period,
                    frame=fact.frame,
                    source_evidence_id=str(fact.source_evidence_id),
                    created_at=_now_iso(),
                )
            )

    def add_capital_structure(self, snapshot: CapitalStructureSnapshot) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                CapitalStructureSnapshotRow(
                    id=row_id,
                    issuer_id=snapshot.issuer_id,
                    as_of=snapshot.as_of.isoformat(),
                    basic_shares=str(snapshot.basic_shares),
                    dilutive_options=str(snapshot.dilutive_options),
                    warrants=str(snapshot.warrants),
                    rsus=str(snapshot.rsus),
                    convertible_shares=str(snapshot.convertible_shares),
                    other_dilutive_shares=str(snapshot.other_dilutive_shares),
                    expected_financing_shares=str(snapshot.expected_financing_shares),
                    fully_diluted_shares=str(snapshot.fully_diluted_shares),
                    projected_fully_diluted_shares=str(snapshot.projected_fully_diluted_shares),
                    basic_share_fact_id=str(snapshot.basic_share_fact_id),
                    evidence_ids_json=_json(snapshot.evidence_ids),
                    calculation_json=_json(snapshot.trace),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_cash_burn(self, snapshot: CashBurnSnapshot) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                CashBurnSnapshotRow(
                    id=row_id,
                    issuer_id=snapshot.issuer_id,
                    as_of=snapshot.as_of.isoformat(),
                    quarters_json=_json(snapshot.quarters),
                    method=snapshot.method,
                    confidence=snapshot.confidence,
                    normalized_quarterly_burn=str(snapshot.normalized_quarterly_burn),
                    calculation_json=_json(snapshot.trace),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_survival(self, snapshot: SurvivalSnapshot) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                SurvivalSnapshotRow(
                    id=row_id,
                    issuer_id=snapshot.issuer_id,
                    as_of=snapshot.as_of.isoformat(),
                    catalyst_latest_date=snapshot.catalyst_latest_date.isoformat(),
                    liquidity=str(snapshot.liquidity),
                    normalized_quarterly_burn=str(snapshot.normalized_quarterly_burn),
                    runway_months=str(snapshot.runway_months),
                    months_to_latest_catalyst=str(snapshot.months_to_latest_catalyst),
                    runway_at_catalyst_months=str(snapshot.runway_at_catalyst_months),
                    cash_position_evidence_ids_json=_json(snapshot.cash_position_evidence_ids),
                    burn_evidence_ids_json=_json(snapshot.burn_evidence_ids),
                    calculation_json=_json(snapshot.trace),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_financing_filing(self, filing: FinancingFiling) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                FinancingFilingRow(
                    id=row_id,
                    issuer_id=filing.issuer_id,
                    cik=filing.cik,
                    accession=filing.accession,
                    form=filing.form,
                    filing_date=filing.filing_date.isoformat(),
                    accepted_at=filing.accepted_at.isoformat(),
                    primary_document=filing.primary_document,
                    filing_url=filing.filing_url,
                    category=filing.category,
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_financing_facility(self, facility: FinancingFacility) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                FinancingFacilityRow(
                    id=row_id,
                    issuer_id=facility.issuer_id,
                    kind=facility.kind,
                    active=facility.active,
                    opened_at=facility.opened_at.isoformat(),
                    capacity_usd=str(facility.capacity_usd) if facility.capacity_usd else None,
                    used_usd=str(facility.used_usd) if facility.used_usd else None,
                    remaining_usd=(
                        str(facility.remaining_usd) if facility.remaining_usd else None
                    ),
                    observed_issuance_dependence=facility.observed_issuance_dependence,
                    management_guided_use_before_catalyst=(
                        facility.management_guided_use_before_catalyst
                    ),
                    evidence_ids_json=_json(facility.evidence_ids),
                    reviewer=facility.reviewer,
                    confirmed_at=facility.confirmed_at.isoformat(),
                    created_at=_now_iso(),
                )
            )
        return row_id

    def add_financing_risk_inputs(self, inputs: FinancingRiskInputs) -> str:
        row_id = str(uuid4())
        with self.database.session() as session:
            session.add(
                FinancingRiskSnapshotRow(
                    id=row_id,
                    issuer_id=inputs.issuer_id,
                    as_of=inputs.as_of.isoformat(),
                    inputs_json=_json(inputs),
                    calculation_json=_json(inputs.trace),
                    created_at=_now_iso(),
                )
            )
        return row_id


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        payload = value.model_dump(mode="json")  # type: ignore[attr-defined]
    elif isinstance(value, tuple):
        payload = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else str(item)
            for item in value
        ]
    else:
        payload = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
