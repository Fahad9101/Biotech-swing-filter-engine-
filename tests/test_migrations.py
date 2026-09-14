from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {
    "alembic_version",
    "claims",
    "evidence_items",
    "issuers",
    "raw_payloads",
    "securities",
    "universe_snapshots",
}


def test_alembic_builds_milestone_two_schema(tmp_path, repository_root, monkeypatch):
    database_path = tmp_path / "migration.db"
    url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("BOE_DATABASE_URL", url)
    config = Config(repository_root / "alembic.ini")

    command.upgrade(config, "head")

    assert set(inspect(create_engine(url)).get_table_names()) == EXPECTED_TABLES
