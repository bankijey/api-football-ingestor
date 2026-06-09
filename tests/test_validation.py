"""validate_response: status-code routing + errors-field detection."""
from __future__ import annotations

import json

import httpx
import pytest

from ingestor.http.errors import (
    ApiResponseError,
    NonRetryableHttpError,
    RetryableHttpError,
)
from ingestor.http.validation import validate_response


def _resp(status: int, body: object) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=json.dumps(body).encode() if not isinstance(body, bytes) else body,
        headers={"content-type": "application/json"},
    )


def test_ok_returns_body() -> None:
    body = {"response": [{"id": 1}], "errors": []}
    assert validate_response(_resp(200, body)) == body


def test_ok_with_empty_errors_dict() -> None:
    body = {"response": [], "errors": {}}
    assert validate_response(_resp(200, body)) == body


def test_200_with_errors_raises_api_response_error() -> None:
    body = {"response": [], "errors": {"token": "invalid"}}
    with pytest.raises(ApiResponseError) as exc:
        validate_response(_resp(200, body))
    assert exc.value.errors == {"token": "invalid"}


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_retryable(status: int) -> None:
    with pytest.raises(RetryableHttpError):
        validate_response(_resp(status, {}))


@pytest.mark.parametrize("status", [408, 425, 429])
def test_specific_4xx_retryable(status: int) -> None:
    with pytest.raises(RetryableHttpError):
        validate_response(_resp(status, {}))


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_other_4xx_not_retryable(status: int) -> None:
    with pytest.raises(NonRetryableHttpError):
        validate_response(_resp(status, {}))


def test_invalid_json_non_retryable() -> None:
    resp = httpx.Response(status_code=200, content=b"<html>oops</html>")
    with pytest.raises(NonRetryableHttpError):
        validate_response(resp)


def test_json_not_dict_non_retryable() -> None:
    with pytest.raises(NonRetryableHttpError):
        validate_response(_resp(200, [1, 2, 3]))
