"""CheckpointStore: lifecycle + per-task status transitions."""
from __future__ import annotations

from ingestor.checkpoint.store import CheckpointStore, ck_fixture, ck_league


def _run_row(pool, run_id):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, args, counters, last_heartbeat_at FROM ingestion_runs WHERE run_id = %s",
            (str(run_id),),
        )
        return cur.fetchone()


def test_start_run_creates_running_row(pg_pool) -> None:
    cs = CheckpointStore(pg_pool)
    rid = cs.start_run(args={"season": 2025})
    status, args, counters, hb = _run_row(pg_pool, rid)
    assert status == "running"
    assert args == {"season": 2025}
    assert counters == {}
    assert hb is not None


def test_heartbeat_advances_timestamp(pg_pool) -> None:
    cs = CheckpointStore(pg_pool)
    rid = cs.start_run()
    _, _, _, hb1 = _run_row(pg_pool, rid)
    cs.heartbeat(rid)
    _, _, _, hb2 = _run_row(pg_pool, rid)
    assert hb2 >= hb1


def test_finish_run_records_terminal_status_and_counters(pg_pool) -> None:
    cs = CheckpointStore(pg_pool)
    rid = cs.start_run()
    cs.finish_run(rid, status="partial", counters={"phase_a": {"failed": 1}})
    status, _, counters, _ = _run_row(pg_pool, rid)
    assert status == "partial"
    assert counters == {"phase_a": {"failed": 1}}


def test_checkpoint_transitions_and_attempts(pg_pool) -> None:
    cs = CheckpointStore(pg_pool)
    rid = cs.start_run()
    ck = ck_league(39, 2025, "fixtures_by_league")

    assert cs.is_succeeded(rid, ck) is False
    cs.mark_pending(rid, ck)
    cs.mark_pending(rid, ck)        # second attempt → bumps to 2
    cs.mark_failed(rid, ck, error="boom")
    assert cs.is_succeeded(rid, ck) is False

    cs.mark_pending(rid, ck)        # third attempt → bumps to 3
    cs.mark_succeeded(rid, ck)
    assert cs.is_succeeded(rid, ck) is True

    with pg_pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT status, attempts, last_error FROM ingestion_checkpoints WHERE run_id=%s",
            (str(rid),),
        )
        status, attempts, last_error = cur.fetchone()
    assert status == "succeeded"
    assert attempts == 3
    # mark_succeeded clears the error field
    assert last_error is None


def test_ck_helpers_build_keys() -> None:
    a = ck_league(39, 2025, "x")
    b = ck_fixture(42, "y")
    assert a.scope == "league" and a.key == "39:2025"
    assert b.scope == "fixture" and b.key == "42"
