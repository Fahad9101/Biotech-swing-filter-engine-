"""Regressions for the self-contained HTML watchlist report."""

from __future__ import annotations

from boe.filter.report import render_html

STATUS = {
    "as_of": "2026-09-18T09:00:00+00:00",
    "search_window": {"start_date": "2026-06-20", "end_date": "2026-09-18"},
    "watchlist_count": 1,
    "watchlist": [
        {
            "ticker": "CAPR",
            "company": "Capricor Therapeutics, Inc.",
            "catalyst_type": "REG_DECISION",
            "window_start": "2026-11-22",
            "window_end": "2026-11-22",
            "date_precision": "EXACT_DATE",
            "objective_pos_low_pct": "65",
            "objective_pos_high_pct": "85",
            "cash_dilution_facts": {"runway_months": "25.5"},
            "technical_facts": {"close": "23.17"},
            "source_sentence": 'PDUFA date of November 22, 2026 & "special" <chars>',
            "source_url": "https://www.sec.gov/example/capr.htm",
        }
    ],
    "excluded_foreign_issuer": [{"ticker": "CNTB", "reason": "20-F filer"}],
    "financial_data_gaps": [],
    "technical_data_gaps": [],
    "discovery_failures": [],
    "already_past": [
        {
            "ticker": "SYRE",
            "catalyst_type": "CLIN_P2",
            "window_end": "2026-09-08",
            "source_sentence": "reported topline results on September 8, 2026.",
        }
    ],
    "disclaimer": "Screening facts, not a recommendation.",
}


def test_render_html_embeds_watchlist_rows():
    html = render_html(STATUS)
    assert "CAPR" in html
    assert "Capricor Therapeutics, Inc." in html
    assert "REG_DECISION" in html
    assert "2026-11-22" in html
    assert 'href="https://www.sec.gov/example/capr.htm"' in html


def test_render_html_escapes_special_characters_in_the_rendered_table():
    html = render_html(STATUS)
    # the table cell must be escaped even though the raw JSON payload
    # embedded in the trailing <script type="application/json"> block
    # legitimately contains the unescaped original text (safe there: a
    # JSON script block is never parsed as markup or executed).
    table_html = html.split('<script id="filter-scan-data"')[0]
    assert "<chars>" not in table_html
    assert "&lt;chars&gt;" in table_html


def test_render_html_includes_gap_sections_with_counts():
    html = render_html(STATUS)
    assert "Excluded - foreign private issuer" in html
    assert "(1)" in html
    assert "Already past (filtered out)" in html
    assert "SYRE" in html


def test_render_html_omits_empty_gap_sections():
    html = render_html(STATUS)
    assert "Financial data gaps" not in html
    assert "Technical data gaps" not in html
    assert "Discovery failures" not in html


def test_render_html_embedded_json_cannot_break_out_of_its_script_tag():
    # A real filing sentence could, in principle, contain the literal text
    # "</script>" - if embedded naively, that would prematurely close the
    # data script tag and let the rest be parsed as markup/script.
    status = {**STATUS, "disclaimer": "Ends with </script><img src=x onerror=alert(1)>"}
    html = render_html(status)
    data_block = html.split('<script id="filter-scan-data"', 1)[1]
    assert "</script><img" not in data_block
    assert "\\u003c/script>" in data_block


def test_render_html_includes_disclaimer_and_is_self_contained():
    html = render_html(STATUS)
    assert "Screening facts, not a recommendation." in html
    assert "<html" in html and "</html>" in html
    assert "data-sortable" in html
    # no external script/style references - fully self-contained
    assert "<link " not in html
    assert 'src="http' not in html


SHORTLIST_STATUS = {
    **STATUS,
    "shortlist_definition": "SHORTLIST-1.0",
    "shortlist_count": 1,
    "shortlist": [
        {
            "ticker": "CAPR",
            "company": "Capricor Therapeutics, Inc.",
            "tier": 1,
            "catalyst_type": "REG_DECISION",
            "window_start": "2026-11-22",
            "window_end": "2026-11-22",
            "date_precision": "EXACT_DATE",
            "market_cap_usd": "548000000",
            "cash_dilution_facts": {"runway_at_catalyst_months": "20.6"},
            "technical_facts": {"close": "9.43", "rsi14": "52.3"},
            "flags": [],
            "exclusion_reasons": [],
            "source_url": "https://www.sec.gov/example/capr.htm",
        }
    ],
    "shortlist_not_selected": [
        {
            "ticker": "GILD",
            "tier": 1,
            "exclusion_reasons": ["MARKET_CAP_ABOVE_MAX"],
            "flags": [],
        }
    ],
}


def test_render_html_shows_shortlist_section_as_the_primary_view():
    html = render_html(SHORTLIST_STATUS)
    assert "<h2>Shortlist" in html
    assert "1 of 1, SHORTLIST-1.0" in html
    shortlist_block = html.split("<h2>Shortlist", 1)[1].split("<details>", 1)[0]
    assert "CAPR" in shortlist_block


def test_render_html_wraps_full_watchlist_in_collapsed_details_when_shortlist_present():
    html = render_html(SHORTLIST_STATUS)
    assert "<details>" in html
    assert "Full watchlist (unfiltered)" in html


def test_render_html_shows_not_selected_reasons():
    html = render_html(SHORTLIST_STATUS)
    assert "Not shortlisted" in html
    assert "GILD" in html
    assert "MARKET_CAP_ABOVE_MAX" in html


def test_render_html_without_shortlist_key_keeps_the_legacy_single_table_layout():
    html = render_html(STATUS)
    assert "<h2>Shortlist" not in html
    assert "Full watchlist (unfiltered)" not in html
    assert "Not shortlisted" not in html
