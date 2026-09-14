"""Load and cross-check BOE-1.0.0 repository contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from boe.enums import DataState, FactorCode
from boe.models import CandidateOutput, ScorecardContract


class ContractViolation(ValueError):
    """Raised when individually valid artifacts disagree with the frozen scorecard."""


@dataclass(frozen=True, slots=True)
class LoadedScorecard:
    contract: ScorecardContract
    raw_sha256: str
    canonical_sha256: str
    path: Path


def _read_json(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractViolation(f"invalid JSON in {path}: {exc}") from exc
    return raw, payload


def load_scorecard(path: str | Path) -> LoadedScorecard:
    resolved = Path(path).resolve()
    raw, payload = _read_json(resolved)
    try:
        contract = ScorecardContract.model_validate(payload)
    except ValidationError as exc:
        raise ContractViolation(f"invalid scorecard {resolved}: {exc}") from exc
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return LoadedScorecard(
        contract=contract,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        canonical_sha256=hashlib.sha256(canonical).hexdigest(),
        path=resolved,
    )


def load_candidate(path: str | Path) -> CandidateOutput:
    resolved = Path(path).resolve()
    _, payload = _read_json(resolved)
    try:
        return CandidateOutput.model_validate(payload)
    except ValidationError as exc:
        raise ContractViolation(f"invalid candidate {resolved}: {exc}") from exc


def validate_candidate_against_scorecard(
    candidate: CandidateOutput,
    loaded_scorecard: LoadedScorecard,
) -> None:
    scorecard = loaded_scorecard.contract
    if candidate.meta.rules_version != scorecard.version:
        raise ContractViolation("candidate rules version differs from scorecard")
    if candidate.meta.rules_checksum != loaded_scorecard.raw_sha256:
        raise ContractViolation("candidate rules checksum differs from scorecard file")

    definitions = {factor.code: factor for factor in scorecard.factors}
    for factor in candidate.score.factors:
        definition = definitions[factor.code]
        if factor.max_points != definition.max_points:
            raise ContractViolation(f"{factor.code}: factor maximum differs from scorecard")
        expected = {item.code: item.max_points for item in definition.subfactors}
        actual = {item.code: item.max_points for item in factor.subfactors}
        if actual != expected:
            raise ContractViolation(f"{factor.code}: subfactor contract differs from scorecard")

    observed_maximum = sum(
        subfactor.max_points
        for factor in candidate.score.factors
        for subfactor in factor.subfactors
        if subfactor.data_state is not DataState.MISSING
    )
    calculated_coverage = 100 * observed_maximum / scorecard.score_max
    if abs(calculated_coverage - candidate.meta.data_coverage_pct) > 1e-9:
        raise ContractViolation("candidate data coverage does not reconcile to subfactor states")

    factor_codes = {factor.code for factor in candidate.score.factors}
    if factor_codes != set(FactorCode):
        raise ContractViolation("candidate factor set differs from scorecard")

    classification_precedence = scorecard.classifications["precedence"]
    if candidate.decision.classification.value not in classification_precedence:
        raise ContractViolation("candidate classification is absent from scorecard precedence")
