"""Inspect an httpx.Response and raise the appropriate HttpError taxonomy.

API-Football quirks handled:
  * Returns 200 with a non-empty `errors` field on some failures.
  * Returns 5xx on transient infra issues; retry those.
  * Returns 429 when the per-minute window is blown; retry with backoff.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from .errors import ApiResponseError, NonRetryableHttpError, RetryableHttpError

# 4xx codes that are NOT permanent — these get retried.
_RETRYABLE_4XX = {408, 425, 429}

# Substrings in an API-Football `errors` body that indicate a transient
# rate-limit / quota issue worth retrying instead of dead-lettering.
_RATELIMIT_KEYS = {"ratelimit", "requests"}
_RATELIMIT_PHRASES = ("too many requests", "limit of requests", "quota")


def validate_response(response: httpx.Response) -> dict[str, Any]:
    """Return parsed JSON body if the call succeeded; raise otherwise."""
    status = response.status_code

    if 500 <= status < 600:
        raise RetryableHttpError(
            f"server error {status}",
            status_code=status,
            retry_after_sec=_parse_retry_after(response.headers),
        )
    if status in _RETRYABLE_4XX:
        raise RetryableHttpError(
            f"retryable client error {status}",
            status_code=status,
            retry_after_sec=_parse_retry_after(response.headers),
        )
    if 400 <= status < 500:
        raise NonRetryableHttpError(f"client error {status}", status_code=status)
    if status != 200:
        # 1xx/3xx shouldn't reach us with httpx default follow-redirects;
        # treat anything not in 2xx as non-retryable.
        raise NonRetryableHttpError(f"unexpected status {status}", status_code=status)

    try:
        body = response.json()
    except json.JSONDecodeError as e:
        raise NonRetryableHttpError(f"invalid JSON: {e}", status_code=status) from e

    if not isinstance(body, dict):
        raise NonRetryableHttpError(
            f"unexpected JSON shape: {type(body).__name__}", status_code=status
        )

    errors = body.get("errors")
    if _is_nonempty_errors(errors):
        # API-Football quirk: returns HTTP 200 with a rate-limit message in
        # the body instead of a proper 429. Promote to retryable so the
        # retrier handles it instead of dead-lettering.
        if _looks_like_rate_limit(errors):
            raise RetryableHttpError(
                f"API in-body rate limit: {errors!r}",
                status_code=200,
                retry_after_sec=_parse_retry_after(response.headers),
            )
        raise ApiResponseError(f"API returned errors: {errors!r}", errors=errors)

    return body


def _looks_like_rate_limit(errors: object) -> bool:
    """True if an `errors` payload smells like a rate-limit / quota notice."""
    if isinstance(errors, dict):
        for k, v in errors.items():
            if isinstance(k, str) and k.lower() in _RATELIMIT_KEYS:
                return True
            if isinstance(v, str) and _phrase_match(v):
                return True
    elif isinstance(errors, list):
        for item in errors:
            if isinstance(item, str) and _phrase_match(item):
                return True
    elif isinstance(errors, str):
        return _phrase_match(errors)
    return False


def _phrase_match(s: str) -> bool:
    low = s.lower()
    return any(p in low for p in _RATELIMIT_PHRASES)


def _parse_retry_after(headers: httpx.Headers) -> float | None:
    """Read the standard `Retry-After` header. Returns seconds, or None."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    # Spec allows either a delta-seconds integer or an HTTP-date.
    # API-Football sends seconds in practice; ignore date form for simplicity.
    try:
        val = float(raw)
        return val if val >= 0 else None
    except (TypeError, ValueError):
        return None


def _is_nonempty_errors(errors: object) -> bool:
    """API-Football returns `errors` as either `[]` (ok) or `{...}` (failure).

    Some endpoints return `errors: []`, others `errors: {}`. Both are "ok".
    Anything with truthy content is a failure.
    """
    if errors is None:
        return False
    if isinstance(errors, list | dict):
        return len(errors) > 0
    # Defensive: any other shape with truthy content is suspicious enough.
    return bool(errors)
