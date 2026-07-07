"""apifootball_events projection: mapping, filtering, latest-per-key,
atomic replace, and the runner's succeeded-only gate."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from ingestor.projection import build_projection

# ---------- helpers ----------

_NOW = 1_000_000  # fixed clock; fixtures are placed relative to this.


def _fx(
    fid: int,
    status: str,
    ts: int,
    *,
    league_id: int = 39,
    league_name: str = "PL",
    home: tuple[str, int] = ("Home FC", 10),
    away: tuple[str, int] = ("Away FC", 20),
) -> dict[str, Any]:
    return {
        "fixture": {"id": fid, "timestamp": ts, "status": {"short": status}},
        "league": {"id": league_id, "name": league_name},
        "teams": {
            "home": {"id": home[1], "name": home[0]},
            "away": {"id": away[1], "name": away[0]},
        },
    }


def _seed(pool, league_id, season, response, *, ingested_at: str | None = None) -> None:
    from psycopg2.extras import Json

    payload = {"response": response, "errors": []}
    rid = str(uuid.uuid4())
    with pool.connection() as conn, conn.cursor() as cur:
        if ingested_at is None:
            cur.execute(
                "INSERT INTO bronze_fixtures "
                "(run_id, endpoint, request_params, response_hash, api_version, "
                " payload, league_id, season) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (rid, "fixtures_by_league", Json({}), "h", "v",
                 Json(payload), league_id, season),
            )
        else:
            cur.execute(
                "INSERT INTO bronze_fixtures "
                "(run_id, ingested_at, endpoint, request_params, response_hash, "
                " api_version, payload, league_id, season) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rid, ingested_at, "fixtures_by_league", Json({}), "h", "v",
                 Json(payload), league_id, season),
            )


_COLS = ("fixture_id", "e_id", "bookmaker_id", "sport_key", "start", "tid",
         "tournament", "home_team", "away_team", "home_id", "away_id", "url")


def _fetch_all(pool) -> list[dict[str, Any]]:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_COLS)} FROM apifootball_events ORDER BY fixture_id"
        )
        return [dict(zip(_COLS, r, strict=True)) for r in cur.fetchall()]


# ---------- AC3 / AC4: mapping + filtering ----------

def test_projection_keeps_only_ns_future_with_full_columns(pg_pool) -> None:
    _seed(pg_pool, 39, 2025, [
        _fx(101, "NS", _NOW + 3600),   # kept: NS + future
        _fx(102, "NS", _NOW - 3600),   # dropped: NS but in the past
        _fx(103, "FT", _NOW + 3600),   # dropped: future but not NS
    ])

    n = build_projection(bronze_pool=pg_pool, matcher_pool=pg_pool, now_ts=_NOW)
    assert n == 1

    rows = _fetch_all(pg_pool)
    assert len(rows) == 1
    row = rows[0]
    assert row["fixture_id"] == 101
    assert row["e_id"] == "apifootball;101"    # AC4: semicolon, not colon
    assert ";" in row["e_id"] and ":" not in row["e_id"]
    assert row["bookmaker_id"] == "apifootball"
    assert row["sport_key"] == "football"
    assert row["url"] is None
    assert row["tid"] == "39"
    assert row["tournament"] == "PL"
    assert row["home_team"] == "Home FC"
    assert row["away_team"] == "Away FC"
    assert row["home_id"] == "10"
    assert row["away_id"] == "20"
    # start is TIMESTAMPTZ from to_timestamp(fixture.timestamp)
    assert row["start"].timestamp() == _NOW + 3600


# ---------- AC7: latest ingest per (league, season) ----------

def test_reflects_only_newest_ingest_per_league_season(pg_pool) -> None:
    _seed(pg_pool, 39, 2025, [_fx(201, "NS", _NOW + 3600)],
          ingested_at="2026-01-01 00:00:00+00")
    _seed(pg_pool, 39, 2025, [_fx(202, "NS", _NOW + 7200)],
          ingested_at="2026-02-01 00:00:00+00")

    n = build_projection(bronze_pool=pg_pool, matcher_pool=pg_pool, now_ts=_NOW)
    assert n == 1
    assert [r["fixture_id"] for r in _fetch_all(pg_pool)] == [202]


# ---------- AC5: atomic replace leaves prior snapshot intact on failure ----------

def test_atomic_replace_keeps_prior_snapshot_on_mid_write_failure(
    pg_pool, monkeypatch
) -> None:
    # First build -> one committed prior row.
    _seed(pg_pool, 39, 2025, [_fx(301, "NS", _NOW + 3600)])
    build_projection(bronze_pool=pg_pool, matcher_pool=pg_pool, now_ts=_NOW)
    assert [r["fixture_id"] for r in _fetch_all(pg_pool)] == [301]

    # A new fixture would change the table on the next build...
    _seed(pg_pool, 140, 2025, [_fx(302, "NS", _NOW + 3600)])

    # ...but the INSERT blows up after TRUNCATE, before commit.
    import ingestor.projection as proj

    def _boom(*_a, **_k):
        raise RuntimeError("mid-write failure")

    monkeypatch.setattr(proj, "execute_batch", _boom)

    with pytest.raises(RuntimeError):
        build_projection(bronze_pool=pg_pool, matcher_pool=pg_pool, now_ts=_NOW)

    # Rolled back: the prior snapshot is intact — not partial, not empty.
    assert [r["fixture_id"] for r in _fetch_all(pg_pool)] == [301]


def test_empty_bronze_yields_empty_table(pg_pool) -> None:
    n = build_projection(bronze_pool=pg_pool, matcher_pool=pg_pool, now_ts=_NOW)
    assert n == 0
    assert _fetch_all(pg_pool) == []


# ---------- F3: bronze read streams via a server-side (named) cursor ----------

class _ConnSpy:
    """Records the ``name`` kwarg of every ``cursor(...)`` call, then delegates."""

    def __init__(self, conn: Any, names: list[str | None]) -> None:
        self._conn = conn
        self._names = names

    def cursor(self, *a: Any, **k: Any) -> Any:
        self._names.append(k.get("name"))
        return self._conn.cursor(*a, **k)

    def __getattr__(self, n: str) -> Any:
        return getattr(self._conn, n)


class _PoolSpy:
    """Wraps a ConnectionPool, yielding connections whose cursor calls are spied."""

    def __init__(self, pool: Any, names: list[str | None]) -> None:
        self._pool = pool
        self._names = names

    @contextmanager
    def connection(self) -> Iterator[_ConnSpy]:
        with self._pool.connection() as conn:
            yield _ConnSpy(conn, self._names)

    def __getattr__(self, n: str) -> Any:
        return getattr(self._pool, n)


def test_read_streams_with_server_side_cursor(pg_pool) -> None:
    # Two latest league-season payloads: one qualifies (NS + future), one does
    # not (FT + past). The projected row set must be exactly the qualifying one.
    _seed(pg_pool, 39, 2025, [_fx(401, "NS", _NOW + 3600)])   # projects
    _seed(pg_pool, 140, 2025, [_fx(402, "FT", _NOW - 3600)])  # dropped

    names: list[str | None] = []
    bronze_spy = _PoolSpy(pg_pool, names)

    n = build_projection(bronze_pool=bronze_spy, matcher_pool=pg_pool, now_ts=_NOW)

    # Output byte-identical to a client-side read: exactly the NS+future fixture.
    assert n == 1
    rows = _fetch_all(pg_pool)
    assert [r["fixture_id"] for r in rows] == [401]
    assert rows[0]["e_id"] == "apifootball;401"

    # The bronze read used a NAMED (server-side) cursor — fails for an unnamed one.
    assert any(name for name in names), f"expected a named cursor, got {names!r}"


# ---------- AC6: runner gate is succeeded-only + configured ----------

def test_should_project_gate() -> None:
    from ingestor.config import Settings
    from ingestor.orchestrator.runner import _should_project

    configured = Settings(  # type: ignore[call-arg]
        _env_file=None, apifootball_key="k",            # type: ignore[arg-type]
        matcher_db_dsn="postgresql://x/y",
    )
    unconfigured = Settings(  # type: ignore[call-arg]
        _env_file=None, apifootball_key="k",            # type: ignore[arg-type]
    )

    assert _should_project("succeeded", configured) is True
    assert _should_project("partial", configured) is False
    assert _should_project("failed", configured) is False
    # Empty MATCHER_DB_DSN disables the projection even on success.
    assert _should_project("succeeded", unconfigured) is False
