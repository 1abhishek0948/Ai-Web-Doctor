"""Structured logging for AI Web Doctor.

A single JSON formatter keeps every log line machine-parseable so it can be
shipped to log aggregators. ``log_event`` emits structured application events
(scan.created, scan.failed, ai.error, ...) with key/value context.

Security note: never pass API keys or full request URLs that embed credentials
into log calls. The Gemini client sends its API key in a header (not in the URL)
so it can never appear in a logged URL.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

_EVENT_LOGGER = logging.getLogger("aiwebdoctor.events")


class JsonFormatter(logging.Formatter):
    """Format a log record as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update({k: v for k, v in extra.items() if k not in payload})
        return json.dumps(payload, default=str)


def log_event(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Emit a structured application event.

    Example::

        log_event("scan.completed", scan_id=3, status="completed", issues=5)
    """
    _EVENT_LOGGER.log(level, event, extra={"extra_fields": fields})
