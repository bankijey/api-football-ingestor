"""Checkpoint + run-state store.

Two tables under the hood:
  * ingestion_runs       — one row per run (status, args, counters, heartbeat)
  * ingestion_checkpoints — one row per (run_id, scope, key, endpoint),
                            tracks per-task status so we can resume cleanly.

Each method borrows its own short-lived connection from the pool. That keeps
checkpoint writes independent of any in-flight HTTP / bronze writes — a
fetcher failing mid-transaction doesn't lose the checkpoint update.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg2.extras import Json

from ..db.connection import ConnectionPool


@dataclass(frozen=True)
class CheckpointKey:
    scope: str        # 'league' | 'fixture'
    key: str          # e.g. '39:2025' or '12345'
    endpoint: str     # e.g. 'fixtures_by_league' | 'fixture_details'


class CheckpointStore:
    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    # ---- run lifecycle ----

    def start_run(self, *, args: dict[str, Any] | None = None) -> UUID:
        rid = uuid4()
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs (run_id, status, args, last_heartbeat_at)
                VALUES (%s, 'running', %s, now())
                """,
                (str(rid), Json(args or {})),
            )
        return rid

    def heartbeat(self, run_id: UUID) -> None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_runs SET last_heartbeat_at = now() WHERE run_id = %s",
                (str(run_id),),
            )

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: str,
        counters: dict[str, Any] | None = None,
    ) -> None:
        if status not in {"succeeded", "partial", "failed"}:
            raise ValueError(f"invalid terminal status: {status}")
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_runs
                   SET status = %s,
                       finished_at = now(),
                       counters = %s,
                       last_heartbeat_at = now()
                 WHERE run_id = %s
                """,
                (status, Json(counters or {}), str(run_id)),
            )

    # ---- per-task checkpoints ----

    def is_succeeded(self, run_id: UUID, ck: CheckpointKey) -> bool:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM ingestion_checkpoints
                 WHERE run_id = %s AND scope = %s AND key = %s AND endpoint = %s
                """,
                (str(run_id), ck.scope, ck.key, ck.endpoint),
            )
            row = cur.fetchone()
            return row is not None and row[0] == "succeeded"

    def mark_pending(self, run_id: UUID, ck: CheckpointKey) -> None:
        self._upsert_status(run_id, ck, status="pending", error=None, bump_attempts=True)

    def mark_succeeded(self, run_id: UUID, ck: CheckpointKey) -> None:
        self._upsert_status(run_id, ck, status="succeeded", error=None, bump_attempts=False)

    def mark_failed(self, run_id: UUID, ck: CheckpointKey, *, error: str) -> None:
        self._upsert_status(run_id, ck, status="failed", error=error, bump_attempts=False)

    # ---- introspection (for resume / tests) ----

    def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, status, args, counters,
                       started_at, finished_at, last_heartbeat_at
                  FROM ingestion_runs WHERE run_id = %s
                """,
                (str(run_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "run_id": row[0],
                "status": row[1],
                "args": row[2],
                "counters": row[3],
                "started_at": row[4],
                "finished_at": row[5],
                "last_heartbeat_at": row[6],
            }

    # ---- internals ----

    def _upsert_status(
        self,
        run_id: UUID,
        ck: CheckpointKey,
        *,
        status: str,
        error: str | None,
        bump_attempts: bool,
    ) -> None:
        attempts_expr = "ingestion_checkpoints.attempts + 1" if bump_attempts else "ingestion_checkpoints.attempts"
        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO ingestion_checkpoints
                    (run_id, scope, key, endpoint, status, attempts, last_error, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id, scope, key, endpoint) DO UPDATE SET
                    status     = EXCLUDED.status,
                    attempts   = {attempts_expr},
                    last_error = EXCLUDED.last_error,
                    updated_at = now()
                """,
                (str(run_id), ck.scope, ck.key, ck.endpoint,
                 status, 1 if bump_attempts else 0,
                 _truncate(error, 4000)),
            )


def _truncate(s: str | None, n: int) -> str | None:
    if s is None:
        return None
    return s if len(s) <= n else s[: n - 1] + "…"


# Re-exported helper to keep callsites readable.
def ck_league(league_id: int, season: int, endpoint: str) -> CheckpointKey:
    return CheckpointKey(scope="league", key=f"{league_id}:{season}", endpoint=endpoint)


def ck_fixture(fixture_id: int, endpoint: str) -> CheckpointKey:
    return CheckpointKey(scope="fixture", key=str(fixture_id), endpoint=endpoint)


# Linter happiness: json is used by callers via Json() but kept available here.
_ = json
