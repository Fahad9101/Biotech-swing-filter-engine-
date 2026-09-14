from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def scorecard_path(repository_root: Path) -> Path:
    return repository_root / "contracts" / "boe-scorecard.v1.0.0.json"


@pytest.fixture(scope="session")
def candidate_path(repository_root: Path) -> Path:
    return repository_root / "tests" / "fixtures" / "valid_candidate.json"
