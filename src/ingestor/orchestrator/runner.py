"""End-to-end run: leagues → fixtures-by-league → derive ids → phase B → finish.

This is the *only* place where dependency ordering between phases lives.
Each phase's tasks are isolated; the runner only fails if a phase setup
step itself blows up (DB unreachable, etc).

Resume: pass `resume_run_id` to continue an existing run. Checkpoints skip
already-succeeded work; failed tasks get re-attempted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ..checkpoint.store import CheckpointStore
from ..config import Settings
from ..db.connection import ConnectionPool
from ..db.migrations import apply_migrations
from ..fetchers.leagues import fetch_leagues
from ..heartbeat import Heartbeat
from ..http.client import ApiFootballClient
from ..logging_setup import bind_run_context, clear_run_context, configure_logging, get_logger
from ..selection.fixture_filter import extract_fixture_records, select_fixture_ids
from ..selection.league_filter import coverage_by_league, select_leagues
from .phase_a import PhaseAResult, run_phase_a
from .phase_b import PhaseBResult, run_phase_b

_log = get_logger(__name__)


@dataclass
class RunResult:
    run_id: UUID
    status: str           # 'succeeded' | 'partial' | 'failed'
    phase_a: PhaseAResult
    phase_b: PhaseBResult
    leagues_total: int
    fixtures_total: int


@dataclass
class RunArgs:
    """Subset of inputs we want recorded on `ingestion_runs.args`."""
    # When set, replaces the default `current=true` season filter in
    # select_leagues. Use [2019,2020,2021,2022] to backfill historical seasons.
    seasons_override: list[int] | None = None
    league_subset_override: list[int] | None = None
    lookback_days_override: int | None = None
    resume_run_id: UUID | None = None
    # Phase-B time-window overrides (epoch seconds, UTC). When either is set,
    # they replace the rolling lookback window entirely.
    from_ts: int | None = None
    to_ts: int | None = None

    def to_record(self) -> dict[str, Any]:
        d = asdict(self)
        if d.get("resume_run_id") is not None:
            d["resume_run_id"] = str(d["resume_run_id"])
        return d


def run_ingestion(
    settings: Settings,
    *,
    args: RunArgs | None = None,
    migrations_dir: Path | None = None,
) -> RunResult:
    configure_logging(settings.log_level)
    args = args or RunArgs()
    pool = ConnectionPool.from_settings(settings)
    checkpoints = CheckpointStore(pool)

    try:
        # 1. Schema is current.
        if migrations_dir is not None:
            with pool.connection() as conn:
                apply_migrations(conn, migrations_dir)

        # 2. Run row.
        if args.resume_run_id is not None:
            run_id = args.resume_run_id
            _log.info("run.resume", run_id=str(run_id))
        else:
            run_id = checkpoints.start_run(args=args.to_record())
        bind_run_context(run_id=str(run_id))

        try:
            client = ApiFootballClient.from_settings(settings)
            with client, Heartbeat(checkpoints, run_id, interval_sec=30.0):
                phase_a, phase_b, leagues_total, fixtures_total = _execute_phases(
                    settings=settings,
                    args=args,
                    client=client,
                    pool=pool,
                    checkpoints=checkpoints,
                    run_id=run_id,
                )

            status = _terminal_status(phase_a, phase_b)
            counters = {
                "leagues_total": leagues_total,
                "fixtures_total": fixtures_total,
                "phase_a": asdict(phase_a.counters),
                "phase_b": asdict(phase_b.counters),
            }
            checkpoints.finish_run(run_id, status=status, counters=counters)
            _log.info("run.done", status=status, counters=counters)

            return RunResult(
                run_id=run_id, status=status,
                phase_a=phase_a, phase_b=phase_b,
                leagues_total=leagues_total, fixtures_total=fixtures_total,
            )
        except Exception as e:
            checkpoints.finish_run(run_id, status="failed",
                                   counters={"error": f"{type(e).__name__}: {e}"})
            _log.exception("run.crashed")
            raise
        finally:
            clear_run_context()
    finally:
        pool.closeall()


# ---- internals ----


def _execute_phases(
    *,
    settings: Settings,
    args: RunArgs,
    client: ApiFootballClient,
    pool: ConnectionPool,
    checkpoints: CheckpointStore,
    run_id: UUID,
) -> tuple[PhaseAResult, PhaseBResult, int, int]:
    # Leagues catalogue.
    with pool.connection() as conn:
        leagues_outcome = fetch_leagues(client, conn, run_id=run_id)
    subset = args.league_subset_override or settings.league_subset or None
    works = select_leagues(
        leagues_outcome.payload,
        subset=subset,
        seasons=args.seasons_override,
    )
    _log.info(
        "run.leagues_selected",
        count=len(works),
        seasons_override=args.seasons_override,
    )

    # Phase A.
    phase_a = run_phase_a(
        client=client, pool=pool, checkpoints=checkpoints, run_id=run_id,
        leagues=works, max_workers=settings.thread_pool_size,
    )

    # Derive Phase B work from Phase A payloads.
    records = []
    for o in phase_a.outcomes:
        records.extend(extract_fixture_records(o.payload))
    lookback = args.lookback_days_override if args.lookback_days_override is not None else settings.lookback_days
    fixture_ids = select_fixture_ids(
        records,
        coverage_by_league(works),
        statuses=settings.fixture_statuses,
        lookback_days=lookback,
        from_ts=args.from_ts,
        to_ts=args.to_ts,
    )
    _log.info(
        "run.fixtures_selected",
        count=len(fixture_ids),
        window=("range" if (args.from_ts or args.to_ts) else f"lookback_{lookback}d"),
    )

    # Phase B.
    phase_b = run_phase_b(
        client=client, pool=pool, checkpoints=checkpoints, run_id=run_id,
        fixture_ids=fixture_ids, max_workers=settings.thread_pool_size,
    )

    return phase_a, phase_b, len(works), len(fixture_ids)


def _terminal_status(a: PhaseAResult, b: PhaseBResult) -> str:
    if a.counters.failed == 0 and b.counters.failed == 0:
        return "succeeded"
    return "partial"
