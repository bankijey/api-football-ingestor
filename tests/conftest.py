"""Shared test fixtures.

DB tests reuse the docker-compose Postgres but isolate via per-test schemas:
each test gets a unique `test_<uuid>` schema, with the search_path set so
all bare table references land inside it. The schema is dropped on teardown.

If Postgres isn't reachable (e.g. someone forgot `make up`), DB-tagged tests
SKIP rather than fail — keeping the pure-Python suite green in any env.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

try:
    import psycopg2
    from psycopg2.extensions import connection as PgConnection
except ModuleNotFoundError:  # pragma: no cover
    psycopg2 = None  # type: ignore[assignment]
    PgConnection = object  # type: ignore[assignment,misc]


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"

_DEFAULT_DSN = "postgresql://ingestor:ingestor@localhost:5432/ingestor"


def _dsn() -> str:
    return os.environ.get("TEST_DB_DSN") or os.environ.get("DB_DSN") or _DEFAULT_DSN


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    """Verify Postgres is reachable; skip the whole DB suite if not."""
    if psycopg2 is None:
        pytest.skip("psycopg2 not installed")
    dsn = _dsn()
    try:
        conn = psycopg2.connect(dsn, connect_timeout=2)
        conn.close()
    except Exception as e:
        pytest.skip(f"postgres not reachable at {dsn}: {e}")
    return dsn


@pytest.fixture()
def pg_conn(pg_dsn: str) -> Iterator[PgConnection]:
    """Per-test isolated schema with migrations applied."""
    from ingestor.db.migrations import apply_migrations

    schema = f"test_{uuid.uuid4().hex[:12]}"
    conn = psycopg2.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
            cur.execute(f'SET search_path TO "{schema}"')
        conn.commit()
        apply_migrations(conn, MIGRATIONS_DIR)
        # Re-set after migrations in case any committed statement reset it.
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}"')
        conn.commit()
        yield conn
    finally:
        try:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.commit()
        finally:
            conn.close()


@pytest.fixture()
def pg_pool(pg_dsn: str):
    """A ConnectionPool pinned to an isolated per-test schema.

    Uses Postgres' libpq `options=-csearch_path=...` so every connection the
    pool hands out starts with the right search_path — no per-borrow SET.
    """
    from ingestor.db.connection import ConnectionPool
    from ingestor.db.migrations import apply_migrations

    schema = f"test_{uuid.uuid4().hex[:12]}"

    # Bootstrap: create the schema using a bare connection.
    boot = psycopg2.connect(pg_dsn)
    try:
        with boot.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}"')
        boot.commit()
    finally:
        boot.close()

    # Pool DSN with search_path pinned for every new connection.
    sep = "&" if "?" in pg_dsn else "?"
    pool_dsn = f"{pg_dsn}{sep}options=-csearch_path%3D{schema}"
    pool = ConnectionPool(pool_dsn, minconn=1, maxconn=8)

    # Apply migrations once into the schema.
    with pool.connection() as conn:
        apply_migrations(conn, MIGRATIONS_DIR)

    try:
        yield pool
    finally:
        pool.closeall()
        drop = psycopg2.connect(pg_dsn)
        try:
            with drop.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            drop.commit()
        finally:
            drop.close()
