"""Phase B — /fixtures?id={fixture_id} (the RICH endpoint).

This one response embeds lineups, events, player stats, and fixture stats.
The bronze layer stores it whole; silver will split it out later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg2.extensions import connection as PgConnection

from ..db.bronze_writer import WriteResult, write_bronze
from ..http.client import ApiFootballClient

ENDPOINT = "fixture_details"
PATH = "/fixtures"


@dataclass(frozen=True)
class FixtureDetailsOutcome:
    fixture_id: int
    payload: dict[str, Any]
    write: WriteResult


def fetch_fixture_details(
    client: ApiFootballClient,
    conn: PgConnection,
    *,
    run_id: UUID,
    fixture_id: int,
    api_version: str | None = None,
) -> FixtureDetailsOutcome:
    body = client.get(PATH, params={"id": fixture_id})
    write = write_bronze(
        conn,
        endpoint=ENDPOINT,
        request_params={"id": fixture_id, "fixture_id": fixture_id},
        payload=body,
        run_id=run_id,
        api_version=api_version,
    )
    return FixtureDetailsOutcome(fixture_id=fixture_id, payload=body, write=write)
