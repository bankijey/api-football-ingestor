"""Phase B — fan out (fixture_id x {fixture_details, halftime_stats}).

Each (fixture_id, endpoint) pair is one task. Failures isolated per pair:
fixture 123's halftime stats failing doesn't prevent fixture 124's details
from running, or even fixture 123's *details* from running independently.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from ..checkpoint.store import CheckpointStore, ck_fixture
from ..db.connection import ConnectionPool
from ..deadletter import record_failure
from ..fetchers.fixture_details import (
    ENDPOINT as FIXTURE_DETAILS_ENDPOINT,
)
from ..fetchers.fixture_details import (
    fetch_fixture_details,
)
from ..fetchers.halftime_stats import (
    ENDPOINT as HALFTIME_STATS_ENDPOINT,
)
from ..fetchers.halftime_stats import (
    fetch_halftime_stats,
)
from ..http.client import ApiFootballClient
from ..logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class PhaseBCounters:
    ok: int = 0
    skipped: int = 0
    unchanged: int = 0
    failed: int = 0


@dataclass
class PhaseBResult:
    counters: PhaseBCounters = field(default_factory=PhaseBCounters)


# A "fetch fn" is anything that takes (client, conn, *, run_id, fixture_id)
# and returns an outcome whose `.write.changed` indicates new vs duplicate.
_FetchFn = Callable[..., Any]

_FETCHERS: list[tuple[str, _FetchFn]] = [
    (FIXTURE_DETAILS_ENDPOINT, fetch_fixture_details),
    (HALFTIME_STATS_ENDPOINT, fetch_halftime_stats),
]


def run_phase_b(
    *,
    client: ApiFootballClient,
    pool: ConnectionPool,
    checkpoints: CheckpointStore,
    run_id: UUID,
    fixture_ids: Iterable[int],
    max_workers: int,
) -> PhaseBResult:
    # Materialize for cardinality + reuse
    fids = list(fixture_ids)
    # Cartesian product: every fixture x every Phase-B endpoint
    tasks: list[tuple[int, str, _FetchFn]] = [
        (fid, endpoint, fn) for fid in fids for endpoint, fn in _FETCHERS
    ]

    result = PhaseBResult()
    lock = threading.Lock()

    def run_one(item: tuple[int, str, _FetchFn]) -> None:
        fid, endpoint, fn = item
        ck = ck_fixture(fid, endpoint)
        log = _log.bind(fixture_id=fid, endpoint=endpoint)

        if checkpoints.is_succeeded(run_id, ck):
            log.info("phase_b.skip_resume")
            with lock:
                result.counters.skipped += 1
            return

        checkpoints.mark_pending(run_id, ck)
        try:
            with pool.connection() as conn:
                outcome = fn(client, conn, run_id=run_id, fixture_id=fid)
            checkpoints.mark_succeeded(run_id, ck)
            with lock:
                if outcome.write.changed:
                    result.counters.ok += 1
                else:
                    result.counters.unchanged += 1
            log.info("phase_b.ok", changed=outcome.write.changed)
        except Exception as e:
            checkpoints.mark_failed(run_id, ck, error=f"{type(e).__name__}: {e}")
            try:
                record_failure(
                    pool,
                    run_id=run_id,
                    endpoint=endpoint,
                    request_params={"fixture_id": fid},
                    error=e,
                )
            except Exception:
                log.exception("phase_b.deadletter_failed")
            with lock:
                result.counters.failed += 1
            log.warning("phase_b.failed", error_class=type(e).__name__, error=str(e))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="phase_b") as ex:
        list(ex.map(run_one, tasks))

    return result
