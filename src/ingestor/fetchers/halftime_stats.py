"""Phase B — /fixtures/statistics?fixture={id}&half=true.

The only call we make for halftime stats; full-match stats are already
embedded inside `fetch_fixture_details`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg2.extensions import connection as PgConnection

from ..db.bronze_writer import WriteResult, write_bronze
from ..http.client import ApiFootballClient

ENDPOINT = "halftime_stats"
PATH = "/fixtures/statistics"


@dataclass(frozen=True)
class HalftimeStatsOutcome:
    fixture_id: int
    payload: dict[str, Any]
    write: WriteResult


def fetch_halftime_stats(
    client: ApiFootballClient,
    conn: PgConnection,
    *,
    run_id: UUID,
    fixture_id: int,
    api_version: str | None = None,
) -> HalftimeStatsOutcome:
    body = client.get(PATH, params={"fixture": fixture_id, "half": "true"})
    write = write_bronze(
        conn,
        endpoint=ENDPOINT,
        request_params={
            "fixture": fixture_id, "half": "true",
            "fixture_id": fixture_id,
        },
        payload=body,
        run_id=run_id,
        api_version=api_version,
    )
    return HalftimeStatsOutcome(fixture_id=fixture_id, payload=body, write=write)
