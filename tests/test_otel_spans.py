"""SLICE-110: runs export OTel spans without leaking content."""

from __future__ import annotations

import uuid

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.observability import (
    a2a_span,
    configure_otel,
    current_trace_id,
    model_span,
    record_usage,
    run_span,
    tool_span,
)

PROBE = "hunter2-prod-secret"


def _invocation(*, tenant: str = "acme") -> Invocation:
    return Invocation(
        run_id=uuid.uuid4().hex,
        trace_id=uuid.uuid4().hex,
        principal=Principal(tenant=tenant, subject="alice", kind="human", roles=["admin"]),
        agent_ref=AgentRef(id="bot_a", version="1.0.0", digest="sha256:" + "a" * 64),
        input=f'password = "{PROBE}"',
    )


class RecordingExporter:
    def __init__(self) -> None:
        self.inner = InMemorySpanExporter()
        self.broken = False

    def export(self, spans):
        if self.broken:
            raise RuntimeError("boom")
        return self.inner.export(spans)

    def shutdown(self) -> None:
        self.inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)

    def get_finished_spans(self):
        return self.inner.get_finished_spans()

    def clear(self) -> None:
        self.inner.clear()


@pytest.fixture(scope="module")
def exporter() -> RecordingExporter:
    recording = RecordingExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(recording))
    trace.set_tracer_provider(provider)
    return recording


@pytest.fixture()
def spans(exporter: RecordingExporter) -> RecordingExporter:
    exporter.broken = False
    exporter.clear()
    return exporter


def test_span_hierarchy(spans: InMemorySpanExporter) -> None:
    invocation = _invocation()
    with run_span(invocation, invocation.agent_ref):
        with model_span(invocation, provider="claude", model="deepseek-v4-pro"):
            pass
        with tool_span(invocation, tool_id="crm.read"):
            pass
        with a2a_span(invocation, target="peer.example/bot_b"):
            pass

    finished = {span.name: span for span in spans.get_finished_spans()}
    assert set(finished) == {"agent.run", "model.call", "tool.call", "a2a.call"}
    root = finished["agent.run"]
    for name in ("model.call", "tool.call", "a2a.call"):
        child = finished[name]
        assert child.parent is not None
        assert child.parent.span_id == root.context.span_id
        assert child.context.trace_id == root.context.trace_id


def test_attributes_and_usage(spans: InMemorySpanExporter) -> None:
    invocation = _invocation()
    with (
        run_span(invocation, invocation.agent_ref),
        model_span(invocation, provider="claude", model="deepseek-v4-pro") as model,
    ):
        record_usage(model, input_tokens=12, output_tokens=34, cost_usd=0.0012)

    finished = {span.name: span for span in spans.get_finished_spans()}
    root = finished["agent.run"]
    attributes = dict(root.attributes)
    assert attributes["adk.tenant"] == "acme"
    assert attributes["adk.run_id"] == invocation.run_id
    assert attributes["adk.agent.id"] == "bot_a"
    assert attributes["adk.agent.version"] == "1.0.0"
    assert attributes["adk.trace_id"] == invocation.trace_id

    model_attributes = dict(finished["model.call"].attributes)
    assert model_attributes["gen_ai.operation.name"] == "chat"
    assert model_attributes["gen_ai.request.model"] == "deepseek-v4-pro"
    assert model_attributes["gen_ai.usage.input_tokens"] == 12
    assert model_attributes["gen_ai.usage.output_tokens"] == 34
    assert model_attributes["adk.cost_usd"] == pytest.approx(0.0012)


def test_no_content_by_default(spans: InMemorySpanExporter) -> None:
    invocation = _invocation()
    with (
        run_span(invocation, invocation.agent_ref),
        tool_span(invocation, tool_id="crm.read", args_hash="abc123"),
    ):
        pass

    finished = spans.get_finished_spans()
    for span in finished:
        dumped = str(dict(span.attributes))
        assert PROBE not in dumped
        assert "password" not in dumped
    tool = next(span for span in finished if span.name == "tool.call")
    assert dict(tool.attributes)["adk.args_hash"] == "abc123"


def test_disabled_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert configure_otel(endpoint=None) is False


def test_invalid_endpoint_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert configure_otel(endpoint="not-a-url") is False


def test_tenants_do_not_mix(spans: RecordingExporter) -> None:
    first = _invocation(tenant="acme")
    second = _invocation(tenant="beta")
    with run_span(first, first.agent_ref):
        pass
    with run_span(second, second.agent_ref):
        pass
    tenants = {
        dict(span.attributes)["adk.tenant"]
        for span in spans.get_finished_spans()
        if span.name == "agent.run"
    }
    assert tenants == {"acme", "beta"}


def test_exporter_failure_is_soft(spans: RecordingExporter) -> None:
    spans.broken = True
    invocation = _invocation()
    with run_span(invocation, invocation.agent_ref):
        pass


def test_trace_id_matches_audit(spans: InMemorySpanExporter) -> None:
    invocation = _invocation()
    with run_span(invocation, invocation.agent_ref) as run:
        assert current_trace_id() == invocation.trace_id
        assert format(run.get_span_context().trace_id, "032x") == invocation.trace_id
