"""Shortlist forward-measurement run.

Reads the shortlist just produced by filter_scan.py, freezes a forward-log
entry for every candidate seen there for the first time, and measures any
checkpoints (1/2/4/8/12 weeks after a candidate's own entry date) that have
come due for entries already being tracked - all from real Alpaca daily
bars, all reasons for a missing measurement recorded rather than silently
dropped.

This is the machinery for answering "does SHORTLIST-1.0 actually work?"
over a genuinely non-repeatable 10-12 week window - see
boe.filter.forward_log for the design rules (frozen entry prices, no
score, no filtering feedback into future scans).

Run manually, or as the second step of the same scheduled workflow that
runs filter_scan.py (it must run after filter_scan.py has written
reports/watchlist.json for this cycle). Not exercised by CI - live network
calls throughout.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.filter.forward_log import (  # noqa: E402
    due_checkpoints,
    measure_checkpoint,
    record_new_entries,
    summarize,
)
from boe.filter.forward_report import render_forward_log_html  # noqa: E402
from boe.ingestion.alpaca import credentials_from_env, fetch_daily_bars  # noqa: E402
from boe.market import MarketSeries  # noqa: E402

BENCHMARK_SYMBOL = "XBI"
DEFAULT_WATCHLIST_PATH = "reports/watchlist.json"
DEFAULT_OUTPUT_DIR = "reports/forward-log"
FETCH_BUFFER_DAYS = 5  # covers weekends/holidays around the entry date itself


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def _fetch_full_series(
    symbol: str,
    *,
    start: date,
    end: date,
    api_key_id: str,
    api_secret_key: str,
    data_url: str,
) -> MarketSeries:
    # feed="iex": same live-plan constraint as the rest of this tool (see
    # boe.filter.live_technical.fetch_live_series) - real, narrower than
    # SIP, not a fabricated substitute. Unlike fetch_live_series's fixed
    # 150-day lookback, the caller here picks start/end explicitly so an
    # older entry's full history is always covered.
    return fetch_daily_bars(
        symbol,
        start=start,
        end=end,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
        feed="iex",
    )


def measure(
    *,
    watchlist_status: dict[str, Any],
    existing_entries: list[dict[str, Any]],
    as_of: datetime,
    api_key_id: str,
    api_secret_key: str,
    data_url: str,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], int]:
    """Returns (updated_entries, newly_added_candidate_ids,
    skipped_new_entries, checkpoints_measured_this_run). Mutates entry
    dicts in place for checkpoints/measurement_errors, same objects as in
    updated_entries."""
    shortlist = watchlist_status.get("shortlist") or []
    benchmark = watchlist_status.get("benchmark")

    entries = existing_entries
    added: list[str] = []
    skipped: list[dict[str, Any]] = []
    if shortlist and benchmark:
        entries, added, skipped = record_new_entries(
            entries,
            shortlist,
            as_of=as_of,
            benchmark_close=Decimal(benchmark["close"]),
            shortlist_definition=watchlist_status["shortlist_definition"],
            shortlist_parameters=watchlist_status["shortlist_parameters"],
        )

    today = as_of.date()
    due = [(entry, due_checkpoints(entry, today=today)) for entry in entries]
    due = [(entry, weeks) for entry, weeks in due if weeks]
    if not due:
        return entries, added, skipped, 0

    earliest_entry_date = min(date.fromisoformat(entry["entry_date"]) for entry, _ in due)
    benchmark_series = _fetch_full_series(
        BENCHMARK_SYMBOL,
        start=earliest_entry_date - timedelta(days=FETCH_BUFFER_DAYS),
        end=today,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
    )

    measured_count = 0
    for entry, weeks in due:
        try:
            security_series = _fetch_full_series(
                entry["ticker"],
                start=date.fromisoformat(entry["entry_date"]) - timedelta(days=FETCH_BUFFER_DAYS),
                end=today,
                api_key_id=api_key_id,
                api_secret_key=api_secret_key,
                data_url=data_url,
            )
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            entry.setdefault("measurement_errors", []).append(
                {"as_of": as_of.isoformat(), "weeks_attempted": weeks, "reason": str(exc)}
            )
            continue
        for week in weeks:
            try:
                result = measure_checkpoint(
                    entry,
                    week,
                    security_series=security_series,
                    benchmark_series=benchmark_series,
                    measured_on=today,
                )
            except ValueError as exc:
                entry.setdefault("measurement_errors", []).append(
                    {"as_of": as_of.isoformat(), "week": week, "reason": str(exc)}
                )
                continue
            entry["checkpoints"][str(week)] = result
            measured_count += 1

    return entries, added, skipped, measured_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watchlist-path", type=str, default=DEFAULT_WATCHLIST_PATH)
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    watchlist_path = ROOT / args.watchlist_path
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    watchlist_status = json.loads(watchlist_path.read_text())
    as_of = datetime.fromisoformat(watchlist_status["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    entries_path = output_dir / "entries.json"
    existing_entries = json.loads(entries_path.read_text()) if entries_path.exists() else []

    api_key_id, api_secret_key, data_url = credentials_from_env()
    entries, added, skipped, checkpoints_measured = measure(
        watchlist_status=watchlist_status,
        existing_entries=existing_entries,
        as_of=as_of,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
        data_url=data_url,
    )

    summary = summarize(entries)
    entries_path.write_text(render(entries))
    (output_dir / "summary.json").write_text(render(summary))
    (output_dir / "forward-log.html").write_text(render_forward_log_html(entries, summary))

    report = {
        "as_of": as_of.isoformat(),
        "entries_added": added,
        "entries_skipped": skipped,
        "entry_count": len(entries),
        "checkpoints_measured_this_run": checkpoints_measured,
    }
    print(json.dumps(report))


if __name__ == "__main__":
    main()
