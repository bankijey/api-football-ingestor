"""Append a failure record to the `dead_letter` table.

Pure append: each failure becomes a new row. No dedup — we want the full
audit trail of what failed, when, and why.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg2.extras import Json

from .db.connection import ConnectionPool


def record_failure(
    pool: ConnectionPool,
    *,
    run_id: UUID | None,
    endpoint: str,
    request_params: dict[str, Any],
    error: BaseException,
    attempts: int = 1,
) -> None:
    http_status = getattr(error, "status_code", None)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dead_letter
                (run_id, endpoint, request_params,
                 error_class, error_message, http_status, attempts)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(run_id) if run_id else None,
                endpoint,
                Json(request_params),
                type(error).__name__,
                str(error)[:4000],
                int(http_status) if isinstance(http_status, int) else None,
                attempts,
            ),
        )
