"""Apply *.sql files from a migrations directory in lexical order.

Idempotent: tracks applied filenames in a `schema_migrations` table. Each file
runs in its own transaction; partial application is impossible.

This is intentionally simpler than alembic — we don't need down-migrations,
auto-generation, or branching for a single-purpose ingestor.
"""
from __future__ import annotations

from pathlib import Path

from psycopg2.extensions import connection as PgConnection

from ..logging_setup import get_logger

_log = get_logger(__name__)

_DDL_TRACKING = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def apply_migrations(conn: PgConnection, migrations_dir: Path) -> list[str]:
    """Apply any *.sql files not yet recorded. Returns list of applied names."""
    files = sorted(p for p in migrations_dir.glob("*.sql"))
    if not files:
        return []

    applied: list[str] = []
    with conn.cursor() as cur:
        cur.execute(_DDL_TRACKING)
        cur.execute("SELECT filename FROM schema_migrations")
        already = {row[0] for row in cur.fetchall()}
    conn.commit()

    for f in files:
        if f.name in already:
            continue
        sql = f.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)",
                (f.name,),
            )
        conn.commit()
        applied.append(f.name)
        _log.info("migrations.applied", file=f.name)

    return applied
