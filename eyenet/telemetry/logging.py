"""structlog config — emits the PLAN §9.1 JSON shape verbatim.

Every line carries `service`, `instance_id`, `trace_id`, `span_id`, `event`.
`trace_id` / `span_id` autopopulate from the current OTel span, so service
code logs `log.info("profile.updated", actor_id="...")` without manually
threading trace state.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from opentelemetry import trace as otel_trace
from structlog.types import EventDict, WrappedLogger

# Third-party stdlib-`logging` loggers that EYENET pipes through structlog.
# These chat at INFO/DEBUG by default and clutter the operator console with
# validation warnings, sync diagnostics, and ORM noise. They are NEVER signal
# for EYENET — relevant errors are re-emitted via our own structlog calls at
# the collector layer. Dropped to WARNING globally.
_NOISY_STDLIB_LOGGERS: tuple[str, ...] = (
    "nio",
    "nio.responses",
    "nio.client",
    "nio.crypto",
    "nio.store",
    "peewee",
)

# nio's `nio.events.misc` logger emits a multi-line jsonschema dump every
# time a homeserver sends an event that nio's strict schema rejects (very
# common — `predecessor` events missing `event_id` from old room upgrades,
# state events with optional-but-missing fields). The event flow is not
# affected; nio falls back to BadEvent. The console noise is. We drop only
# these specific lines and keep everything else from the same logger.
_NIO_BADEVENT_PREFIX = "Error validating event:"


class _DropNioBadEventValidation(logging.Filter):
    """Drop nio's per-event jsonschema validation dumps. Keep other records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not msg.startswith(_NIO_BADEVENT_PREFIX)


def _add_trace_ids(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    span = otel_trace.get_current_span()
    span_ctx = span.get_span_context()
    if span_ctx.is_valid:
        event_dict["trace_id"] = format(span_ctx.trace_id, "032x")
        event_dict["span_id"] = format(span_ctx.span_id, "016x")
    return event_dict


def _add_static(service: str, instance_id: str) -> Any:
    def processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service)
        event_dict.setdefault("instance_id", instance_id)
        return event_dict

    return processor


def configure_logging(*, service: str, instance_id: str, pretty: bool | None = None) -> None:
    """Configure structlog + stdlib logging process-wide, unified on ONE renderer.

    pretty defaults to sys.stdout.isatty() — human-readable on TTY, single-line
    JSON when piped (prod). Foreign stdlib loggers (uvicorn, nio, sqlalchemy, the
    OTel SDK) are bridged through the SAME renderer via `ProcessorFormatter`, so
    the stream carries exactly ONE log shape. No interleaved multi-line
    tracebacks: `dict_tracebacks` renders every exception as a single structured
    JSON field, which is also what makes each line cleanly shippable to Loki.
    """
    if pretty is None:
        pretty = sys.stdout.isatty()
    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=True)
        if pretty
        else structlog.processors.JSONRenderer()
    )
    # Pre-chain shared by BOTH structlog-native and foreign (stdlib) records, so a
    # uvicorn error and a `log.info(...)` come out with the same service/ts/trace keys.
    shared_processors: list[Any] = [
        _add_static(service, instance_id),
        _add_trace_ids,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
    ]
    structlog.configure(
        processors=[
            *shared_processors,
            # Hand the event to the stdlib ProcessorFormatter instead of rendering
            # here — one handler, one renderer, for structlog and stdlib alike.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.dict_tracebacks,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for name in _NOISY_STDLIB_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Attach the BadEvent content filter on the specific child logger that
    # emits the jsonschema dumps. The filter is idempotent — re-attaching
    # only adds it once because we check via `filters` membership.
    badevent_logger = logging.getLogger("nio.events.misc")
    if not any(isinstance(f, _DropNioBadEventValidation) for f in badevent_logger.filters):
        badevent_logger.addFilter(_DropNioBadEventValidation())


def get_logger() -> structlog.BoundLogger:
    log: structlog.BoundLogger = structlog.get_logger()
    return log


__all__ = ["configure_logging", "get_logger"]
