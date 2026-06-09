"""ApiFootballClient: end-to-end via httpx.MockTransport.

Covers: header injection, success path, retry on 503 then 200, 401 not retried,
200-with-errors not retried, rate limiter touched per call.
"""
from __future__ import annotations

import json

import httpx
import pytest

from ingestor.http.client import ApiFootballClient
from ingestor.http.errors import ApiResponseError, NonRetryableHttpError
from ingestor.http.rate_limiter import RateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, d: float) -> None:
        self.t += d


def _limiter() -> RateLimiter:
    clk = _FakeClock()
    return RateLimiter(
        per_interval=10_000,
        interval_sec=60.0,
        daily_quota=10_000,
        now=clk.now,
        sleep=clk.sleep,
    )


def _client(transport: httpx.MockTransport, *, max_attempts: int = 3) -> ApiFootballClient:
    return ApiFootballClient(
        base_url="https://v3.football.api-sports.io",
        host="v3.football.api-sports.io",
        api_key="test-key",
        rate_limiter=_limiter(),
        timeout_sec=5.0,
        retry_max_attempts=max_attempts,
        retry_backoff_base_sec=0.001,
        retry_backoff_max_sec=0.002,
        transport=transport,
    )


def test_success_path_returns_body_and_sends_headers() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": [{"id": 1}], "errors": []})

    with _client(httpx.MockTransport(handler)) as c:
        body = c.get("/leagues", params={"id": 39})
    assert body["response"] == [{"id": 1}]
    headers = captured["headers"]
    assert headers["x-rapidapi-key"] == "test-key"  # type: ignore[index]
    assert headers["x-rapidapi-host"] == "v3.football.api-sports.io"  # type: ignore[index]
    assert "id=39" in captured["url"]  # type: ignore[operator]


def test_retries_on_503_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={})
        return httpx.Response(200, json={"response": [], "errors": []})

    with _client(httpx.MockTransport(handler), max_attempts=5) as c:
        body = c.get("/leagues")
    assert calls["n"] == 3
    assert body == {"response": [], "errors": []}


def test_does_not_retry_on_401() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={})

    with _client(httpx.MockTransport(handler), max_attempts=5) as c, \
         pytest.raises(NonRetryableHttpError):
        c.get("/leagues")
    assert calls["n"] == 1


def test_does_not_retry_on_200_with_errors() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            content=json.dumps({"response": [], "errors": {"token": "bad"}}).encode(),
            headers={"content-type": "application/json"},
        )

    with _client(httpx.MockTransport(handler), max_attempts=5) as c, \
         pytest.raises(ApiResponseError):
        c.get("/leagues")
    assert calls["n"] == 1


def test_observes_rate_limit_headers() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": [], "errors": []},
            headers={
                "x-ratelimit-requests-limit": "1000",
                "x-ratelimit-requests-remaining": "100",
            },
        )

    limiter = _limiter()
    c = ApiFootballClient(
        base_url="https://v3.football.api-sports.io",
        host="v3.football.api-sports.io",
        api_key="k",
        rate_limiter=limiter,
        timeout_sec=5.0,
        retry_max_attempts=1,
        retry_backoff_base_sec=0.001,
        retry_backoff_max_sec=0.002,
        transport=httpx.MockTransport(handler),
    )
    with c:
        c.get("/leagues")
    snap = limiter.snapshot()
    # API says 900 used of 1000. We scaled into our 10k local quota → 9000.
    assert snap["long_used"] >= 9000
