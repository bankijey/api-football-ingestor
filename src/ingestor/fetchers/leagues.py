"""Phase A — single call to /leagues.

Returns the raw payload AND the WriteResult so the orchestrator can both
log and pass the payload downstream to `selection.league_filter.select_leagues`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg2.extensions import connection as PgConnection

from ..db.bronze_writer import WriteResult, write_bronze
from ..http.client import ApiFootballClient

ENDPOINT = "leagues"
PATH = "/leagues"


@dataclass(frozen=True)
class LeaguesFetchOutcome:
    payload: dict[str, Any]
    write: WriteResult


def fetch_leagues(
    client: ApiFootballClient,
    conn: PgConnection,
    *,
    run_id: UUID,
    api_version: str | None = None,
) -> LeaguesFetchOutcome:
    body = client.get(PATH)
    write = write_bronze(
        conn,
        endpoint=ENDPOINT,
        request_params={},
        payload=body,
        run_id=run_id,
        api_version=api_version,
    )
    return LeaguesFetchOutcome(payload=body, write=write)
