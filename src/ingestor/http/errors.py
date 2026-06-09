"""Exception taxonomy for the HTTP layer.

The retry policy keys off these classes — if you add a new failure mode,
classify it as retryable or non-retryable here.
"""
from __future__ import annotations


class HttpError(Exception):
    """Base for any HTTP-layer failure."""


class RetryableHttpError(HttpError):
    """Transient: tenacity should retry (network blip, 429, 5xx).

    `retry_after_sec` (when set) is the server's hint via the Retry-After
    header — the retrier prefers it over exponential backoff so we wake
    exactly when the window resets, not earlier and not too much later.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_sec: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_sec = retry_after_sec


class NonRetryableHttpError(HttpError):
    """Permanent: bad request, auth, not found — retrying won't help."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiResponseError(NonRetryableHttpError):
    """HTTP 200 but the API-Football `errors` field is non-empty.

    Treated as non-retryable by default. (Some `errors` payloads — e.g. a
    rate-limit notice — could in principle be retryable, but we don't try
    to special-case them in v1; the rate limiter + 429 path covers quota.)
    """

    def __init__(self, message: str, *, errors: object) -> None:
        super().__init__(message, status_code=200)
        self.errors = errors
