"""Append a raw API payload to a bronze table — with hash-based dedup.

Algorithm per write:
  1. Compute `response_hash = sha256(canonical_json(payload))`.
  2. Compute `params_hash   = sha256(canonical_json(request_params))`.
  3. Look up `bronze_latest_hash` for (endpoint, params_hash).
     - If `last_response_hash == response_hash`: skip the insert. Always
       update `last_checked_at`.
     - Else: INSERT a new bronze row, then UPSERT latest_hash with new hash.
  4. Return a small status dict so the orchestrator can log & count.

Append-only invariant: this module never issues UPDATE or DELETE against
bronze_* tables. Only `bronze_latest_hash` (a companion, not bronze itself)
is upserted.

Endpoints supported (extend `_ENDPOINTS` to add more):
  * "leagues"            → bronze_leagues
  * "fixtures_by_league" → bronze_fixtures        (extra cols: league_id, season)
  * "fixture_details"    → bronze_fixture_details (extra cols: fixture_id)
  * "halftime_stats"     → bronze_halftime_stats  (extra cols: fixture_id)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg2.extensions import connection as PgConnection
from psycopg2.extras import Json


@dataclass(frozen=True)
class _EndpointSpec:
    table: str
    extra_columns: tuple[str, ...]  # columns pulled from request_params


_ENDPOINTS: dict[str, _EndpointSpec] = {
    "leagues":            _EndpointSpec("bronze_leagues",          ()),
    "fixtures_by_league": _EndpointSpec("bronze_fixtures",         ("league_id", "season")),
    "fixture_details":    _EndpointSpec("bronze_fixture_details",  ("fixture_id",)),
    "halftime_stats":     _EndpointSpec("bronze_halftime_stats",   ("fixture_id",)),
}


@dataclass(frozen=True)
class WriteResult:
    endpoint: str
    params_hash: str
    response_hash: str
    changed: bool
    bronze_row_id: int | None  # None when skipped


def write_bronze(
    conn: PgConnection,
    *,
    endpoint: str,
    request_params: dict[str, Any],
    payload: dict[str, Any],
    run_id: UUID,
    api_version: str | None = None,
) -> WriteResult:
    """Hash-dedup append. Caller manages the surrounding transaction."""
    spec = _ENDPOINTS.get(endpoint)
    if spec is None:
        raise ValueError(f"unknown bronze endpoint: {endpoint!r}")

    params_hash = _hash_canonical(request_params)
    response_hash = _hash_canonical(payload)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_response_hash
              FROM bronze_latest_hash
             WHERE endpoint = %s AND params_hash = %s
             FOR UPDATE
            """,
            (endpoint, params_hash),
        )
        row = cur.fetchone()
        changed = row is None or row[0] != response_hash

        bronze_id: int | None = None
        if changed:
            bronze_id = _insert_bronze(
                cur,
                spec=spec,
                run_id=run_id,
                endpoint=endpoint,
                request_params=request_params,
                response_hash=response_hash,
                api_version=api_version,
                payload=payload,
            )
        _upsert_latest_hash(
            cur,
            endpoint=endpoint,
            params_hash=params_hash,
            request_params=request_params,
            response_hash=response_hash,
            run_id=run_id,
            changed=changed,
        )

    return WriteResult(
        endpoint=endpoint,
        params_hash=params_hash,
        response_hash=response_hash,
        changed=changed,
        bronze_row_id=bronze_id,
    )


# ---- internals ----


def _hash_canonical(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _insert_bronze(
    cur: Any,
    *,
    spec: _EndpointSpec,
    run_id: UUID,
    endpoint: str,
    request_params: dict[str, Any],
    response_hash: str,
    api_version: str | None,
    payload: dict[str, Any],
) -> int:
    columns = [
        "run_id", "endpoint", "request_params", "response_hash",
        "api_version", "payload",
    ]
    values: list[Any] = [
        str(run_id), endpoint, Json(request_params), response_hash,
        api_version, Json(payload),
    ]
    for extra in spec.extra_columns:
        if extra not in request_params:
            raise KeyError(
                f"endpoint {endpoint!r} requires {extra!r} in request_params"
            )
        columns.append(extra)
        values.append(request_params[extra])

    placeholders = ", ".join(["%s"] * len(values))
    col_sql = ", ".join(columns)
    cur.execute(
        f"INSERT INTO {spec.table} ({col_sql}) VALUES ({placeholders}) RETURNING id",
        values,
    )
    return int(cur.fetchone()[0])


def _upsert_latest_hash(
    cur: Any,
    *,
    endpoint: str,
    params_hash: str,
    request_params: dict[str, Any],
    response_hash: str,
    run_id: UUID,
    changed: bool,
) -> None:
    if changed:
        cur.execute(
            """
            INSERT INTO bronze_latest_hash
                (endpoint, params_hash, request_params,
                 last_response_hash, last_run_id,
                 last_checked_at, last_changed_at)
            VALUES (%s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (endpoint, params_hash) DO UPDATE SET
                last_response_hash = EXCLUDED.last_response_hash,
                last_run_id        = EXCLUDED.last_run_id,
                last_checked_at    = now(),
                last_changed_at    = now()
            """,
            (endpoint, params_hash, Json(request_params),
             response_hash, str(run_id)),
        )
    else:
        # Always bump last_checked_at even when nothing changed.
        cur.execute(
            """
            UPDATE bronze_latest_hash
               SET last_checked_at = now(),
                   last_run_id     = %s
             WHERE endpoint = %s AND params_hash = %s
            """,
            (str(run_id), endpoint, params_hash),
        )
