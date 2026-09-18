"""Regressions for real-filing forward-catalyst extraction.

Sentences below are copied verbatim (HTML-entity-decoded) from real SEC
8-K exhibits fetched live during development (2026-09-18) - not invented,
so the regexes are proven against genuine, messy company language.
"""

from __future__ import annotations

from datetime import date

from boe.enums import CatalystType
from boe.filter.extraction import (
    MAX_SENTENCE_LENGTH,
    DatePrecision,
    extract_candidates,
    extract_date_window,
)

CAPRICOR_SENTENCE = (
    "Food and Drug Administration (FDA) has extended the Prescription Drug User Fee Act "
    "(PDUFA) target action date for its Biologics License Application (BLA) for Deramiocel, "
    "an investigational cell therapy for Duchenne muscular dystrophy (DMD), from August 22, "
    "2026 to November 22, 2026."
)

BRIDGEBIO_TEXT = (
    "On May 27, 2026, the FDA accepted the Company's New Drug Application (NDA) for BBP-418 "
    "and granted Priority Review, assigning a Prescription Drug User Fee Act (PDUFA) target "
    "action date of November 27, 2026. The FDA re-considered its review designation of the "
    "Company's NDA filing for encaleret in ADH1 and has granted Priority Review, with a PDUFA "
    "target action date of May 8, 2027."
)

COGENT_TEXT = (
    "Potential FDA approval of bezuclastinib in GIST - PDUFA date of November 30, 2026. "
    "Potential FDA approval of bezuclastinib in NonAdvSM - PDUFA date of December 30, 2026."
)

PRAXIS_QUARTER_SENTENCE = (
    "Topline results are anticipated in the fourth quarter of 2026 and assuming successful "
    "initial NDA approval of relutrigine, the EMERALD study, if positive, would serve as the "
    "basis for a supplemental NDA submission in 2027."
)

PRAXIS_YEAR_SENTENCE = (
    "Enrollment in the EMBRAVE3 registrational trial is progressing, with topline results "
    "expected in 2027."
)


def test_extract_date_window_prefers_the_last_exact_date_in_a_revision_sentence():
    window = extract_date_window(CAPRICOR_SENTENCE)
    assert window is not None
    assert window.precision == DatePrecision.EXACT_DATE
    assert window.window_start == window.window_end == date(2026, 11, 22)


def test_extract_date_window_handles_quarter_precision():
    window = extract_date_window(PRAXIS_QUARTER_SENTENCE)
    assert window is not None
    assert window.precision == DatePrecision.QUARTER
    assert window.window_start == date(2026, 10, 1)
    assert window.window_end == date(2026, 12, 31)


def test_extract_date_window_handles_bare_year_precision():
    window = extract_date_window("topline results expected in 2027.")
    assert window is not None
    assert window.precision == DatePrecision.YEAR
    assert window.window_start == date(2027, 1, 1)
    assert window.window_end == date(2027, 12, 31)


def test_extract_date_window_returns_none_without_any_date():
    assert extract_date_window("We remain confident in our pipeline execution.") is None


def test_extract_candidates_finds_the_real_capricor_pdufa_extension():
    candidates = extract_candidates(
        ticker="CAPR",
        cik="0001133869",
        company="Capricor Therapeutics, Inc.",
        document_text=CAPRICOR_SENTENCE,
        source_url="https://www.sec.gov/example/capr.htm",
        filing_date=date(2026, 8, 24),
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.catalyst_type == CatalystType.REG_DECISION
    assert candidate.window_start == date(2026, 11, 22)
    assert candidate.precision == DatePrecision.EXACT_DATE
    assert candidate.trigger_phrase == "PDUFA"


def test_extract_candidates_finds_two_distinct_real_pdufa_dates_in_one_filing():
    candidates = extract_candidates(
        ticker="BBIO",
        cik="0001743881",
        company="BridgeBio Pharma, Inc.",
        document_text=BRIDGEBIO_TEXT,
        source_url="https://www.sec.gov/example/bbio.htm",
        filing_date=date(2026, 8, 10),
    )
    dates = sorted(c.window_start for c in candidates)
    assert dates == [date(2026, 11, 27), date(2027, 5, 8)]
    assert all(c.catalyst_type == CatalystType.REG_DECISION for c in candidates)


def test_extract_candidates_finds_two_distinct_indications_same_drug():
    candidates = extract_candidates(
        ticker="COGT",
        cik="0001622229",
        company="Cogent Biosciences, Inc.",
        document_text=COGENT_TEXT,
        source_url="https://www.sec.gov/example/cogt.htm",
        filing_date=date(2026, 8, 10),
    )
    dates = sorted(c.window_start for c in candidates)
    assert dates == [date(2026, 11, 30), date(2026, 12, 30)]


def test_extract_candidates_classifies_registrational_trial_as_phase_3():
    candidates = extract_candidates(
        ticker="PRAX",
        cik="0001689548",
        company="Praxis Precision Medicines, Inc.",
        document_text=PRAXIS_YEAR_SENTENCE,
        source_url="https://www.sec.gov/example/prax.htm",
        filing_date=date(2026, 8, 6),
    )
    assert len(candidates) == 1
    assert candidates[0].catalyst_type == CatalystType.CLIN_P3
    assert candidates[0].precision == DatePrecision.YEAR


def test_extract_candidates_deduplicates_identical_sentence_repeats():
    doubled = CAPRICOR_SENTENCE + " " + CAPRICOR_SENTENCE
    candidates = extract_candidates(
        ticker="CAPR",
        cik="0001133869",
        company="Capricor Therapeutics, Inc.",
        document_text=doubled,
        source_url="https://www.sec.gov/example/capr.htm",
        filing_date=date(2026, 8, 24),
    )
    assert len(candidates) == 1


def test_extract_candidates_skips_oversized_non_prose_fragments():
    # Simulates a slide-deck/table exhibit with no real sentence
    # punctuation: a single huge run-on fragment containing a trigger and
    # a date, which is not a genuine disclosure sentence.
    noisy = "PDUFA " + ("filler bullet content without periods " * 20) + "November 22, 2026"
    assert len(noisy) > MAX_SENTENCE_LENGTH
    candidates = extract_candidates(
        ticker="XYZ",
        cik="0000000001",
        company="Example Biotech",
        document_text=noisy,
        source_url="https://www.sec.gov/example/xyz.htm",
        filing_date=None,
    )
    assert candidates == ()


def test_extract_candidates_ignores_sentences_without_a_trigger():
    candidates = extract_candidates(
        ticker="XYZ",
        cik="0000000001",
        company="Example Biotech",
        document_text="We reported strong quarterly revenue growth of 12%.",
        source_url="https://www.sec.gov/example/xyz.htm",
        filing_date=None,
    )
    assert candidates == ()
