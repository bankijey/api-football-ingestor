"""Fetchers: end-to-end through MockTransport + real Postgres (skips w/o DB).

Each fetcher is a thin glue layer: HTTP via ApiFootballClient, persist via
write_bronze. We verify both the call path (correct URL/params) and the DB
row landing in the right bronze table.
"""
from __future__ import annotations

import uuid

import httpx

from ingestor.fetchers.fixture_details import fetch_fixture_details
from ingestor.fetchers.fixtures_by_league import fetch_fixtures_by_league
from ingestor.fetchers.halftime_stats import fetch_halftime_stats
from ingestor.fetchers.leagues import fetch_leagues
from ingestor.http.client import ApiFootballClient
from ingestor.http.rate_limiter import RateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def _client(handler) -> ApiFootballClient:
    clk = _FakeClock()
    limiter = RateLimiter(
        per_interval=10_000, interval_sec=60.0, daily_quota=10_000,
        now=clk.now, sleep=clk.sleep,
    )
    return ApiFootballClient(
        base_url="https://v3.football.api-sports.io",
        host="v3.football.api-sports.io",
        api_key="k",
        rate_limiter=limiter,
        timeout_sec=5.0,
        retry_max_attempts=1,
        retry_backoff_base_sec=0.001,
        retry_backoff_max_sec=0.002,
        transport=httpx.MockTransport(handler),
    )


def _count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return int(cur.fetchone()[0])


def test_fetch_leagues_writes_bronze_leagues(pg_conn) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": [{"league": {"id": 1}}], "errors": []})

    with _client(handler) as c:
        outcome = fetch_leagues(c, pg_conn, run_id=uuid.uuid4())

    assert outcome.write.changed
    assert captured["url"].endswith("/leagues")
    assert _count(pg_conn, "bronze_leagues") == 1


def test_fetch_fixtures_by_league_sends_params_and_types_columns(pg_conn) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": [], "errors": []})

    with _client(handler) as c:
        outcome = fetch_fixtures_by_league(
            c, pg_conn, run_id=uuid.uuid4(), league_id=39, season=2025,
        )

    assert "league=39" in captured["url"]
    assert "season=2025" in captured["url"]
    with pg_conn.cursor() as cur:
        cur.execute("SELECT league_id, season FROM bronze_fixtures WHERE id = %s",
                    (outcome.write.bronze_row_id,))
        assert cur.fetchone() == (39, 2025)


def test_fetch_fixture_details_writes_typed_fixture_id(pg_conn) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": [], "errors": []})

    with _client(handler) as c:
        outcome = fetch_fixture_details(c, pg_conn, run_id=uuid.uuid4(), fixture_id=12345)

    with pg_conn.cursor() as cur:
        cur.execute("SELECT fixture_id FROM bronze_fixture_details WHERE id = %s",
                    (outcome.write.bronze_row_id,))
        assert cur.fetchone() == (12345,)


def test_fetch_halftime_stats_sends_half_true(pg_conn) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": [], "errors": []})

    with _client(handler) as c:
        fetch_halftime_stats(c, pg_conn, run_id=uuid.uuid4(), fixture_id=42)

    assert "fixture=42" in captured["url"]
    assert "half=true" in captured["url"]
    assert _count(pg_conn, "bronze_halftime_stats") == 1


def test_repeat_fetch_skips_via_hash(pg_conn) -> None:
    """Phase A's hash-skip behaviour proven end-to-end: same response → no new row."""
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": [{"id": 1}], "errors": []})

    with _client(handler) as c:
        rid = uuid.uuid4()
        fetch_leagues(c, pg_conn, run_id=rid)
        o2 = fetch_leagues(c, pg_conn, run_id=rid)

    assert o2.write.changed is False
    assert o2.write.bronze_row_id is None
    assert _count(pg_conn, "bronze_leagues") == 1
