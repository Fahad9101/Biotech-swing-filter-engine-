"""Extracts real, company-self-disclosed forward-catalyst date windows from
SEC filing text (8-K press-release exhibits found via EDGAR full-text
search - see boe.ingestion.edgar_fts).

Precision is reported honestly rather than forced to a single point date:
a PDUFA disclosure is usually an exact date ("November 27, 2026"), while a
clinical-trial readout is often only guided to a quarter ("Q4 2026") or a
bare year ("in 2027"). The extracted window_start/window_end always spans
the true uncertainty of what was actually disclosed - never narrowed to a
single fabricated day.

Regex-based, not an LLM extraction: every match is traceable to the exact
sentence it came from (source_sentence), so a human can verify each one
against the real filing rather than trust a black box.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from boe.enums import CatalystType

_MONTH_NAMES = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_EXACT_DATE_RE = re.compile(rf"\b({_MONTH_NAMES})\s+(\d{{1,2}}),?\s+(\d{{4}})\b")
_QUARTER_RE = re.compile(
    r"\b(first|second|third|fourth|1st|2nd|3rd|4th|Q1|Q2|Q3|Q4)\s+(?:quarter\s+of\s+)?(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

_QUARTER_ORDINALS = {
    "first": 1,
    "1st": 1,
    "q1": 1,
    "second": 2,
    "2nd": 2,
    "q2": 2,
    "third": 3,
    "3rd": 3,
    "q3": 3,
    "fourth": 4,
    "4th": 4,
    "q4": 4,
}

# Real press-release sentences run well under this even when compound
# (the longest genuine example found in development - a PDUFA-extension
# sentence naming two dates, a BLA, and an indication - is ~260 chars).
# Fragments longer than this are reliably not a real single sentence: they
# are what re.split(r"(?<=[.!?])\s+", ...) produces when it hits investor-
# deck/table HTML with little or no real sentence punctuation to split on
# (confirmed empirically: a live scan found 56/83 raw candidates over 400
# chars, versus a clean genuine-press-release median under 150). Skipping
# them is honest - extracting a plausible-looking date from a slide-deck
# blob would be a real false positive, not a lower-confidence real fact.
MAX_SENTENCE_LENGTH = 400

REG_TRIGGERS: tuple[str, ...] = (
    "PDUFA",
    "target action date",
    "Complete Response Letter",
    "Advisory Committee",
    "Priority Review",
)
CLINICAL_TRIGGERS: tuple[str, ...] = (
    "topline",
    "top-line",
    "readout",
    "primary endpoint data",
    "interim analysis",
    "interim data",
    "data update",
    "complete enrollment",
)


class DatePrecision(StrEnum):
    EXACT_DATE = "EXACT_DATE"
    QUARTER = "QUARTER"
    YEAR = "YEAR"


@dataclass(frozen=True, slots=True)
class ExtractedWindow:
    window_start: date
    window_end: date
    precision: DatePrecision
    matched_text: str


@dataclass(frozen=True, slots=True)
class DiscoveredCatalyst:
    ticker: str
    cik: str
    company: str
    catalyst_type: CatalystType
    window_start: date
    window_end: date
    precision: DatePrecision
    trigger_phrase: str
    source_sentence: str
    source_url: str
    filing_date: date | None


def extract_date_window(text: str) -> ExtractedWindow | None:
    """Finds the most specific real date expression in `text`, preferring
    an exact calendar date over a quarter over a bare year. When a sentence
    names multiple exact dates (e.g. "extended from August 22, 2026 to
    November 22, 2026"), the LAST one is taken as the current target - a
    revision/extension is always disclosed old-date-then-new-date, never
    the reverse, in every real filing sentence seen during development."""
    exact_matches = list(_EXACT_DATE_RE.finditer(text))
    if exact_matches:
        exact = exact_matches[-1]
        month_name, day_str, year_str = exact.groups()
        month = list(calendar.month_name).index(month_name)
        try:
            found = date(int(year_str), month, int(day_str))
        except ValueError:
            found = None
        if found is not None:
            return ExtractedWindow(
                window_start=found,
                window_end=found,
                precision=DatePrecision.EXACT_DATE,
                matched_text=exact.group(0),
            )

    quarter = _QUARTER_RE.search(text)
    if quarter is not None:
        ordinal_text, year_str = quarter.groups()
        q = _QUARTER_ORDINALS[ordinal_text.lower()]
        year = int(year_str)
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        return ExtractedWindow(
            window_start=date(year, start_month, 1),
            window_end=date(year, end_month, calendar.monthrange(year, end_month)[1]),
            precision=DatePrecision.QUARTER,
            matched_text=quarter.group(0),
        )

    year_match = _YEAR_RE.search(text)
    if year_match is not None:
        year = int(year_match.group(1))
        return ExtractedWindow(
            window_start=date(year, 1, 1),
            window_end=date(year, 12, 31),
            precision=DatePrecision.YEAR,
            matched_text=year_match.group(0),
        )

    return None


def _sentences(text: str) -> list[str]:
    normalized = re.sub(r"<[^>]+>", " ", text)
    normalized = re.sub(r"&#8226;|&#x2022;|•", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    fragments = (s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized))
    return [s for s in fragments if s and len(s) <= MAX_SENTENCE_LENGTH]


def _classify_trigger(sentence: str) -> tuple[str, CatalystType] | None:
    lowered = sentence.lower()
    for trigger in REG_TRIGGERS:
        if trigger.lower() not in lowered:
            continue
        # "Advisory Committee" alone is ambiguous - companies also host
        # their own internal medical/KOL advisory boards (confirmed as a
        # real false match in live testing: "we hosted an advisory
        # committee meeting with... key opinion leaders"). PDUFA/target
        # action date/CRL/Priority Review are FDA-specific terms with no
        # such alternate meaning and need no extra check.
        if trigger == "Advisory Committee" and "fda" not in lowered:
            continue
        return trigger, CatalystType.REG_DECISION
    for trigger in CLINICAL_TRIGGERS:
        if trigger.lower() in lowered:
            is_phase_3 = any(
                marker in lowered
                for marker in ("phase 3", "phase iii", "registrational", "pivotal")
            )
            catalyst_type = CatalystType.CLIN_P3 if is_phase_3 else CatalystType.CLIN_P2
            return trigger, catalyst_type
    return None


def extract_candidates(
    *,
    ticker: str,
    cik: str,
    company: str,
    document_text: str,
    source_url: str,
    filing_date: date | None,
) -> tuple[DiscoveredCatalyst, ...]:
    results: list[DiscoveredCatalyst] = []
    seen: set[tuple[CatalystType, date, date]] = set()
    for sentence in _sentences(document_text):
        classified = _classify_trigger(sentence)
        if classified is None:
            continue
        trigger, catalyst_type = classified
        window = extract_date_window(sentence)
        if window is None:
            continue
        key = (catalyst_type, window.window_start, window.window_end)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            DiscoveredCatalyst(
                ticker=ticker,
                cik=cik,
                company=company,
                catalyst_type=catalyst_type,
                window_start=window.window_start,
                window_end=window.window_end,
                precision=window.precision,
                trigger_phrase=trigger,
                source_sentence=sentence,
                source_url=source_url,
                filing_date=filing_date,
            )
        )
    return tuple(results)
