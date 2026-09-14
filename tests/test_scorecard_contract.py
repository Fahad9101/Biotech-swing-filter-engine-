import hashlib

import pytest

from boe.contracts import ContractViolation, load_scorecard
from boe.enums import CatalystType, Classification, FactorCode


def test_scorecard_loads_and_hashes_exact_file(scorecard_path):
    loaded = load_scorecard(scorecard_path)

    assert loaded.contract.version == "BOE-1.0.0"
    assert loaded.contract.score_max == 100
    assert loaded.raw_sha256 == hashlib.sha256(scorecard_path.read_bytes()).hexdigest()
    assert len(loaded.canonical_sha256) == 64


def test_scorecard_contains_closed_taxonomies(scorecard_path):
    contract = load_scorecard(scorecard_path).contract

    assert {factor.code for factor in contract.factors} == set(FactorCode)
    assert set(contract.catalyst_types) == set(CatalystType)
    assert set(contract.classifications["precedence"]) == {item.value for item in Classification}


def test_scorecard_rejects_modified_maximum(tmp_path, scorecard_path):
    text = scorecard_path.read_text().replace('"score_max": 100', '"score_max": 99')
    changed = tmp_path / "changed.json"
    changed.write_text(text)

    with pytest.raises(ContractViolation, match="score_max"):
        load_scorecard(changed)
