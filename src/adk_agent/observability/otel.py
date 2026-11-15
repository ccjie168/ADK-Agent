"""Thin OTel boundary. Missing packages or exporters never break a run."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

from ..core import AgentRef, Invocation

logger = logging.getLogger(__name__)

_TRACER_NAME = "adk_agent"
_configured = False
_warned = False

_BASE_KEYS = (
    "adk.tenant",
    "adk.run_id",
    "adk.agent.id",
    "adk.agent.version",
    "adk.principal.subject",
)


def configure_otel(
    *,
    endpoint: str | None = None,
    service_name: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> bool:
    """Install the global tracer provider once. No endpoint means no-op."""
    global _configured
    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return False
    if _configured:
        return True
    if urlsplit(endpoint).scheme not in ("http", "https"):
        _warn("invalid OTLP endpoint; tracing stays disabled")
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        _warn("OTLP endpoint set but the otel extra is not installed")
        return False

    try:
        resource = Resource.create(
            {"service.name": service_name or os.environ.get("OTEL_SERVICE_NAME", "adk-agent")}
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=dict(headers) if headers is not None else None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
    except Exception as exc:  # noqa: BLE001  # exporter setup must not break startup
        _warn(f"OTel exporter setup failed: {type(exc).__name__}")
        return False
    _configured = True
    return True


def _warn(message: str) -> None:
    global _warned
    if not _warned:
        logger.warning(message)
        _warned = True


def _tracer() -> Any:
    from opentelemetry import trace

    return trace.get_tracer(_TRACER_NAME)


def _base_attributes(invocation: Invocation, agent_ref: AgentRef) -> dict[str, Any]:
    return {
        "adk.tenant": invocation.principal.tenant,
        "adk.run_id": invocation.run_id,
        "adk.agent.id": agent_ref.id,
        "adk.agent.version": agent_ref.version,
        "adk.principal.subject": invocation.principal.subject,
    }


def _parent_context(trace_id: str) -> Any:
    from opentelemetry.trace import (
        NonRecordingSpan,
        SpanContext,
        TraceFlags,
        set_span_in_context,
    )

    if len(trace_id) != 32:
        return None
    try:
        value = int(trace_id, 16)
    except ValueError:
        return None
    if value == 0:
        return None
    span_id = int.from_bytes(os.urandom(8), "big") or 1
    context = SpanContext(
        trace_id=value,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    return set_span_in_context(NonRecordingSpan(context))


def _trace_id_hex(span: Any) -> str | None:
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


@contextmanager
def run_span(invocation: Invocation, agent_ref: AgentRef) -> Iterator[Any]:
    tracer = _tracer()
    with tracer.start_as_current_span(
        "agent.run",
        context=_parent_context(invocation.trace_id),
        attributes=_base_attributes(invocation, agent_ref),
    ) as span:
        trace_id = _trace_id_hex(span) or invocation.trace_id
        span.set_attribute("adk.trace_id", trace_id)
        yield span


def start_tool_span(invocation: Invocation, *, tool_id: str, args_hash: str | None = None) -> Any:
    """Start a tool span that is not bound to the caller's context.

    ADK calls the before and after callbacks in separate steps. Keeping the
    span current across them would leak context; the parent is captured here.
    """
    attributes: dict[str, Any] = {
        **_base_attributes(invocation, invocation.agent_ref),
        "adk.tool.id": tool_id,
    }
    if args_hash is not None:
        attributes["adk.args_hash"] = args_hash
    return _tracer().start_span("tool.call", attributes=attributes)


def finish_span(span: Any, *, status: str, error_code: str | None = None) -> None:
    span.set_attribute("adk.status", status)
    if error_code is not None:
        span.set_attribute("adk.error_code", error_code)
    span.end()


@contextmanager
def model_span(invocation: Invocation, *, provider: str, model: str) -> Iterator[Any]:
    with _tracer().start_as_current_span(
        "model.call",
        attributes={
            **_base_attributes(invocation, invocation.agent_ref),
            "gen_ai.operation.name": "chat",
            "gen_ai.system": provider,
            "gen_ai.request.model": model,
        },
    ) as span:
        yield span


@contextmanager
def tool_span(
    invocation: Invocation, *, tool_id: str, args_hash: str | None = None
) -> Iterator[Any]:
    attributes: dict[str, Any] = {
        **_base_attributes(invocation, invocation.agent_ref),
        "adk.tool.id": tool_id,
    }
    if args_hash is not None:
        attributes["adk.args_hash"] = args_hash
    with _tracer().start_as_current_span("tool.call", attributes=attributes) as span:
        yield span


@contextmanager
def a2a_span(invocation: Invocation, *, target: str) -> Iterator[Any]:
    with _tracer().start_as_current_span(
        "a2a.call",
        attributes={
            **_base_attributes(invocation, invocation.agent_ref),
            "adk.a2a.target": target,
        },
    ) as span:
        yield span


def record_usage(
    span: Any,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    if cost_usd is not None:
        span.set_attribute("adk.cost_usd", cost_usd)


def record_error(span: Any, error_code: str) -> None:
    span.set_attribute("adk.error_code", error_code)
    span.set_attribute("adk.status", "error")


def current_trace_id() -> str | None:
    from opentelemetry import trace

    return _trace_id_hex(trace.get_current_span())
