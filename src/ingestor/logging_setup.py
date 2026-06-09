"""Structured (JSON) logging via structlog.

Writes one JSON object per line to stdout — perfect for docker / k8s log
collectors. No stdlib `logging` coupling: the logger factory resolves
`sys.stdout` on every write, so test capture (capsys) and stream redirection
work as expected.

Usage:
    from ingestor.logging_setup import configure_logging, get_logger, bind_run_context
    configure_logging("INFO")
    bind_run_context(run_id="abc-123")
    log = get_logger(__name__)
    log.info("phase_a.start", league_count=42)
"""
from __future__ import annotations

from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

_CONFIGURED = False
_LEVEL_NUM = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}


class _StdoutLogger:
    """Tiny logger that prints to the *current* sys.stdout on every call.

    Avoids the StreamHandler/PrintLogger pattern of capturing sys.stdout at
    construction, which breaks under pytest's capsys.
    """

    def msg(self, message: str) -> None:
        print(message)

    log = debug = info = warning = error = critical = msg


def _factory(*_: Any, **__: Any) -> _StdoutLogger:
    return _StdoutLogger()


def configure_logging(level: str = "INFO") -> None:
    """Idempotent: subsequent calls are no-ops."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    min_level_num = _LEVEL_NUM.get(level.lower(), _LEVEL_NUM["info"])

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level_num),
        logger_factory=_factory,
        cache_logger_on_first_use=False,
    )
    _CONFIGURED = True


def get_logger(name: str | None = None) -> Any:
    """Return a structlog BoundLogger. Typed as Any because structlog's
    filtering_bound_logger doesn't statically expose info/warning/etc."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()


def bind_run_context(**kwargs: Any) -> None:
    """Bind keys (run_id, etc.) to the ambient logging context."""
    bind_contextvars(**kwargs)


def clear_run_context() -> None:
    clear_contextvars()
