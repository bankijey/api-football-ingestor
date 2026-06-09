"""Heartbeat: thread starts, ticks, stops cleanly; errors don't crash it."""
from __future__ import annotations

import time
from unittest.mock import MagicMock
from uuid import uuid4

from ingestor.heartbeat import Heartbeat


def test_heartbeat_ticks_at_interval() -> None:
    checkpoints = MagicMock()
    rid = uuid4()
    with Heartbeat(checkpoints, rid, interval_sec=0.05):
        time.sleep(0.18)
    # Initial tick + at least 2 interval ticks → 3+ calls.
    assert checkpoints.heartbeat.call_count >= 3
    checkpoints.heartbeat.assert_called_with(rid)


def test_heartbeat_swallows_exceptions() -> None:
    checkpoints = MagicMock()
    checkpoints.heartbeat.side_effect = RuntimeError("db gone")
    rid = uuid4()
    # Should not raise, even though every tick fails.
    with Heartbeat(checkpoints, rid, interval_sec=0.05):
        time.sleep(0.12)
    assert checkpoints.heartbeat.call_count >= 2


def test_heartbeat_double_start_is_noop() -> None:
    checkpoints = MagicMock()
    hb = Heartbeat(checkpoints, uuid4(), interval_sec=10)
    hb.start()
    t1 = hb._thread
    hb.start()
    assert hb._thread is t1
    hb.stop()
