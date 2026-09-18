"""Renders a filter_scan.py result as a single, self-contained HTML file.

No server, no build step, no external dependencies: the data is embedded
directly in the page, so opening the file (double-click, or a browser
pointed at the committed path in a private repo) is the entire viewing
experience. Deliberately not a claude.ai/hosted artifact - this file lives
in the repo itself, viewed locally or via GitHub, same as any other
committed report.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #ffffff; --fg: #1a1a1a; --muted: #6b7280; --border: #e5e7eb;
  --accent: #2563eb; --row-alt: #f9fafb; --warn-bg: #fff7ed; --warn-fg: #9a3412;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --fg: #e5e7eb; --muted: #9ca3af; --border: #2a2e37;
    --accent: #60a5fa; --row-alt: #171a21; --warn-bg: #2a1f14; --warn-fg: #fbbf24;
  }
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--fg); margin: 0; padding: 24px;
  font: 14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
}
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 4px; }
.disclaimer {
  background: var(--warn-bg); color: var(--warn-fg); border-radius: 8px;
  padding: 12px 16px; font-size: 13px; margin: 16px 0 24px; max-width: 900px;
}
table { border-collapse: collapse; width: 100%; margin-bottom: 32px; }
th, td {
  text-align: left; padding: 8px 10px;
  border-bottom: 1px solid var(--border); vertical-align: top;
}
th {
  cursor: pointer; user-select: none; white-space: nowrap;
  font-size: 12px; text-transform: uppercase; color: var(--muted);
}
th:hover { color: var(--accent); }
tbody tr:nth-child(even) { background: var(--row-alt); }
td.ticker { font-weight: 600; font-variant-numeric: tabular-nums; }
td.mono { font-variant-numeric: tabular-nums; white-space: nowrap; }
.sentence { color: var(--muted); font-size: 12.5px; max-width: 420px; }
a { color: var(--accent); }
details { margin-bottom: 20px; }
summary { cursor: pointer; font-weight: 600; }
summary .count { color: var(--muted); font-weight: 400; }
"""

_JS = """
document.querySelectorAll('table[data-sortable] th').forEach(function (th, idx) {
  th.addEventListener('click', function () {
    var table = th.closest('table');
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    var asc = th.dataset.sortDir !== 'asc';
    table.querySelectorAll('th').forEach(function (h) { delete h.dataset.sortDir; });
    th.dataset.sortDir = asc ? 'asc' : 'desc';
    rows.sort(function (a, b) {
      var av = a.children[idx].dataset.sort || a.children[idx].textContent.trim();
      var bv = b.children[idx].dataset.sort || b.children[idx].textContent.trim();
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  });
});
"""


def _cell(value: Any) -> str:
    return escape(str(value)) if value is not None else ""


def _watchlist_rows(watchlist: list[dict[str, Any]]) -> str:
    rows = []
    for row in watchlist:
        cash = row.get("cash_dilution_facts") or {}
        tech = row.get("technical_facts") or {}
        window = f"{row['window_start']}" + (
            f" to {row['window_end']}" if row["window_start"] != row["window_end"] else ""
        )
        rows.append(
            "<tr>"
            f'<td class="ticker">{_cell(row["ticker"])}</td>'
            f"<td>{_cell(row['company'])}</td>"
            f"<td>{_cell(row['catalyst_type'])}</td>"
            f'<td class="mono" data-sort="{_cell(row["window_start"])}">{_cell(window)}</td>'
            f"<td>{_cell(row['date_precision'])}</td>"
            f'<td class="mono">{_cell(row["objective_pos_low_pct"])}'
            f"-{_cell(row['objective_pos_high_pct'])}%</td>"
            f'<td class="mono">{_cell(cash.get("runway_months"))}</td>'
            f'<td class="mono">{_cell(tech.get("close"))}</td>'
            f'<td class="sentence">{_cell(row["source_sentence"])}</td>'
            f'<td><a href="{_cell(row["source_url"])}" target="_blank" '
            f'rel="noopener">source</a></td>'
            "</tr>"
        )
    return "\n".join(rows)


def _gap_section(title: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    items = "\n".join(
        f"<li><strong>{_cell(r.get('ticker'))}</strong> - "
        f"{_cell(r.get('reason') or r.get('source_sentence') or '')}</li>"
        for r in rows
    )
    return (
        f"<details><summary>{escape(title)} "
        f'<span class="count">({len(rows)})</span></summary>'
        f"<ul>{items}</ul></details>"
    )


def render_html(status: dict[str, Any]) -> str:
    watchlist = status["watchlist"]
    header_cols = (
        "Ticker",
        "Company",
        "Catalyst type",
        "Window",
        "Precision",
        "PoS range",
        "Runway (mo)",
        "Close",
        "Source sentence",
        "Link",
    )
    thead = "".join(f"<th>{escape(c)}</th>" for c in header_cols)
    gaps = "".join(
        [
            _gap_section("Already past (filtered out)", status.get("already_past", [])),
            _gap_section("Excluded - foreign private issuer", status["excluded_foreign_issuer"]),
            _gap_section("Financial data gaps", status["financial_data_gaps"]),
            _gap_section("Technical data gaps", status["technical_data_gaps"]),
            _gap_section("Discovery failures", status["discovery_failures"]),
        ]
    )
    # Escape "<" so a real filing sentence that happens to contain the
    # literal text "</script>" can never prematurely close this tag and
    # inject markup - < is a valid JSON string escape that decodes
    # back to "<" when parsed, so this is invisible to JSON.parse/embedded
    # data consumers, just not to the HTML tokenizer scanning for </script.
    embedded = json.dumps(status, default=str).replace("<", "\\u003c")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Catalyst filter watchlist</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Catalyst filter watchlist</h1>
<div class="meta">Generated {escape(status["as_of"])} - search window
{escape(status["search_window"]["start_date"])} to {escape(status["search_window"]["end_date"])}
- {len(watchlist)} candidates</div>
<div class="disclaimer">{escape(status["disclaimer"])}</div>
<table data-sortable>
<thead><tr>{thead}</tr></thead>
<tbody>
{_watchlist_rows(watchlist)}
</tbody>
</table>
{gaps}
<script id="filter-scan-data" type="application/json">{embedded}</script>
<script>{_JS}</script>
</body>
</html>
"""
