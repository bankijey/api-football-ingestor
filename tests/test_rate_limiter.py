"""RateLimiter: sliding window correctness with injected clock."""
from __future__ import annotations

from ingestor.http.rate_limiter import RateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.slept.append(d)
        self.t += d


def _mk(per_interval: int = 3, interval: float = 10.0, daily: int = 100) -> tuple[RateLimiter, _FakeClock]:
    clk = _FakeClock()
    rl = RateLimiter(
        per_interval=per_interval,
        interval_sec=interval,
        daily_quota=daily,
        now=clk.now,
        sleep=clk.sleep,
    )
    return rl, clk


def test_under_limit_does_not_sleep() -> None:
    rl, clk = _mk()
    for _ in range(3):
        rl.acquire()
    assert clk.slept == []
    snap = rl.snapshot()
    assert snap["short_used"] == 3


def test_over_limit_blocks_until_oldest_expires() -> None:
    rl, clk = _mk(per_interval=3, interval=10.0)
    for _ in range(3):
        rl.acquire()
    # 4th call: must wait until the first one ages out (10s from t=0)
    rl.acquire()
    assert sum(clk.slept) >= 10.0
    # After sleeping `interval` seconds, the three original entries have aged
    # out and only the newly-appended 4th remains in the short window.
    assert rl.snapshot()["short_used"] == 1


def test_daily_quota_enforced() -> None:
    rl, clk = _mk(per_interval=1000, interval=10.0, daily=2)
    rl.acquire()
    rl.acquire()
    rl.acquire()  # third must wait ~a day
    assert sum(clk.slept) >= 86_400.0


def test_observe_headers_inflates_counter() -> None:
    rl, _ = _mk(per_interval=300, interval=60.0, daily=300)
    # We've issued 0 calls locally, but API says 250 of 300 already used today.
    rl.observe_headers({
        "x-ratelimit-requests-limit": "300",
        "x-ratelimit-requests-remaining": "50",
    })
    assert rl.snapshot()["long_used"] == 250


def test_observe_headers_ignored_when_missing() -> None:
    rl, _ = _mk()
    rl.observe_headers({"unrelated": "x"})
    assert rl.snapshot()["long_used"] == 0
