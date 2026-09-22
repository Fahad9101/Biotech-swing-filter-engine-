"""Renders the FORWARD-LOG-1.0 entries + summary as a self-contained HTML
page, same pattern as boe.filter.report: no server, no build step, data
embedded directly so opening the committed file is the whole experience.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from boe.filter.report import REPORT_CSS, REPORT_JS, render_cell

_SUMMARY_COLS = (
    "Week",
    "Measured",
    "Hit 20%+ (close)",
    "Hit rate",
    "Hit 20%+ (peak)",
    "Peak hit rate",
    "Mean return",
    "Mean vs XBI",
)

_ENTRY_COLS = (
    "Ticker",
    "Company",
    "Tier",
    "Catalyst type",
    "Entry date",
    "Entry close",
    "Weeks measured",
    "Latest return",
    "Latest vs XBI",
)


def _summary_rows(summary: dict[str, Any]) -> str:
    rows = []
    for week, stats in summary["by_checkpoint_week"].items():
        if not stats.get("measured_count"):
            rows.append(
                f"<tr><td class='mono'>{render_cell(week)}</td><td class='mono'>0</td>"
                "<td colspan='6' class='sentence'>Not enough entries have reached this "
                "checkpoint yet.</td></tr>"
            )
            continue
        rows.append(
            "<tr>"
            f"<td class='mono'>{render_cell(week)}</td>"
            f"<td class='mono'>{render_cell(stats['measured_count'])}</td>"
            f"<td class='mono'>{render_cell(stats['hit_20pct_count'])}</td>"
            f"<td class='mono'>{render_cell(stats['hit_20pct_rate_pct'])}%</td>"
            f"<td class='mono'>{render_cell(stats['peak_hit_20pct_count'])}</td>"
            f"<td class='mono'>{render_cell(stats['peak_hit_20pct_rate_pct'])}%</td>"
            f"<td class='mono'>{render_cell(stats['mean_return_pct'])}%</td>"
            f"<td class='mono'>{render_cell(stats['mean_relative_return_pct'])}%</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _latest_checkpoint(entry: dict[str, Any]) -> dict[str, Any] | None:
    checkpoints = entry.get("checkpoints") or {}
    if not checkpoints:
        return None
    latest_week = max(int(w) for w in checkpoints)
    return checkpoints[str(latest_week)]  # type: ignore[no-any-return]


def _entry_rows(entries: list[dict[str, Any]]) -> str:
    rows = []
    for entry in entries:
        latest = _latest_checkpoint(entry)
        weeks_measured = ", ".join(sorted(entry.get("checkpoints") or {}, key=int)) or "-"
        entry_date_cell = render_cell(entry["entry_date"])
        rows.append(
            "<tr>"
            f"<td class='ticker'>{render_cell(entry['ticker'])}</td>"
            f"<td>{render_cell(entry.get('company'))}</td>"
            f"<td class='mono'>{render_cell(entry['tier'])}</td>"
            f"<td>{render_cell(entry['catalyst_type'])}</td>"
            f"<td class='mono' data-sort='{entry_date_cell}'>{entry_date_cell}</td>"
            f"<td class='mono'>{render_cell(entry['entry_close'])}</td>"
            f"<td class='mono'>{render_cell(weeks_measured)}</td>"
            f"<td class='mono'>{render_cell(latest['return_pct'] if latest else '')}"
            f"{'%' if latest else ''}</td>"
            f"<td class='mono'>{render_cell(latest['relative_return_pct'] if latest else '')}"
            f"{'%' if latest else ''}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_forward_log_html(entries: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    summary_thead = "".join(f"<th>{escape(c)}</th>" for c in _SUMMARY_COLS)
    entry_thead = "".join(f"<th>{escape(c)}</th>" for c in _ENTRY_COLS)
    embedded = json.dumps({"entries": entries, "summary": summary}, default=str).replace(
        "<", "\\u003c"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catalyst shortlist forward log</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<h1>Shortlist forward-measurement log</h1>
<div class="meta">{summary["forward_log_definition"]} - {summary["entry_count"]} entries logged
total</div>
<div class="disclaimer">Tracks how SHORTLIST-1.0 candidates actually perform after being
shortlisted, checked at 1/2/4/8/12 weeks against their own entry price and against XBI over
the same span. Entry prices are frozen the day a candidate first appears in the shortlist and
never recomputed. This is a measurement, not a signal: with few entries measured so far, these
numbers are not yet meaningful and should not be read as evidence either way until the sample
grows over the coming weeks.</div>
<h2>Summary by checkpoint</h2>
<table data-sortable>
<thead><tr>{summary_thead}</tr></thead>
<tbody>
{_summary_rows(summary)}
</tbody>
</table>
<h2>All logged entries</h2>
<table data-sortable>
<thead><tr>{entry_thead}</tr></thead>
<tbody>
{_entry_rows(entries)}
</tbody>
</table>
<script id="forward-log-data" type="application/json">{embedded}</script>
<script>{REPORT_JS}</script>
</body>
</html>
"""
