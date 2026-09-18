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
