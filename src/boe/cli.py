"""Command-line validation for BOE repository contracts."""

from __future__ import annotations

import argparse
from pathlib import Path

from boe.contracts import load_candidate, load_scorecard, validate_candidate_against_scorecard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate BOE-1.0.0 contract artifacts")
    parser.add_argument(
        "--scorecard",
        type=Path,
        default=Path("contracts/boe-scorecard.v1.0.0.json"),
    )
    parser.add_argument("--candidate", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    loaded = load_scorecard(args.scorecard)
    print(f"scorecard={loaded.contract.version}")
    print(f"raw_sha256={loaded.raw_sha256}")
    print(f"canonical_sha256={loaded.canonical_sha256}")
    print(f"score_max={loaded.contract.score_max}")
    print(f"factors={len(loaded.contract.factors)}")
    if args.candidate is not None:
        candidate = load_candidate(args.candidate)
        validate_candidate_against_scorecard(candidate, loaded)
        print(f"candidate={candidate.identity.ticker}")
        print(f"classification={candidate.decision.classification}")
    return 0
