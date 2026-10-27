"""Source-aware JSON logging.

Every log line carries `source` and `run_id`, so any problem in the output
can be traced back to the source and the run that produced it.
"""
import json
import logging
import sys

# Attributes every LogRecord has: anything else was added via `extra=`.
_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        # Add source, run_id and any other extra fields.
        line.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        return json.dumps(line, ensure_ascii=False, default=str)


class SourceLogger(logging.LoggerAdapter):
    """Binds fixed fields (source, run_id) once; call sites add the rest."""

    def process(self, msg, kwargs):
        kwargs["extra"] = {**self.extra, **kwargs.get("extra", {})}
        return msg, kwargs


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)  # logs -> stderr, results -> stdout
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("iris_spv")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False


def get_logger(source: str, run_id: str) -> SourceLogger:
    return SourceLogger(logging.getLogger("iris_spv"), {"source": source, "run_id": run_id})
