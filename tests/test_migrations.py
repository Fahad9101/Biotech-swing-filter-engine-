from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {
    "alembic_version",
    "analysis_runs",
    "candidate_decisions",
    "capital_structure_snapshots",
    "cash_burn_snapshots",
    "catalyst_confirmations",
    "catalyst_conflicts",
    "catalyst_observations",
    "catalyst_versions",
    "claims",
    "evidence_items",
    "factor_scores",
    "financial_facts",
    "financing_facilities",
    "financing_filings",
    "financing_risk_snapshots",
    "gate_results",
    "historical_cohort_manifests",
    "historical_decision_locks",
    "historical_events",
    "historical_failure_analysis",
    "historical_leakage_audit",
    "historical_outcomes",
    "historical_validation_reports",
    "issuers",
    "market_bar_batches",
    "market_bars_daily",
    "market_data_source_audits",
    "raw_payloads",
    "science_reviews",
    "scientific_evidence_packs",
    "securities",
    "survival_snapshots",
    "technical_snapshots",
    "universe_snapshots",
    "valuation_assumptions",
    "valuation_snapshots",
}


def test_alembic_builds_milestone_seven_schema(tmp_path, repository_root, monkeypatch):
    database_path = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("BOE_DATABASE_URL", url)
    config = Config(repository_root / "alembic.ini")

    command.upgrade(config, "head")

    assert set(inspect(create_engine(url)).get_table_names()) == EXPECTED_TABLES
