"""Tenacity retry policy.

Retryable exceptions:
  * RetryableHttpError (429, 5xx, 408, 425, in-body rate-limit)
  * httpx.TransportError (connect/read timeouts, DNS, broken pipe...)

Non-retryable: NonRetryableHttpError and its ApiResponseError subclass.

Wait strategy:
  * If the last exception carries `retry_after_sec` (parsed from the API's
    Retry-After header), honour it — that's the server telling us exactly
    when the window resets.
  * Otherwise fall back to randomised exponential backoff.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .errors import RetryableHttpError

T = TypeVar("T")

# Hard cap on a Retry-After wait, in case the server returns something absurd.
_RETRY_AFTER_CAP_SEC = 120.0


def make_retrier(
    *,
    max_attempts: int,
    backoff_base_sec: float,
    backoff_max_sec: float,
) -> Callable[[Callable[[], T]], T]:
    """Return a `run(callable)` helper applying our retry policy.

    Usage:
        run = make_retrier(max_attempts=7, backoff_base_sec=1, backoff_max_sec=30)
        body = run(lambda: client.get(url, params=p))
    """
    exp_wait = wait_random_exponential(multiplier=backoff_base_sec, max=backoff_max_sec)

    def wait(state: RetryCallState) -> float:
        exc = state.outcome.exception() if state.outcome else None
        if isinstance(exc, RetryableHttpError) and exc.retry_after_sec is not None:
            return min(exc.retry_after_sec, _RETRY_AFTER_CAP_SEC)
        return exp_wait(state)

    retrier = Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait,
        retry=retry_if_exception_type((RetryableHttpError, httpx.TransportError)),
        reraise=True,
    )

    def run(fn: Callable[[], T]) -> T:
        return retrier(fn)

    return run
