"""W3C trace context parsing and inbound trace id resolution."""

from __future__ import annotations

import re
import uuid

__all__ = ["resolve_trace_id", "trace_id_from_traceparent"]

_TRACEPARENT = re.compile(r"([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})")
_X_TRACE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def trace_id_from_traceparent(value: str | None) -> str | None:
    """Return the W3C trace id from a valid ``traceparent`` header, else None."""
    if value is None:
        return None
    match = _TRACEPARENT.fullmatch(value)
    if match is None:
        return None
    version, trace_id, parent_id, _flags = match.groups()
    if version == "ff":
        return None
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        return None
    return trace_id


def resolve_trace_id(x_trace_id: str | None, traceparent: str | None) -> str:
    """Resolve the inbound trace id: X-Trace-Id wins, then traceparent, then a new id."""
    if x_trace_id is not None and _X_TRACE_ID.fullmatch(x_trace_id):
        return x_trace_id
    traced = trace_id_from_traceparent(traceparent)
    if traced is not None:
        return traced
    return uuid.uuid4().hex
