from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings

request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

_SENSITIVE_KEY = re.compile(
    r"(?:token|authorization|cookie|password|secret|api[_-]?key|encryption|ciphertext|"
    r"session|csrf|smtp|database[_-]?url)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(authorization|cookie|password|secret|api[_-]?key|token|csrf|smtp_password)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@", re.I)


def redact_sensitive(value: Any, *, max_length: int | None = None) -> Any:
    limit = max_length or get_settings().log_max_field_length
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if _SENSITIVE_KEY.search(str(key))
            else redact_sensitive(item, max_length=limit)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive(item, max_length=limit) for item in value]
    if isinstance(value, str):
        cleaned = _SENSITIVE_TEXT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
        cleaned = _URL_CREDENTIALS.sub(lambda match: f"{match.group('scheme')}[REDACTED]@", cleaned)
        return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}…"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return redact_sensitive(str(value), max_length=limit)


class OperationalFormatter(logging.Formatter):
    _standard = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.name),
            "message": message,
            "request_id": getattr(record, "request_id", None) or request_id_context.get(),
            "release_id": self.settings.app_release_id,
        }
        for key, value in record.__dict__.items():
            if key not in self._standard and key not in payload and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Error"
            payload["stack"] = self.formatException(record.exc_info)
        if self.settings.log_include_source:
            payload["source"] = {"file": record.pathname, "line": record.lineno}
        safe = redact_sensitive(payload, max_length=self.settings.log_max_field_length)
        if self.settings.log_format == "json":
            return json.dumps(safe, ensure_ascii=False, separators=(",", ":"), default=str)
        prefix = f"{safe['timestamp']} {safe['level']} {safe['logger']}"
        request_id = safe.get("request_id")
        return f"{prefix} request_id={request_id or '-'} {safe['message']}"


def configure_logging(settings: Settings | None = None) -> None:
    active = settings or get_settings()
    root = logging.getLogger()
    root.setLevel(active.log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(OperationalFormatter(active))
    root.handlers[:] = [handler]
