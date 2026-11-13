"""Correlated diagnostics — structured logs and request/task context.

Every layer may import this module: it carries no project dependencies
and no configuration knowledge. `bind_context` stamps bounded
correlation fields (task, operation, correlation, request) onto log
records so one operation can be traced across the API, Celery workers
and satellite services. `JsonFormatter` emits a fixed key set with
sensitive values redacted and long values truncated — bounded labels
by construction rather than by discipline.
"""

import contextlib
import contextvars
import json
import logging
import re
import uuid
from datetime import UTC, datetime

# Bounded context fields — the complete set of log labels. Anything a
# caller passes outside this allowlist is dropped, keeping label
# cardinality fixed.
_CONTEXT_KEYS = ("request_id", "task_id", "task_name", "operation_id", "correlation_id")
_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "taryx_context", default=None
)

_SENSITIVE = re.compile(r"token|password|secret|authorization|api[-_]?key", re.I)
_REDACTED = "<redacted>"
_MAX_VALUE = 300


def current_context() -> dict:
    return dict(_context.get() or {})


@contextlib.contextmanager
def bind_context(**fields):
    """Bind bounded correlation fields for the duration of a block —
    e.g. a Celery task body or a service call handling one operation."""
    merged = {**(_context.get() or {}), **{k: v for k, v in fields.items() if k in _CONTEXT_KEYS}}
    token = _context.set(merged)
    try:
        yield merged
    finally:
        _context.reset(token)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class ContextFilter(logging.Filter):
    """Inject bound context fields onto every record that lacks them."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_context().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def _clean(key: str, value):
    if _SENSITIVE.search(key):
        return _REDACTED
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    text = str(value)
    return text if len(text) <= _MAX_VALUE else text[:_MAX_VALUE] + "…"


class JsonFormatter(logging.Formatter):
    """One JSON object per record with a fixed schema. `extra` keys are
    included under `fields` after redaction/truncation."""

    _BUILTIN = logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()

    def format(self, record: logging.LogRecord) -> str:
        event: dict = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value:
                event[key] = str(value)
        fields = {
            k: _clean(k, v)
            for k, v in record.__dict__.items()
            if k not in self._BUILTIN and k not in _CONTEXT_KEYS
        }
        if fields:
            event["fields"] = fields
        if record.exc_info and record.exc_info[0] is not None:
            event["exc"] = self.formatException(record.exc_info)
        return json.dumps(event, separators=(",", ":"))


def install_celery_signals() -> None:
    """Bind task identity into the log context for each task run so
    worker logs join the API/queue story by task_id."""
    from celery.signals import task_postrun, task_prerun

    @task_prerun.connect(weak=False)
    def _bind(sender=None, task_id=None, task=None, **kwargs):
        _context.set(
            {
                **(_context.get() or {}),
                "task_id": task_id,
                "task_name": getattr(task, "name", None) or getattr(sender, "name", None),
            }
        )

    @task_postrun.connect(weak=False)
    def _unbind(**kwargs):
        _context.set(None)
