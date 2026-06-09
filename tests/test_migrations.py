"""Migrations: idempotent, tracked, create the expected tables."""
from __future__ import annotations

from pathlib import Path

from ingestor.db.migrations import apply_migrations

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"

EXPECTED_TABLES = {
    "bronze_leagues",
    "bronze_fixtures",
    "bronze_fixture_details",
    "bronze_halftime_stats",
    "bronze_latest_hash",
    "ingestion_runs",
    "ingestion_checkpoints",
    "dead_letter",
    "schema_migrations",
}


def _tables_in_search_path(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
              FROM information_schema.tables
             WHERE table_schema = current_schema()
            """
        )
        return {row[0] for row in cur.fetchall()}


def test_apply_creates_expected_tables(pg_conn) -> None:
    assert EXPECTED_TABLES.issubset(_tables_in_search_path(pg_conn))


def test_apply_is_idempotent(pg_conn) -> None:
    applied = apply_migrations(pg_conn, MIGRATIONS_DIR)
    assert applied == []  # conftest already applied them


def test_schema_migrations_records_filenames(pg_conn) -> None:
    with pg_conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations ORDER BY filename")
        names = [r[0] for r in cur.fetchall()]
    assert names == ["001_bronze.sql"]
