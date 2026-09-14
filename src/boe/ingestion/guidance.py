"""Conservative catalyst-guidance extraction from SEC and issuer primary-source text."""

from __future__ import annotations

import re
from datetime import date, datetime
from uuid import UUID

from boe.catalysts import CatalystObservation
from boe.enums import CatalystType, EvidenceTier, TimingConfidence

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_PATTERN = "|".join(_MONTHS)


class GuidanceExtractionError(ValueError):
    """Raised when a caller requests unsafe or ambiguous automatic guidance handling."""


def extract_catalyst_guidance(
    text: str,
    *,
    issuer_id: str,
    asset: str,
    indication: str,
    clinical_phase: str,
    evidence_id: UUID,
    source_tier: EvidenceTier,
    known_at: datetime,
) -> tuple[CatalystObservation, ...]:
    """Extract explicit future catalyst timing statements; never infer missing dates."""

    if source_tier not in {EvidenceTier.SEC_FILING, EvidenceTier.ISSUER_RELATIONS}:
        raise GuidanceExtractionError(
            "guidance extractor accepts SEC or issuer primary sources only"
        )
    sentences = _sentences(text)
    observations: list[CatalystObservation] = []
    for sentence in sentences:
        catalyst_type = _infer_catalyst_type(sentence, clinical_phase)
        if catalyst_type is None:
            continue
        window = _extract_window(sentence, known_at.date())
        if window is None:
            continue
        start, end, confidence = window
        if end < known_at.date():
            continue
        observations.append(
            CatalystObservation(
                issuer_id=issuer_id,
                asset=asset,
                indication=indication,
                catalyst_type=catalyst_type,
                clinical_phase=clinical_phase,
                title=sentence[:240],
                window_start=start,
                window_end=end,
                timing_confidence=confidence,
                evidence_id=evidence_id,
                source_tier=source_tier,
                known_at=known_at,
                source_statement=sentence,
            )
        )
    return tuple(observations)


def _sentences(text: str) -> tuple[str, ...]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return ()
    return tuple(item.strip() for item in _SENTENCE_RE.split(cleaned) if item.strip())


def _infer_catalyst_type(sentence: str, clinical_phase: str) -> CatalystType | None:
    lower = sentence.lower()
    if any(
        token in lower for token in ("pdufa", "fda decision", "regulatory decision", "action date")
    ):
        return CatalystType.REG_DECISION
    if any(token in lower for token in ("advisory committee", "adcom")):
        return CatalystType.REG_ADCOM
    if any(
        token in lower
        for token in (
            "submit",
            "submission",
            "file an nda",
            "file a bla",
            "nda filing",
            "bla filing",
        )
    ):
        return CatalystType.REG_SUBMIT
    if any(token in lower for token in ("topline", "top-line", "readout", "data", "results")):
        phase = clinical_phase.lower().replace(" ", "")
        if "2/3" in phase or "2-3" in phase:
            return CatalystType.CLIN_P2_3
        if "3" in phase:
            return CatalystType.CLIN_P3
        if "1/2" in phase or "1-2" in phase:
            return CatalystType.CLIN_P1_2
        if "2" in phase:
            return CatalystType.CLIN_P2
        if "1" in phase:
            return CatalystType.CLIN_P1
        return CatalystType.CONF_DATA
    if any(token in lower for token in ("conference", "congress", "meeting presentation")):
        return CatalystType.CONF_DATA
    return None


def _extract_window(sentence: str, known_on: date) -> tuple[date, date, TimingConfidence] | None:
    lower = sentence.lower()
    exact = re.search(
        rf"\b({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b",
        lower,
    )
    if exact:
        day = int(exact.group(2))
        value = date(int(exact.group(3)), _MONTHS[exact.group(1)], day)
        return value, value, TimingConfidence.HIGH

    month = re.search(rf"\b({_MONTH_PATTERN})\s+(20\d{{2}})\b", lower)
    if month:
        year = int(month.group(2))
        month_number = _MONTHS[month.group(1)]
        start = date(year, month_number, 1)
        end = _month_end(year, month_number)
        return start, end, TimingConfidence.MODERATE

    quarter = re.search(r"\b(?:q([1-4])|([1-4])q)\s*(20\d{2})\b", lower)
    if quarter:
        quarter_number = int(quarter.group(1) or quarter.group(2))
        year = int(quarter.group(3))
        first_month = 1 + (quarter_number - 1) * 3
        return (
            date(year, first_month, 1),
            _month_end(year, first_month + 2),
            TimingConfidence.MODERATE,
        )

    half = re.search(r"\b(?:h([12])|([12])h)\s*(20\d{2})\b", lower)
    if half:
        half_number = int(half.group(1) or half.group(2))
        year = int(half.group(3))
        if half_number == 1:
            return date(year, 1, 1), date(year, 6, 30), TimingConfidence.LOW
        return date(year, 7, 1), date(year, 12, 31), TimingConfidence.LOW

    end_year = re.search(r"\b(?:by|before|through) (?:the )?end of (20\d{2})\b", lower)
    if end_year:
        year = int(end_year.group(1))
        start = known_on if known_on.year == year else date(year, 1, 1)
        if start <= date(year, 12, 31):
            return start, date(year, 12, 31), TimingConfidence.LOW
    return None


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(date(year, month + 1, 1).toordinal() - 1)
