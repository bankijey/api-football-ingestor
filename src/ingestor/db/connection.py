"""Postgres connection pool — single entrypoint for all DB access.

We use psycopg2's SimpleConnectionPool because the ingestor is sync +
ThreadPoolExecutor. Each worker `with pool.connection() as conn:` borrows a
connection for the duration of one unit of work (a fetch, a write).

DO NOT instantiate raw psycopg2 connections elsewhere — go through the pool.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg2.extensions import connection as PgConnection
from psycopg2.pool import SimpleConnectionPool

from ..config import Settings


class ConnectionPool:
    def __init__(self, dsn: str, *, minconn: int = 1, maxconn: int = 16) -> None:
        self._pool = SimpleConnectionPool(minconn, maxconn, dsn=dsn)

    @classmethod
    def from_settings(cls, settings: Settings) -> ConnectionPool:
        # Pool size scales with worker count, with some headroom for migrations
        # / heartbeat / orchestrator threads.
        return cls(
            settings.db_dsn,
            minconn=1,
            maxconn=max(settings.thread_pool_size * 2, 4),
        )

    @contextmanager
    def connection(self) -> Iterator[PgConnection]:
        """Borrow a connection; commit on clean exit, rollback on exception."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    def closeall(self) -> None:
        self._pool.closeall()

    def __enter__(self) -> ConnectionPool:
        return self

    def __exit__(self, *_: Any) -> None:
        self.closeall()
