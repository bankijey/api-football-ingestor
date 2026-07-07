"""Heartbeat: thread starts, ticks, stops cleanly; errors don't crash it."""
from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import MagicMock
from uuid import uuid4

from ingestor.heartbeat import Heartbeat


def _poll_until(predicate: Callable[[], bool], deadline_sec: float = 2.0) -> None:
    """Spin until `predicate()` is true or a generous deadline elapses.

    Replaces a fixed `time.sleep` + exact-count assert: a slow machine simply
    takes longer to reach the target (still well under the deadline) instead of
    failing at a hard time boundary. The 2.0 s default is ~40x the ~0.1 s that
    three 0.05 s-interval ticks actually need, so timer granularity / CPU load
    can't race it.
    """
    end = time.monotonic() + deadline_sec
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.01)


def test_heartbeat_ticks_at_interval() -> None:
    checkpoints = MagicMock()
    rid = uuid4()
    # Poll *inside* the context so ticks keep firing while we wait.
    with Heartbeat(checkpoints, rid, interval_sec=0.05):
        _poll_until(lambda: checkpoints.heartbeat.call_count >= 3)
    # Initial tick + at least 2 interval ticks → 3+ calls.
    assert checkpoints.heartbeat.call_count >= 3
    checkpoints.heartbeat.assert_called_with(rid)


def test_heartbeat_swallows_exceptions() -> None:
    checkpoints = MagicMock()
    checkpoints.heartbeat.side_effect = RuntimeError("db gone")
    rid = uuid4()
    # Should not raise, even though every tick fails.
    with Heartbeat(checkpoints, rid, interval_sec=0.05):
        _poll_until(lambda: checkpoints.heartbeat.call_count >= 2)
    assert checkpoints.heartbeat.call_count >= 2


def test_heartbeat_double_start_is_noop() -> None:
    checkpoints = MagicMock()
    hb = Heartbeat(checkpoints, uuid4(), interval_sec=10)
    hb.start()
    t1 = hb._thread
    hb.start()
    assert hb._thread is t1
    hb.stop()
