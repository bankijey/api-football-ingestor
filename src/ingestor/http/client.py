"""ApiFootballClient — the ONLY way out to api-sports.io.

Wires together: shared rate limiter → httpx call → response validation →
retry on RetryableHttpError / transport errors. Returns parsed JSON `dict`.

Usage:
    with ApiFootballClient.from_settings(settings) as client:
        body = client.get("/leagues", params={})
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx

from ..config import Settings
from ..logging_setup import get_logger
from .rate_limiter import RateLimiter
from .retry import make_retrier
from .validation import validate_response

_log = get_logger(__name__)


class ApiFootballClient:
    def __init__(
        self,
        *,
        base_url: str,
        host: str,
        api_key: str,
        rate_limiter: RateLimiter,
        timeout_sec: float,
        retry_max_attempts: int,
        retry_backoff_base_sec: float,
        retry_backoff_max_sec: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "x-rapidapi-host": host,
                "x-rapidapi-key": api_key,
                "accept": "application/json",
            },
            timeout=timeout_sec,
            transport=transport,
        )
        self._rate_limiter = rate_limiter
        self._run = make_retrier(
            max_attempts=retry_max_attempts,
            backoff_base_sec=retry_backoff_base_sec,
            backoff_max_sec=retry_backoff_max_sec,
        )

    # ---- construction ----

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> ApiFootballClient:
        limiter = rate_limiter or RateLimiter(
            per_interval=settings.rate_limit_per_min,
            interval_sec=float(settings.rate_limit_window_sec),
            daily_quota=settings.daily_quota,
        )
        return cls(
            base_url=settings.apifootball_base_url,
            host=settings.apifootball_host,
            api_key=settings.apifootball_key.get_secret_value(),
            rate_limiter=limiter,
            timeout_sec=settings.http_timeout_sec,
            retry_max_attempts=settings.http_retry_max_attempts,
            retry_backoff_base_sec=settings.http_retry_backoff_base_sec,
            retry_backoff_max_sec=settings.http_retry_backoff_max_sec,
            transport=transport,
        )

    # ---- core ----

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON endpoint; return parsed body. Raises HttpError subclasses."""
        params = dict(params or {})

        def _attempt() -> dict[str, Any]:
            self._rate_limiter.acquire()
            t0 = time.monotonic()
            resp = self._client.get(path, params=params)
            duration_ms = int((time.monotonic() - t0) * 1000)
            # Reconcile against API's own counters before raising on body.
            self._rate_limiter.observe_headers(resp.headers)
            try:
                body = validate_response(resp)
            except Exception:
                _log.warning(
                    "http.error",
                    path=path,
                    params=params,
                    status=resp.status_code,
                    duration_ms=duration_ms,
                    bytes=len(resp.content),
                )
                raise
            _log.info(
                "http.ok",
                path=path,
                params=params,
                status=resp.status_code,
                duration_ms=duration_ms,
                bytes=len(resp.content),
            )
            return body

        return self._run(_attempt)

    # ---- lifecycle ----

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiFootballClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
