"""`apifootball_events` projection — the ONE bronze-only-charter exception (D2).

Reads the latest `bronze_fixtures` catalogue (newest ingest per league+season)
from the local bronze DB, extracts unstarted future fixtures, and writes them
into the matcher's (sources) DB as `apifootball_events`, replacing the whole
table in a **single transaction** (D4) so the matcher never observes a partial
snapshot.

This is field-extraction only — no parsing, no reshaping of bronze payloads
(D2). It reads bronze locally and writes ONLY to the sources DB (D5); this
module is the sole place this process touches that DB. Rows conform to the
matcher's `EVENT_COLUMNS` contract (D6): `e_id = "apifootball;<fixture_id>"`
(semicolon), `bookmaker_id = "apifootball"`, `sport_key = "football"`,
`url = NULL`.

DB access goes through `ConnectionPool` only — no raw psycopg2 connections
(see `db/connection.py`).
"""
from __future__ import annotations

import time
from typing import Any

from psycopg2.extras import execute_batch

from .db.connection import ConnectionPool
from .logging_setup import get_logger

_log = get_logger(__name__)

# Idempotent DDL, run at build start on the sources-DB connection (NOT part of
# the bronze migrations). id columns are TEXT to mirror the legacy `all_events`
# feed the matcher already reads (D5); `start` is TIMESTAMPTZ (D6).
_CREATE_DDL = """
CREATE TABLE IF NOT EXISTS apifootball_events (
    fixture_id   BIGINT,
    e_id         TEXT,
    bookmaker_id TEXT,
    sport_key    TEXT,
    start        TIMESTAMPTZ,
    tid          TEXT,
    tournament   TEXT,
    home_team    TEXT,
    away_team    TEXT,
    home_id      TEXT,
    away_id      TEXT,
    url          TEXT
)
"""

# Latest ingest per (league_id, season) — DISTINCT ON keeps the newest row.
_LATEST_FIXTURES_SQL = """
SELECT DISTINCT ON (league_id, season) payload
FROM bronze_fixtures
ORDER BY league_id, season, ingested_at DESC
"""

_INSERT_SQL = """
INSERT INTO apifootball_events (
    fixture_id, e_id, bookmaker_id, sport_key, start,
    tid, tournament, home_team, away_team, home_id, away_id, url
) VALUES (
    %(fixture_id)s, %(e_id)s, %(bookmaker_id)s, %(sport_key)s, to_timestamp(%(ts)s),
    %(tid)s, %(tournament)s, %(home_team)s, %(away_team)s, %(home_id)s, %(away_id)s, %(url)s
)
"""


def build_projection(
    *,
    bronze_pool: ConnectionPool,
    matcher_pool: ConnectionPool,
    now_ts: float | None = None,
) -> int:
    """Project latest `bronze_fixtures` into the sources-DB `apifootball_events`.

    Reads bronze locally, computes the row set, then atomically replaces the
    sources-DB table. Returns the number of rows written.
    """
    if now_ts is None:
        now_ts = time.time()

    rows = _read_rows(bronze_pool, now_ts)
    _write_atomic(matcher_pool, rows)
    _log.info("projection.built", rows=len(rows))
    return len(rows)


# ---- internals ----


_ITERSIZE = 200  # payloads resident per server-side fetch batch


def _read_rows(bronze_pool: ConnectionPool, now_ts: float) -> list[dict[str, Any]]:
    # Stream the latest league-season payloads with a psycopg2 named
    # (server-side) cursor instead of materializing all ~thousands of large
    # JSONB payloads at once (fetchall would peak at the full set — an OOM risk
    # that grows with bronze). The named cursor is created and fully consumed
    # inside the pool's transaction (connection.py:38-49), before commit.
    rows: list[dict[str, Any]] = []
    with (
        bronze_pool.connection() as conn,
        conn.cursor(name="apifootball_proj_read") as cur,
    ):
        cur.itersize = _ITERSIZE
        cur.execute(_LATEST_FIXTURES_SQL)
        for (payload,) in cur:
            for fixture in (payload or {}).get("response") or []:
                row = _to_row(fixture, now_ts)
                if row is not None:
                    rows.append(row)
    return rows


def _to_row(fixture: dict[str, Any], now_ts: float) -> dict[str, Any] | None:
    """Map one API-Football fixture object to a projection row, or None if it
    is not an unstarted future fixture (status NS + timestamp in the future)."""
    fx = fixture.get("fixture") or {}
    status = (fx.get("status") or {}).get("short")
    ts = fx.get("timestamp")
    # NS = not-started; combine with a FUTURE timestamp so a delayed/erroneous
    # NS in the past cannot leak in.
    if status != "NS" or ts is None or ts <= now_ts:
        return None

    fid = fx.get("id")
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    return {
        "fixture_id": fid,
        "e_id": f"apifootball;{fid}",   # semicolon delimiter (D6)
        "bookmaker_id": "apifootball",
        "sport_key": "football",
        "ts": ts,                        # -> to_timestamp() -> TIMESTAMPTZ
        "tid": _s(league.get("id")),
        "tournament": league.get("name"),
        "home_team": home.get("name"),
        "away_team": away.get("name"),
        "home_id": _s(home.get("id")),
        "away_id": _s(away.get("id")),
        "url": None,                     # D6
    }


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def _write_atomic(matcher_pool: ConnectionPool, rows: list[dict[str, Any]]) -> None:
    """Replace the whole `apifootball_events` table in one transaction.

    Idempotent DDL + TRUNCATE + INSERT all run on a single borrowed connection;
    the pool commits on clean exit and rolls back on any exception
    (connection.py:38-49). That wrapping transaction IS the all-or-nothing
    guarantee: a reader sees the complete old snapshot or the complete new one.
    """
    with matcher_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_CREATE_DDL)
        cur.execute("TRUNCATE apifootball_events")
        if rows:
            execute_batch(cur, _INSERT_SQL, rows)
