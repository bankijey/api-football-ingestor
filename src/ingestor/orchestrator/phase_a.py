"""Phase A — fan out fixtures-by-league fetches across a thread pool.

Per-league isolation: one failure (HTTP, DB, or validation) is recorded in
the checkpoint table and dead_letter; other leagues keep running. The
shared rate limiter inside `client` is the global throttle — pool size only
caps parallelism, not throughput.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from ..checkpoint.store import CheckpointStore, ck_league
from ..db.bronze_writer import WriteResult
from ..db.connection import ConnectionPool
from ..deadletter import record_failure
from ..fetchers.fixtures_by_league import (
    ENDPOINT as FIXTURES_BY_LEAGUE_ENDPOINT,
)
from ..fetchers.fixtures_by_league import (
    FixturesByLeagueOutcome,
    fetch_fixtures_by_league,
)
from ..http.client import ApiFootballClient
from ..logging_setup import get_logger
from ..selection.league_filter import LeagueWork

_log = get_logger(__name__)


@dataclass
class PhaseACounters:
    ok: int = 0
    skipped: int = 0      # already-succeeded on resume
    unchanged: int = 0    # hash-skip in bronze writer
    failed: int = 0


@dataclass
class PhaseAResult:
    outcomes: list[FixturesByLeagueOutcome] = field(default_factory=list)
    counters: PhaseACounters = field(default_factory=PhaseACounters)


def run_phase_a(
    *,
    client: ApiFootballClient,
    pool: ConnectionPool,
    checkpoints: CheckpointStore,
    run_id: UUID,
    leagues: Iterable[LeagueWork],
    max_workers: int,
) -> PhaseAResult:
    result = PhaseAResult()
    lock = threading.Lock()

    def task(work: LeagueWork) -> None:
        ck = ck_league(work.league_id, work.season, FIXTURES_BY_LEAGUE_ENDPOINT)
        log = _log.bind(league_id=work.league_id, season=work.season, endpoint=FIXTURES_BY_LEAGUE_ENDPOINT)

        if checkpoints.is_succeeded(run_id, ck):
            # Reload the most recent bronze payload so Phase B can still derive
            # fixture ids from it. Without this, resuming a fully-Phase-A-done
            # run would produce an empty Phase B work list.
            payload = _load_latest_payload(pool, work.league_id, work.season)
            if payload is not None:
                synthetic = FixturesByLeagueOutcome(
                    league_id=work.league_id,
                    season=work.season,
                    payload=payload,
                    write=WriteResult(
                        endpoint=FIXTURES_BY_LEAGUE_ENDPOINT,
                        params_hash="", response_hash="",
                        changed=False, bronze_row_id=None,
                    ),
                )
                with lock:
                    result.outcomes.append(synthetic)
            log.info("phase_a.skip_resume", has_cached_payload=payload is not None)
            with lock:
                result.counters.skipped += 1
            return

        checkpoints.mark_pending(run_id, ck)
        try:
            with pool.connection() as conn:
                outcome = fetch_fixtures_by_league(
                    client, conn,
                    run_id=run_id,
                    league_id=work.league_id,
                    season=work.season,
                )
            checkpoints.mark_succeeded(run_id, ck)
            with lock:
                result.outcomes.append(outcome)
                if outcome.write.changed:
                    result.counters.ok += 1
                else:
                    result.counters.unchanged += 1
            log.info(
                "phase_a.ok",
                changed=outcome.write.changed,
                fixture_count=len(outcome.payload.get("response") or []),
            )
        except Exception as e:
            checkpoints.mark_failed(run_id, ck, error=f"{type(e).__name__}: {e}")
            try:
                record_failure(
                    pool,
                    run_id=run_id,
                    endpoint=FIXTURES_BY_LEAGUE_ENDPOINT,
                    request_params={"league_id": work.league_id, "season": work.season},
                    error=e,
                )
            except Exception:
                log.exception("phase_a.deadletter_failed")
            with lock:
                result.counters.failed += 1
            log.warning("phase_a.failed", error_class=type(e).__name__, error=str(e))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="phase_a") as ex:
        list(ex.map(task, leagues))

    return result


def _load_latest_payload(pool: ConnectionPool, league_id: int, season: int) -> dict[str, Any] | None:
    """Most recent bronze_fixtures payload for (league, season), or None."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload FROM bronze_fixtures
             WHERE league_id = %s AND season = %s
             ORDER BY ingested_at DESC LIMIT 1
            """,
            (league_id, season),
        )
        row = cur.fetchone()
        return row[0] if row else None
