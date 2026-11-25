import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import Settings

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_context.get()
            or getattr(record, "request_id", None),
            "message": record.getMessage(),
        }
        if record.exc_info is not None and record.exc_info[0] is not None:
            payload["exception_type"] = record.exc_info[0].__name__
            payload["stack"] = [
                f"{frame.filename}:{frame.lineno} in {frame.name}"
                for frame in traceback.extract_tb(record.exc_info[2])
            ]
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat()
        message = record.getMessage().replace("\r", "\\r").replace("\n", "\\n")
        request_id = request_id_context.get() or getattr(record, "request_id", None)
        return (
            f"{timestamp} {record.levelname} {record.name} "
            f"request_id={request_id} {message}"
        )


def configure_logging(settings: Settings) -> None:
    logger = logging.getLogger("taskhub")
    for handler in list(logger.handlers):
        if handler.name == "taskhub.console":
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.name = "taskhub.console"
    handler.setFormatter(
        JsonFormatter() if settings.log_format == "json" else TextFormatter()
    )
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    server_logger = logging.getLogger("uvicorn.error")
    server_logger.handlers = [handler]
    server_logger.propagate = False
    server_logger.setLevel(settings.log_level)
