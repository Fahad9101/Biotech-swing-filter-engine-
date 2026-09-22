"""Regressions for the self-contained forward-measurement log HTML report."""

from __future__ import annotations

from boe.filter.forward_log import summarize
from boe.filter.forward_report import render_forward_log_html

ENTRIES = [
    {
        "candidate_id": "CAPR-REG_DECISION-2026-11-22",
        "ticker": "CAPR",
        "company": "Capricor Therapeutics, Inc.",
        "catalyst_type": "REG_DECISION",
        "tier": 1,
        "entry_date": "2026-09-22",
        "entry_close": "9.43",
        "entry_xbi_close": "95.00",
        "checkpoints": {
            "1": {
                "week": 1,
                "return_pct": "12.50",
                "relative_return_pct": "10.00",
                "hit_20pct_at_checkpoint": False,
                "peak_hit_20pct": False,
            }
        },
    },
    {
        "candidate_id": "AAA-CLIN_P2-2026-10-01",
        "ticker": "AAA",
        "company": "Example Bio & <Research>",
        "catalyst_type": "CLIN_P2",
        "tier": 2,
        "entry_date": "2026-09-22",
        "entry_close": "5.00",
        "entry_xbi_close": "95.00",
        "checkpoints": {},
    },
]


def test_render_forward_log_html_includes_summary_and_entries():
    summary = summarize(ENTRIES)
    html = render_forward_log_html(ENTRIES, summary)
    assert "CAPR" in html
    assert "AAA" in html
    assert "FORWARD-LOG-1.0" in html
    assert "12.50" in html


def test_render_forward_log_html_shows_not_yet_measured_for_empty_checkpoints():
    summary = summarize(ENTRIES)
    html = render_forward_log_html(ENTRIES, summary)
    assert "Not enough entries have reached this checkpoint yet." in html


def test_render_forward_log_html_escapes_company_names():
    summary = summarize(ENTRIES)
    html = render_forward_log_html(ENTRIES, summary)
    table_html = html.split('<script id="forward-log-data"')[0]
    assert "<Research>" not in table_html
    assert "&lt;Research&gt;" in table_html


def test_render_forward_log_html_is_self_contained():
    summary = summarize(ENTRIES)
    html = render_forward_log_html(ENTRIES, summary)
    assert "<html" in html and "</html>" in html
    assert "<link " not in html
    assert 'src="http' not in html
