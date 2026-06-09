"""Thread-safe sliding-window rate limiter.

Two windows enforced simultaneously:
  1. Per-interval (e.g. 300 requests per 65s) — protects the live RPS cap.
  2. Per-day (e.g. 100k / day) — protects the plan quota.

`acquire()` blocks until both windows have headroom, then records the call.
`observe_headers()` lets the client correct drift from the API's own counters.

Design notes:
  * Sliding window via two `deque[float]` of timestamps. Each `acquire()`
    prunes expired entries from the front, then either fits the new call
    in or sleeps until the oldest call ages out.
  * One `threading.Lock` covers both deques. Hold-and-sleep is avoided: we
    compute a sleep duration under lock, release, sleep, then loop.
  * Header observation is best-effort: if the API reports fewer remaining
    than our deque suggests, we pad the deque so we slow down. We never
    *remove* recorded calls based on headers (we'd rather under-issue than
    over-issue).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping

# Default monotonic clock; tests inject a fake.
_DEFAULT_NOW = time.monotonic
_DEFAULT_SLEEP = time.sleep


class RateLimiter:
    def __init__(
        self,
        per_interval: int,
        interval_sec: float,
        daily_quota: int,
        *,
        day_sec: float = 86_400.0,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if per_interval < 1 or daily_quota < 1:
            raise ValueError("limits must be >= 1")
        self._per_interval = per_interval
        self._interval = interval_sec
        self._daily_quota = daily_quota
        self._day = day_sec
        self._now = now or _DEFAULT_NOW
        self._sleep = sleep or _DEFAULT_SLEEP
        self._lock = threading.Lock()
        self._short: deque[float] = deque()
        self._long: deque[float] = deque()

    # ---- public ----

    def acquire(self) -> None:
        """Block until a slot is available in BOTH windows, then claim it."""
        while True:
            with self._lock:
                t = self._now()
                self._prune(t)
                short_full = len(self._short) >= self._per_interval
                long_full = len(self._long) >= self._daily_quota
                if not short_full and not long_full:
                    self._short.append(t)
                    self._long.append(t)
                    return
                # Compute sleep duration outside the lock.
                wait = 0.0
                if short_full:
                    wait = max(wait, self._short[0] + self._interval - t)
                if long_full:
                    wait = max(wait, self._long[0] + self._day - t)
            # Sleep with the lock released so other threads can proceed
            # when their slot frees up earlier.
            self._sleep(max(wait, 0.001))

    def observe_headers(self, headers: Mapping[str, str]) -> None:
        """Reconcile internal counters against API-reported remaining counts.

        Recognised headers (case-insensitive):
          * x-ratelimit-requests-limit / x-ratelimit-requests-remaining  (daily)
          * X-RateLimit-Limit         / X-RateLimit-Remaining            (per-interval)
        """
        # httpx headers are case-insensitive; we still .lower() to be safe
        # if a Mapping[str, str] is passed by tests.
        h = {k.lower(): v for k, v in headers.items()}
        self._reconcile(
            limit_key="x-ratelimit-requests-limit",
            remaining_key="x-ratelimit-requests-remaining",
            window="long",
            headers=h,
        )
        self._reconcile(
            limit_key="x-ratelimit-limit",
            remaining_key="x-ratelimit-remaining",
            window="short",
            headers=h,
        )

    def snapshot(self) -> dict[str, int]:
        """Diagnostic counts (used by logs / tests)."""
        with self._lock:
            return {
                "short_used": len(self._short),
                "short_limit": self._per_interval,
                "long_used": len(self._long),
                "long_limit": self._daily_quota,
            }

    # ---- internals ----

    def _prune(self, now: float) -> None:
        cutoff_short = now - self._interval
        while self._short and self._short[0] <= cutoff_short:
            self._short.popleft()
        cutoff_long = now - self._day
        while self._long and self._long[0] <= cutoff_long:
            self._long.popleft()

    def _reconcile(
        self,
        *,
        limit_key: str,
        remaining_key: str,
        window: str,
        headers: dict[str, str],
    ) -> None:
        try:
            limit = int(headers[limit_key])
            remaining = int(headers[remaining_key])
        except (KeyError, ValueError):
            return
        if limit < 1:
            return
        used = max(0, limit - remaining)
        with self._lock:
            t = self._now()
            self._prune(t)
            q = self._short if window == "short" else self._long
            local_limit = self._per_interval if window == "short" else self._daily_quota
            # Only ever inflate: never delete genuine records.
            # Scale `used` against our local limit in case plans differ.
            scaled = min(local_limit, int(used * (local_limit / limit)))
            while len(q) < scaled:
                q.append(t)
