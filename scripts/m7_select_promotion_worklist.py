"""Select a deterministic first promotion-evidence worklist from the M7 ledger."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "validation/m7/promotion/candidate-promotion-ledger.json"
OUTPUT = ROOT / "validation/m7/promotion/promotion-worklist-01.json"
TARGET = 50

STRATUM_ORDER = (
    "PHASE_2_POC",
    "PHASE_3_PIVOTAL",
    "REGULATORY",
    "EARLY_CLINICAL",
    "CONFERENCE_OTHER",
)


def main() -> None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    by_stratum: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ledger["rows"]:
        if row["first_public_timestamp"] is None:
            continue
        if row["duplicate_group_id"] is not None:
            continue
        by_stratum[row["proposed_primary_stratum"]].append(row)

    for rows in by_stratum.values():
        rows.sort(
            key=lambda row: (
                row["cik"] is None,
                row["first_public_date"],
                row["candidate_id"],
            )
        )

    selected: list[dict[str, Any]] = []
    used_tickers: set[str] = set()
    cursor = {stratum: 0 for stratum in STRATUM_ORDER}
    while len(selected) < TARGET:
        advanced = False
        for stratum in STRATUM_ORDER:
            rows = by_stratum[stratum]
            while cursor[stratum] < len(rows):
                row = rows[cursor[stratum]]
                cursor[stratum] += 1
                ticker = str(row["historical_ticker"])
                if ticker in used_tickers:
                    continue
                selected.append(
                    {
                        "candidate_id": row["candidate_id"],
                        "ticker": ticker,
                        "cik": row["cik"],
                        "event_date": row["first_public_date"],
                        "event_timestamp": row["first_public_timestamp"],
                        "stratum": row["proposed_primary_stratum"],
                        "asset": row["asset"],
                        "indication": row["indication"],
                        "negative_event": row["negative_event"],
                        "financing_window_status": "PENDING",
                        "single_asset_status": "PENDING",
                    }
                )
                used_tickers.add(ticker)
                advanced = True
                break
            if len(selected) >= TARGET:
                break
        if not advanced:
            break

    payload = {
        "format_version": "1.0",
        "milestone": 7,
        "rules_version": "BOE-1.0.0",
        "role": "PREFREEZE_PROMOTION_EVIDENCE_WORKLIST",
        "selection_rule": "exact timestamp, no potential duplicate group, one row per ticker, deterministic stratum round-robin; no market outcomes",
        "candidate_count": len(selected),
        "market_outcomes_inspected": False,
        "candidates": selected,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_count": len(selected)}, sort_keys=True))


if __name__ == "__main__":
    main()
