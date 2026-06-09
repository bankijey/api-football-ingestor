"""Logging: JSON output, run-context binding."""
from __future__ import annotations

import json
import logging

import pytest

from ingestor import logging_setup


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    # Force re-configuration each test so capsys captures fresh handlers.
    logging_setup._CONFIGURED = False
    logging_setup.clear_run_context()
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)


def _last_json_line(captured: str) -> dict:
    lines = [ln for ln in captured.strip().splitlines() if ln.strip().startswith("{")]
    assert lines, f"no JSON log lines found in: {captured!r}"
    return json.loads(lines[-1])


def test_logger_emits_json(capsys: pytest.CaptureFixture[str]) -> None:
    logging_setup.configure_logging("INFO")
    log = logging_setup.get_logger("test")
    log.info("hello", foo="bar")
    out = capsys.readouterr().out
    payload = _last_json_line(out)
    assert payload["event"] == "hello"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"
    assert "timestamp" in payload


def test_bind_run_context_attaches_to_lines(capsys: pytest.CaptureFixture[str]) -> None:
    logging_setup.configure_logging("INFO")
    logging_setup.bind_run_context(run_id="abc-123")
    log = logging_setup.get_logger("test")
    log.info("phase_a.start")
    payload = _last_json_line(capsys.readouterr().out)
    assert payload["run_id"] == "abc-123"


def test_configure_logging_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    logging_setup.configure_logging("INFO")
    logging_setup.configure_logging("DEBUG")  # second call should be a no-op
    log = logging_setup.get_logger("test")
    log.info("once")
    out = capsys.readouterr().out
    assert out.count('"event": "once"') == 1
