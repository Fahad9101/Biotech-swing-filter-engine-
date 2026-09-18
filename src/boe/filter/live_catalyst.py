"""Real, live CATALYST facts for a discovered forward-catalyst candidate.

Reuses scoring.py::score_catalyst unchanged, with the exact TIMING_CONFIDENCE
mapping already established and tested at scale in Milestone 7: FDA
regulatory target-action dates are set by statute/policy upon filing
acceptance and are public record (HIGH); company-guided clinical-trial
readout timing is well documented industry-wide to be subject to real
slippage (MODERATE). This is a property of the catalyst type, not an
opinion about any specific company.

MATERIALITY and NOVEL_INFORMATION are always MISSING, same as Milestone 7:
judging how important a specific catalyst is to the company, or whether a
disclosure is genuinely new information, needs reading the actual protocol
or filing in depth - a real judgment call, not fabricated here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from boe.enums import CatalystType, DataState, TimingConfidence
from boe.filter.extraction import DiscoveredCatalyst
from boe.models import FactorScore, ScorecardContract
from boe.scoring import (
    CatalystScoreInput,
    SubfactorEvidence,
    _derived_maturity_bucket,
    score_catalyst,
)

_HIGH_CONFIDENCE_TYPES = {
    CatalystType.REG_SUBMIT,
    CatalystType.REG_ADCOM,
    CatalystType.REG_DECISION,
    CatalystType.CONF_DATA,
    CatalystType.PUBLICATION,
}


def _timing_confidence(catalyst_type: CatalystType) -> TimingConfidence:
    return (
        TimingConfidence.HIGH
        if catalyst_type in _HIGH_CONFIDENCE_TYPES
        else TimingConfidence.MODERATE
    )


def _evidence(rationale: str, evidence_id_seed: str, *, missing: bool) -> SubfactorEvidence:
    if missing:
        return SubfactorEvidence(data_state=DataState.MISSING, rationale=rationale, evidence_ids=())
    return SubfactorEvidence(
        data_state=DataState.DERIVED,
        rationale=rationale,
        evidence_ids=(uuid5(NAMESPACE_URL, evidence_id_seed),),
    )


def live_catalyst_score(
    candidate: DiscoveredCatalyst,
    *,
    as_of: datetime,
    rules: ScorecardContract,
    candidate_id: str,
) -> FactorScore:
    timing_confidence = _timing_confidence(candidate.catalyst_type)
    score_input = CatalystScoreInput(
        as_of=as_of,
        catalyst_type=candidate.catalyst_type,
        window_start=candidate.window_start,
        timing_confidence=timing_confidence,
        materiality_points=None,
        novelty_points=None,
        maturity_bucket=_derived_maturity_bucket(candidate.catalyst_type),
        evidence={
            "TIMING_CONFIDENCE": _evidence(
                f"{timing_confidence.value} - structural property of catalyst_type "
                f"{candidate.catalyst_type.value}, not a per-candidate judgment.",
                f"filter-timing-{candidate_id}",
                missing=False,
            ),
            "PROXIMITY": _evidence(
                f"window_start={candidate.window_start.isoformat()} extracted from a real, "
                f'self-disclosed company statement: "{candidate.source_sentence}" '
                f"({candidate.source_url}).",
                f"filter-proximity-{candidate_id}",
                missing=False,
            ),
            "MATURITY": _evidence(
                f"derived from catalyst_type {candidate.catalyst_type.value}.",
                f"filter-maturity-{candidate_id}",
                missing=False,
            ),
            "MATERIALITY": _evidence(
                "Not assessed: how important this specific catalyst is to the company "
                "requires reading the actual trial protocol or filing in depth.",
                f"filter-materiality-{candidate_id}",
                missing=True,
            ),
            "NOVEL_INFORMATION": _evidence(
                "Not assessed: whether this disclosure is genuinely new information "
                "requires tracking this company's prior disclosures over time.",
                f"filter-novelty-{candidate_id}",
                missing=True,
            ),
        },
    )
    return score_catalyst(score_input, rules)
