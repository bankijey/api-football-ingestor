"""Periodic heartbeat — proves the run is still alive.

Daemon thread that bumps `ingestion_runs.last_heartbeat_at` every N seconds
until stopped. v1: just updates the timestamp; a future "dead man's switch"
monitor can alert on stale heartbeats.

Use as a context manager around the run body:

    with Heartbeat(checkpoints, run_id, interval_sec=30):
        ... long work ...
"""
from __future__ import annotations

import threading
from types import TracebackType
from uuid import UUID

from .checkpoint.store import CheckpointStore
from .logging_setup import get_logger

_log = get_logger(__name__)


class Heartbeat:
    def __init__(
        self,
        checkpoints: CheckpointStore,
        run_id: UUID,
        *,
        interval_sec: float = 30.0,
    ) -> None:
        self._checkpoints = checkpoints
        self._run_id = run_id
        self._interval = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="heartbeat", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)
            self._thread = None

    def _loop(self) -> None:
        # Bump immediately so the first tick lands without waiting `interval`.
        self._tick()
        while not self._stop.wait(self._interval):
            self._tick()

    def _tick(self) -> None:
        try:
            self._checkpoints.heartbeat(self._run_id)
        except Exception as e:
            _log.warning("heartbeat.failed", error_class=type(e).__name__, error=str(e))

    def __enter__(self) -> Heartbeat:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
