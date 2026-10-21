import json
import logging
import sys
from datetime import UTC, datetime

# Attribute names that must never be written to logs, even if passed via `extra=`.
SENSITIVE_KEYS = {"password", "token", "access_token", "secret", "authorization", "api_key"}

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Extra fields are included, sensitive ones redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED:
                continue
            payload[key] = "[REDACTED]" if key.lower() in SENSITIVE_KEYS else value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._teamforge = True  # type: ignore[attr-defined]  # marks our handler for replacement
    root = logging.getLogger()
    # Replace only our own handler (idempotent), leaving foreign handlers such as pytest's alone.
    root.handlers = [h for h in root.handlers if not getattr(h, "_teamforge", False)] + [handler]
    root.setLevel(level.upper())
    # Our middleware logs requests; uvicorn's access log would duplicate it.
    logging.getLogger("uvicorn.access").disabled = True
