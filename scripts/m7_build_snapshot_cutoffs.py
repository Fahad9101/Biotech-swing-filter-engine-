"""Compute real point-in-time snapshot cutoffs and T0 sessions for the frozen
Milestone 7 cohort.

This is pure calendar math over the already-frozen
validation/m7/cohort-manifest.json - no price data, no scientific review, no
judgment calls. It supplies the trading-calendar input required by
boe.historical_validation's frozen snapshot_cutoff() and align_t0_session()
functions (via boe.market_calendar, a dependency-free NYSE holiday calendar)
and persists the result as a committed artifact.

This is a deliberately narrow slice of Milestone 7's "point-in-time
reconstruction" step (validation/VALIDATION-AND-MILESTONES.md section 3): it
establishes WHEN each snapshot's evidence cutoff falls, not WHAT evidence was
available as of that cutoff. Assembling the real evidence packs bound to
these cutoffs still depends on a real price-data source decision and, for any
scored decision lock, a real human scientific/catalyst reviewer - see
docs/M7-HUMAN-REVIEW-BLOCKER.md, which neither this script nor any other part
of this repository may substitute for.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from boe.historical_validation import (  # noqa: E402
    CohortManifest,
    SnapshotLabel,
    align_t0_session,
    snapshot_cutoff,
)
from boe.market_calendar import last_complete_session_before, trading_sessions  # noqa: E402

MANIFEST_PATH = ROOT / "validation/m7/cohort-manifest.json"
OUTPUT_PATH = ROOT / "validation/m7/snapshot-cutoffs.json"

# Wide enough that align_t0_session always has a same-day-or-later candidate,
# even around back-to-back holidays, without scanning the whole calendar.
_T0_SEARCH_WINDOW_DAYS = 14


def render(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def build() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise ValueError(
            f"{MANIFEST_PATH} does not exist - the cohort is not frozen yet. "
            "Run scripts/m7_build_historical_event_registry.py --freeze first."
        )
    manifest = CohortManifest.model_validate(json.loads(MANIFEST_PATH.read_bytes()))

    records = []
    for event in manifest.events:
        event_date = event.event_at.date()
        last_complete = last_complete_session_before(event_date)
        window = trading_sessions(
            event_date - timedelta(days=_T0_SEARCH_WINDOW_DAYS),
            event_date + timedelta(days=_T0_SEARCH_WINDOW_DAYS),
        )
        t0_session = align_t0_session(event.event_at, window)
        cutoffs = {
            label.value: snapshot_cutoff(event.event_at, label, last_complete).isoformat()
            for label in SnapshotLabel
        }
        records.append(
            {
                "event_id": event.event_id,
                "ticker": event.ticker,
                "primary_stratum": event.primary_stratum.value,
                "event_at": event.event_at.isoformat(),
                "t0_session": t0_session.isoformat(),
                "last_complete_session": last_complete.isoformat(),
                "snapshot_cutoffs": cutoffs,
            }
        )
    records.sort(key=lambda r: str(r["event_id"]))

    return {
        "generator": "python scripts/m7_build_snapshot_cutoffs.py",
        "cohort_sha256": manifest.cohort_sha256,
        "event_count": len(records),
        "events": records,
        "not_yet_complete": [
            "Point-in-time evidence packs bound to these cutoffs (market, "
            "financial, catalyst, and scientific evidence available as of "
            "each cutoff) have not been assembled.",
            "No real price-data source has been selected; outcome/return "
            "reconstruction (VALIDATION-AND-MILESTONES.md section 4) is not "
            "possible without one.",
            "No ManualScienceReview or HumanCatalystConfirmation records "
            "exist; no HistoricalDecisionLock may be constructed without a "
            "real, identified human reviewer.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    status = build()
    expected = render(status)
    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text() != expected:
            raise SystemExit(f"Stale generated artifact: {OUTPUT_PATH.relative_to(ROOT)}")
    else:
        OUTPUT_PATH.write_text(expected)
    print(f"wrote snapshot cutoffs for {status['event_count']} events")


if __name__ == "__main__":
    main()
