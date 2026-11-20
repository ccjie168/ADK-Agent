"""SLICE-188: model audit carries the alias and the fallback count (ADR-0033 slice 4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentRef,
    AuditEvent,
    Invocation,
    Message,
    ModelAlias,
    ModelCandidate,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
)
from adk_agent.models.gateway import ModelUnavailable, PolicyModelGateway


def _policy() -> ModelPolicy:
    return ModelPolicy(
        provider_allowlist=["fake"],
        model_aliases=[
            ModelAlias(
                alias="primary",
                candidates=[
                    ModelCandidate(provider="fake", model="m-primary"),
                    ModelCandidate(provider="fake", model="m-backup"),
                ],
            )
        ],
    )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _request() -> ModelRequest:
    return ModelRequest(provider="fake", model="m1", messages=[Message(role="user", content="hi")])


class FakeProvider:
    name = "fake"
    egress = "third_party"

    def __init__(self, *, fail_models: tuple[str, ...] = ()) -> None:
        self.fail_models = fail_models

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if request.model in self.fail_models:
            raise ModelUnavailable(f"{request.model} down")
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            egress="third_party",
        )


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _gateway(provider: FakeProvider, audit: RecordingAudit) -> PolicyModelGateway:
    return PolicyModelGateway({provider.name: provider}, audit=audit)


def test_direct_call_audits_defaults():
    audit = RecordingAudit()
    gateway = _gateway(FakeProvider(), audit)
    asyncio.run(gateway.complete(_invocation(), _request(), _policy()))
    assert audit.events[-1].model_alias is None
    assert audit.events[-1].fallback_count == 0


def test_alias_call_audits_alias():
    audit = RecordingAudit()
    gateway = _gateway(FakeProvider(), audit)
    asyncio.run(gateway.complete(_invocation(), _request(), _policy(), alias="primary"))
    event = audit.events[-1]
    assert event.model_alias == "primary"
    assert event.fallback_count == 0
    assert event.target == "fake:m-primary"


def test_fallback_audits_count():
    audit = RecordingAudit()
    gateway = _gateway(FakeProvider(fail_models=("m-primary",)), audit)
    asyncio.run(gateway.complete(_invocation(), _request(), _policy(), alias="primary"))
    assert [(e.model_alias, e.fallback_count, e.target) for e in audit.events] == [
        ("primary", 0, "fake:m-primary"),
        ("primary", 1, "fake:m-backup"),
    ]


def test_audit_rejects_negative_fallback_count():
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="e1",
            run_id="r1",
            trace_id="tr1",
            tenant="t1",
            principal=Principal(tenant="t1", subject="alice", kind="human"),
            agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
            action="model.call",
            target="fake:m1",
            status="ok",
            fallback_count=-1,
            timestamp=datetime.now(timezone.utc),
        )
