from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from boe.enums import ClaimConfidence, ClaimStatus, EvidenceTier
from boe.evidence import (
    Claim,
    EvidenceConflict,
    EvidenceItem,
    LookAheadViolation,
    claims_as_of,
)
from boe.storage.raw import FileRawPayloadStore

NOW = datetime(2026, 9, 14, 20, tzinfo=UTC)


def _evidence(*, available_at: datetime = NOW) -> EvidenceItem:
    return EvidenceItem(
        id=uuid4(),
        evidence_type="SEC_SUBMISSION",
        source_tier=EvidenceTier.SEC_FILING,
        title="Issuer filing",
        publisher="SEC",
        source_url="https://www.sec.gov/example",
        published_at=available_at,
        available_at=available_at,
        retrieved_at=NOW + timedelta(hours=1),
        accession_or_external_id="0001",
        raw_blob_sha256="a" * 64,
        excerpt_locator="Item 1",
        supports_claim="Primary business is therapeutics",
        quality_flag=None,
    )


def _claim(evidence_id, value, *, known_at=NOW) -> Claim:
    return Claim(
        id=uuid4(),
        subject_type="issuer",
        subject_id="0000000001",
        field_name="lead_asset_type",
        typed_value=value,
        evidence_id=evidence_id,
        valid_from=known_at,
        known_at=known_at,
        confidence=ClaimConfidence.HIGH,
        status=ClaimStatus.ACTIVE,
    )


def test_content_addressed_raw_store_is_idempotent(tmp_path):
    store = FileRawPayloadStore(tmp_path / "raw")
    first = store.put(
        b"immutable",
        source_url="https://www.sec.gov/example",
        retrieved_at=NOW,
        available_at=NOW,
        media_type="application/json",
    )
    second = store.put(
        b"immutable",
        source_url="https://www.sec.gov/example",
        retrieved_at=NOW,
        available_at=NOW,
        media_type="application/json",
    )

    assert first.sha256 == second.sha256
    assert store.read(first.sha256) == b"immutable"
    with pytest.raises(ValueError, match="invalid SHA"):
        store.read("../escape")

    (store.root / first.relative_path).write_bytes(b"corrupted")
    with pytest.raises(RuntimeError, match="integrity"):
        store.read(first.sha256)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.put(
            b"naive",
            source_url="https://www.sec.gov/example",
            retrieved_at=datetime(2026, 9, 14),
            available_at=datetime(2026, 9, 14),
            media_type=None,
        )


def test_claim_resolution_prevents_lookahead_and_selects_latest():
    evidence = _evidence()
    earlier = _claim(evidence.id, "UNKNOWN", known_at=NOW - timedelta(days=1))
    latest = _claim(evidence.id, "THERAPEUTIC")

    assert claims_as_of((earlier, latest), (evidence,), NOW) == (latest,)
    with pytest.raises(LookAheadViolation):
        claims_as_of((latest,), (evidence,), NOW - timedelta(seconds=1))


def test_equally_current_conflicting_claims_fail_closed():
    evidence = _evidence()
    with pytest.raises(EvidenceConflict):
        claims_as_of(
            (_claim(evidence.id, "A"), _claim(evidence.id, "B")),
            (evidence,),
            NOW,
        )
