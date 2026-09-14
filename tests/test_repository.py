from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from boe.enums import (
    ClaimConfidence,
    EvidenceTier,
    Exchange,
    LeadEconomicAssetType,
    SecurityKind,
)
from boe.evidence import Claim, EvidenceItem
from boe.repositories.database import (
    ClaimRow,
    Database,
    EvidenceItemRow,
    IssuerRow,
    Milestone2Repository,
    RawPayloadRow,
    SecurityRow,
    UniverseSnapshotRow,
)
from boe.storage.raw import FileRawPayloadStore
from boe.universe import (
    BusinessEvidence,
    ListingRecord,
    SecSubmissionProfile,
    UniverseClassificationInput,
    classify_universe,
)

NOW = datetime(2026, 9, 14, 20, tzinfo=UTC)


def test_repository_persists_identity_lineage_and_snapshot(tmp_path):
    database = Database.sqlite(tmp_path / "boe.db")
    database.create_schema()
    repository = Milestone2Repository(database)
    raw = FileRawPayloadStore(tmp_path / "raw").put(
        b"filing",
        source_url="https://www.sec.gov/example",
        retrieved_at=NOW,
        available_at=NOW,
        media_type="application/json",
    )
    repository.add_raw_payload(raw)
    evidence = EvidenceItem(
        id=uuid4(),
        evidence_type="SEC_SUBMISSION",
        source_tier=EvidenceTier.SEC_FILING,
        title="Filing",
        publisher="SEC",
        source_url="https://www.sec.gov/example",
        published_at=NOW,
        available_at=NOW,
        retrieved_at=NOW,
        accession_or_external_id="0001",
        raw_blob_sha256=raw.sha256,
        excerpt_locator="Item 1",
        supports_claim="Primary business",
        quality_flag=None,
    )
    repository.add_evidence(evidence)
    claim = Claim(
        id=uuid4(),
        subject_type="issuer",
        subject_id="0000000001",
        field_name="lead_asset_type",
        typed_value="THERAPEUTIC",
        evidence_id=evidence.id,
        valid_from=NOW,
        known_at=NOW,
        confidence=ClaimConfidence.HIGH,
    )
    repository.add_claim(claim)
    profile = SecSubmissionProfile(
        cik="0000000001",
        legal_name="BOE Example",
        sic="2834",
        sic_description="Pharmaceutical Preparations",
        entity_type="operating",
        filer_category="accelerated filer",
        country="DE",
        tickers=("BOEX",),
        exchanges=("Nasdaq",),
        latest_periodic_filing_date=date(2026, 8, 1),
        latest_periodic_form="10-Q",
        reporting_current=True,
        source_available_at=NOW,
    )
    listing = ListingRecord(
        ticker="BOEX",
        security_name="BOE Example Common Stock",
        exchange=Exchange.NASDAQ,
        exchange_code="Q",
        security_kind=SecurityKind.COMMON_STOCK,
        test_issue=False,
        etf=False,
        next_shares=False,
        financial_status=None,
        source_row=2,
    )
    business = BusinessEvidence(
        lead_economic_asset_type=LeadEconomicAssetType.THERAPEUTIC,
        active_therapeutic_assets=1,
        therapeutic_focus_share_pct=100,
        supporting_claim_ids=(str(claim.id),),
        rationale="Therapeutics are primary",
    )
    decision = classify_universe(
        UniverseClassificationInput(
            listing=listing, sec_profile=profile, business_evidence=business, as_of=NOW
        )
    )
    issuer_id = repository.upsert_issuer(
        profile, business, decision, source_raw_blob_sha256=raw.sha256
    )
    security_id = repository.upsert_security(issuer_id, listing, source_raw_blob_sha256=raw.sha256)
    repository.add_universe_snapshot(security_id, decision)

    assert repository.count(RawPayloadRow) == 1
    assert repository.count(EvidenceItemRow) == 1
    assert repository.count(ClaimRow) == 1
    assert repository.count(IssuerRow) == 1
    assert repository.count(SecurityRow) == 1
    assert repository.count(UniverseSnapshotRow) == 1
    repository.add_raw_payload(raw)
    assert repository.count(RawPayloadRow) == 1
    with pytest.raises(ValueError, match="append-only"):
        repository.add_claim(claim)

    bad_decision = decision.model_copy(update={"supporting_claim_ids": (str(uuid4()),)})
    with pytest.raises(ValueError, match="absent claims"):
        repository.add_universe_snapshot(security_id, bad_decision)
