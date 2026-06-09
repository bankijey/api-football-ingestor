"""Orchestrator: per-task isolation, end-to-end runner, resume semantics."""
from __future__ import annotations

import httpx
import pytest

from ingestor.checkpoint.store import CheckpointStore
from ingestor.http.client import ApiFootballClient
from ingestor.http.rate_limiter import RateLimiter
from ingestor.orchestrator.phase_a import run_phase_a
from ingestor.orchestrator.runner import RunArgs, run_ingestion
from ingestor.selection.league_filter import LeagueWork

# ---------- helpers ----------

class _Clk:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def _client(handler) -> ApiFootballClient:
    clk = _Clk()
    return ApiFootballClient(
        base_url="https://v3.football.api-sports.io",
        host="v3.football.api-sports.io",
        api_key="k",
        rate_limiter=RateLimiter(per_interval=10_000, interval_sec=60.0,
                                 daily_quota=10_000, now=clk.now, sleep=clk.sleep),
        timeout_sec=5.0, retry_max_attempts=1,
        retry_backoff_base_sec=0.001, retry_backoff_max_sec=0.002,
        transport=httpx.MockTransport(handler),
    )


def _count(pool, table: str) -> int:
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return int(cur.fetchone()[0])


# ---------- phase A isolation ----------

def test_phase_a_isolates_one_failing_league(pg_pool) -> None:
    """League 99 returns 500; leagues 39 and 140 succeed."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "league=99" in str(request.url):
            return httpx.Response(500, json={})
        return httpx.Response(200, json={"response": [], "errors": []})

    cs = CheckpointStore(pg_pool)
    rid = cs.start_run()
    with _client(handler) as c:
        res = run_phase_a(
            client=c, pool=pg_pool, checkpoints=cs, run_id=rid,
            leagues=[
                LeagueWork(39,  2025, {"fixtures": {"lineups": True}}),
                LeagueWork(99,  2025, {"fixtures": {"lineups": True}}),
                LeagueWork(140, 2025, {"fixtures": {"lineups": True}}),
            ],
            max_workers=3,
        )

    assert res.counters.ok == 2
    assert res.counters.failed == 1
    assert _count(pg_pool, "bronze_fixtures") == 2
    # The failure landed in dead_letter, and exactly one checkpoint says failed.
    assert _count(pg_pool, "dead_letter") == 1
    with pg_pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, key FROM ingestion_checkpoints ORDER BY key")
        rows = cur.fetchall()
    by_key = {k: s for s, k in rows}
    assert by_key == {"39:2025": "succeeded", "99:2025": "failed", "140:2025": "succeeded"}


# ---------- end-to-end runner ----------

def _leagues_payload() -> dict:
    return {
        "response": [
            {
                "league": {"id": 39, "name": "PL"},
                "seasons": [{"year": 2025, "current": True,
                             "coverage": {"fixtures": {"lineups": True,
                                                       "statistics_fixtures": True,
                                                       "statistics_players": True,
                                                       "events": True}}}],
            },
            {
                # No coverage flags → its fixtures should NOT enter Phase B.
                "league": {"id": 200, "name": "X"},
                "seasons": [{"year": 2025, "current": True,
                             "coverage": {"fixtures": {"lineups": False,
                                                       "statistics_fixtures": False,
                                                       "statistics_players": False,
                                                       "events": False}}}],
            },
        ],
        "errors": [],
    }


def _fixtures_payload(league_id: int, fids: list[int], status: str, ts: int) -> dict:
    return {
        "response": [
            {"fixture": {"id": fid, "timestamp": ts, "status": {"short": status}},
             "league": {"id": league_id, "season": 2025}}
            for fid in fids
        ],
        "errors": [],
    }


def _empty_ok() -> dict:
    return {"response": [], "errors": []}


@pytest.fixture()
def runner_settings(pg_pool):
    # Settings whose db_dsn matches the pg_pool's pinned schema.
    from ingestor.config import Settings
    dsn = pg_pool._pool._kwargs["dsn"]
    s = Settings(
        _env_file=None,
        apifootball_key="test-key",            # type: ignore[arg-type]
        db_dsn=dsn,
        thread_pool_size=2,
        lookback_days=14,
    )  # type: ignore[call-arg]
    return s


def test_end_to_end_runner_persists_all_layers(monkeypatch, pg_pool, runner_settings) -> None:
    """One full pass: leagues, fixtures-by-league, fixture-details, halftime."""
    import time as _time
    now_ts = int(_time.time())

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/leagues"):
            return httpx.Response(200, json=_leagues_payload())
        if "/fixtures" in url and "league=39" in url:
            return httpx.Response(200, json=_fixtures_payload(39, [101, 102], "FT", now_ts - 3600))
        if "/fixtures" in url and "league=200" in url:
            return httpx.Response(200, json=_fixtures_payload(200, [999], "FT", now_ts - 3600))
        if "/fixtures/statistics" in url:
            return httpx.Response(200, json=_empty_ok())
        if "/fixtures" in url and "id=" in url:
            return httpx.Response(200, json=_empty_ok())
        return httpx.Response(404, json={})

    # Patch the client factory so the runner uses our MockTransport.
    from ingestor.orchestrator import runner as _runner

    def _from_settings(settings, **_):
        return _client(handler)

    monkeypatch.setattr(_runner.ApiFootballClient, "from_settings", classmethod(lambda cls, s: _client(handler)))

    result = run_ingestion(runner_settings, args=RunArgs())

    assert result.status == "succeeded"
    assert result.leagues_total == 2          # 39 + 200 (both current)
    assert result.fixtures_total == 2         # only 101, 102 — league 200 has no coverage
    # Bronze layers populated:
    assert _count(pg_pool, "bronze_leagues") == 1
    assert _count(pg_pool, "bronze_fixtures") == 2          # one per league in Phase A
    assert _count(pg_pool, "bronze_fixture_details") == 2   # 101, 102
    assert _count(pg_pool, "bronze_halftime_stats") == 2
    # Phase B counters
    assert result.phase_b.counters.failed == 0
    assert result.phase_b.counters.ok + result.phase_b.counters.unchanged == 4


def test_resume_skips_already_succeeded(monkeypatch, pg_pool, runner_settings) -> None:
    """Second run with same run_id sees checkpoints and skips work."""
    import time as _time
    now_ts = int(_time.time())
    call_counts: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        call_counts[url] = call_counts.get(url, 0) + 1
        if url.endswith("/leagues"):
            return httpx.Response(200, json=_leagues_payload())
        if "league=39" in url:
            return httpx.Response(200, json=_fixtures_payload(39, [101], "FT", now_ts - 3600))
        if "league=200" in url:
            return httpx.Response(200, json=_fixtures_payload(200, [], "FT", now_ts - 3600))
        if "/fixtures/statistics" in url:
            return httpx.Response(200, json=_empty_ok())
        if "id=" in url:
            return httpx.Response(200, json=_empty_ok())
        return httpx.Response(404, json={})

    monkeypatch.setattr(
        "ingestor.orchestrator.runner.ApiFootballClient.from_settings",
        classmethod(lambda cls, s: _client(handler)),
    )

    r1 = run_ingestion(runner_settings, args=RunArgs())
    assert r1.status == "succeeded"

    # Replay with the same run_id; every Phase A + Phase B task should skip.
    r2 = run_ingestion(runner_settings, args=RunArgs(resume_run_id=r1.run_id))
    assert r2.phase_a.counters.skipped == 2
    assert r2.phase_a.counters.ok == 0
    assert r2.phase_b.counters.skipped == 2  # 1 fixture * 2 endpoints
    assert r2.phase_b.counters.ok == 0
