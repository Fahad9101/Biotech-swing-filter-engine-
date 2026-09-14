# Biotech Opportunity Engine (BOE)

BOE is a production-oriented research system for ranking U.S.-listed biotechnology stocks with identifiable 1–12 week catalysts. It separates scientific quality, investment value, and swing-trade timing, then applies explicit data-quality and risk gates before a candidate can be classified as investable.

## Current status

**Milestone 2 complete: BOE now has an auditable universe and evidence foundation. Catalyst, clinical, financial, scoring, valuation, market-data, and UI logic remain unimplemented.**

The frozen foundation consists of:

- [`docs/BOE-1.0.0-INVESTMENT-SPECIFICATION.md`](docs/BOE-1.0.0-INVESTMENT-SPECIFICATION.md) — universe, scoring, probability, valuation, risk gates, and classifications.
- [`docs/TECHNICAL-IMPLEMENTATION-CONTRACT.md`](docs/TECHNICAL-IMPLEMENTATION-CONTRACT.md) — fields, provenance, architecture, storage, API, and output behavior.
- [`docs/VALIDATION-AND-MILESTONES.md`](docs/VALIDATION-AND-MILESTONES.md) — historical validation, acceptance criteria, governance, and controlled milestone sequence.
- [`contracts/boe-scorecard.v1.0.0.json`](contracts/boe-scorecard.v1.0.0.json) — machine-readable scorecard and decision thresholds.
- [`contracts/candidate-output.schema.json`](contracts/candidate-output.schema.json) — machine-testable candidate-output contract.
- [`docs/MILESTONE-2-REPORT.md`](docs/MILESTONE-2-REPORT.md) — implemented boundary, audit result, limitations, and handoff.
- [`validation/milestone-2-universe-audit.json`](validation/milestone-2-universe-audit.json) — reproducible 19-case universe-classification audit result.

## Non-negotiable boundaries

- Free/public data only during BOE v1.0 validation.
- No Docker requirement.
- No integration with, or modification of, Investment Execution Engine v1.7.2.
- No integration with, or modification of, Swing Opportunity Engine SOE-1.0.0.
- No unapproved BOE v1.1 logic changes.
- GitHub is the single source of truth.

## Decision philosophy

BOE does not equate a nearby catalyst with an opportunity. A company must clear four separate questions:

1. Is the event real, sufficiently dated, and value-changing?
2. Is the scientific/regulatory case credible?
3. Does price leave a conservative margin of safety and positive expected value?
4. Is the balance sheet and trade structure survivable if the thesis fails?

## Local contract validation

Python 3.12 is required. No Docker or paid data service is needed.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
ruff format --check .
ruff check .
mypy src
pytest
boe-contracts --candidate tests/fixtures/valid_candidate.json
BOE_DATABASE_URL=sqlite+pysqlite:///boe.db alembic upgrade head
```

Milestone 3 must not begin without explicit approval.
