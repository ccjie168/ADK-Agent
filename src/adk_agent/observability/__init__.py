"""OpenTelemetry spans for runs, model calls, tool calls, and A2A calls."""

from __future__ import annotations

from .otel import (
    a2a_span,
    configure_otel,
    current_trace_id,
    finish_span,
    model_span,
    record_error,
    record_usage,
    run_span,
    start_tool_span,
    tool_span,
)

__all__ = [
    "a2a_span",
    "configure_otel",
    "current_trace_id",
    "finish_span",
    "model_span",
    "record_error",
    "record_usage",
    "run_span",
    "start_tool_span",
    "tool_span",
]
