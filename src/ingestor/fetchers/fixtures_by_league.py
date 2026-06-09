"""Phase A — /fixtures?league={id}&season={year} for one league+season."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg2.extensions import connection as PgConnection

from ..db.bronze_writer import WriteResult, write_bronze
from ..http.client import ApiFootballClient

ENDPOINT = "fixtures_by_league"
PATH = "/fixtures"


@dataclass(frozen=True)
class FixturesByLeagueOutcome:
    league_id: int
    season: int
    payload: dict[str, Any]
    write: WriteResult


def fetch_fixtures_by_league(
    client: ApiFootballClient,
    conn: PgConnection,
    *,
    run_id: UUID,
    league_id: int,
    season: int,
    api_version: str | None = None,
) -> FixturesByLeagueOutcome:
    params = {"league": league_id, "season": season}
    body = client.get(PATH, params=params)
    # The bronze writer needs typed extras under their column names, not API
    # param names. We store both so the request_params JSONB is faithful AND
    # the typed columns get populated.
    write = write_bronze(
        conn,
        endpoint=ENDPOINT,
        request_params={
            "league": league_id, "season": season,
            "league_id": league_id,  # extra for the typed column
        },
        payload=body,
        run_id=run_id,
        api_version=api_version,
    )
    return FixturesByLeagueOutcome(
        league_id=league_id, season=season, payload=body, write=write,
    )
