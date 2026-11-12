"""SLICE-046: the MCP run wrapper writes audit and enforces quota."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from adk_agent.audit import ListAuditSink
from adk_agent.audit.hashing import hash_text
from adk_agent.core import Principal, QuotaExceeded, QuotaPolicy
from adk_agent.mcp.runtime import AuditedMcpRunner
from adk_agent.runtime.quota import InMemoryQuotaManager

ALICE = Principal(tenant="acme", subject="alice", kind="human")
ANONYMOUS = Principal(tenant="local", subject="mcp_user", kind="service")
POLICY = QuotaPolicy(max_runs=1, window_seconds=60)


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeEvent:
    def __init__(self, text: str | None = None, *, final: bool = False) -> None:
        self.content = FakeContent(text) if text is not None else None
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    app_name = "probe"

    def __init__(self, events: list[Any] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.calls = 0

    async def run_async(self, **kwargs):
        self.calls += 1
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


def _runner(
    inner: FakeRunner,
    *,
    audit: ListAuditSink | None,
    quota: InMemoryQuotaManager | None = None,
    quota_policy: QuotaPolicy | None = None,
    principal: Principal = ALICE,
    input_text: str = "hello",
) -> AuditedMcpRunner:
    return AuditedMcpRunner(
        inner,
        agent_name="probe",
        principal=principal,
        input_text=input_text,
        audit=audit,
        quota=quota,
        quota_policy=quota_policy,
    )


def _consume(wrapper: AuditedMcpRunner) -> list[Any]:
    async def scenario() -> list[Any]:
        return [event async for event in wrapper.run_async(user_id="u", session_id="s")]

    return asyncio.run(scenario())


def test_audits_ok_run():
    sink = ListAuditSink()
    inner = FakeRunner([FakeEvent("partial"), FakeEvent("hi", final=True)])
    wrapper = _runner(inner, audit=sink)

    events = _consume(wrapper)

    assert events == inner.events
    assert inner.calls == 1
    [event] = sink.recent(10)
    assert event.action == "agent.run"
    assert event.status == "ok"
    assert event.tenant == "acme"
    assert event.principal == ALICE
    assert event.target == "probe@dev"
    assert event.agent_ref.id == "probe"
    assert event.args_hash == hash_text("hello")
    assert event.result_hash == hash_text("hi")
    assert event.error_code is None


def test_audits_failed_run():
    sink = ListAuditSink()
    inner = FakeRunner(error=RuntimeError("boom"))
    wrapper = _runner(inner, audit=sink)

    with pytest.raises(RuntimeError):
        _consume(wrapper)

    [event] = sink.recent(10)
    assert event.action == "agent.run"
    assert event.status == "error"
    assert event.error_code == "RuntimeError"
    assert event.result_hash is None


def test_quota_denial_skips_runner():
    sink = ListAuditSink()
    inner = FakeRunner([FakeEvent("hi", final=True)])
    quota = InMemoryQuotaManager()
    wrapper = _runner(inner, audit=sink, quota=quota, quota_policy=POLICY)

    async def scenario() -> None:
        async with quota.reserve("acme", POLICY):
            pass
        with pytest.raises(QuotaExceeded):
            async for _ in wrapper.run_async(user_id="u", session_id="s"):
                pass

    asyncio.run(scenario())
    assert inner.calls == 0
    [event] = sink.recent(10)
    assert event.status == "denied"
    assert event.error_code == "quota_exceeded"


def test_unlisted_tenant_unlimited():
    inner = FakeRunner([FakeEvent("hi", final=True)])
    quota = InMemoryQuotaManager()
    wrapper = _runner(inner, audit=None, quota=quota, quota_policy=None)

    _consume(wrapper)
    _consume(wrapper)

    assert inner.calls == 2


def test_anonymous_uses_local_tenant():
    sink = ListAuditSink()
    wrapper = _runner(FakeRunner([FakeEvent("hi", final=True)]), audit=sink, principal=ANONYMOUS)

    _consume(wrapper)

    [event] = sink.recent(10)
    assert event.tenant == "local"
    assert event.principal.subject == "mcp_user"


def test_events_pass_through():
    first = FakeEvent("one")
    second = FakeEvent("two", final=True)
    inner = FakeRunner([first, second])

    events = _consume(_runner(inner, audit=None))

    assert events[0] is first
    assert events[1] is second


def test_no_sinks_is_passthrough():
    inner = FakeRunner([FakeEvent("hi", final=True)])

    events = _consume(_runner(inner, audit=None))

    assert len(events) == 1
    assert inner.calls == 1
