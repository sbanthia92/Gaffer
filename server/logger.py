"""
Structured JSON logger for The Gaffer API.

Writes one JSON object per line to stdout. The CloudWatch agent
tails /var/log/gaffer/app.log (which systemd writes to via
StandardOutput=file in the service unit).

Usage:
    from server.logger import log
    log.info("ask.complete", question="...", latency_ms=320, tools=["search_player"])
"""

import logging
import sys
from datetime import UTC, datetime


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        # Merge any extra fields passed via log.info("event", key=value)
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "taskName",
            }:
                payload[key] = value

        return json.dumps(payload, default=str)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("gaffer")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)

    logger.propagate = False
    return logger


class _StructuredLogger:
    """Thin wrapper that accepts keyword extras alongside the message."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, event: str, **kwargs) -> None:
        self._logger.log(level, event, extra=kwargs)

    def info(self, event: str, **kwargs) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs) -> None:
        self._log(logging.ERROR, event, **kwargs)


log = _StructuredLogger(_build_logger())
