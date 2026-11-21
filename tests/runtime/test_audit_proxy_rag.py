"""SLICE-206: retrieval is applied to MCP and A2A runs through the audit proxy."""

from __future__ import annotations

import asyncio

import pytest
from google.genai import types

from adk_agent.audit.hashing import hash_text
from adk_agent.core import Principal
from adk_agent.rag.context import RagUnavailable
from adk_agent.runtime.audit_proxy import AuditedRunner, wrap_runner


class FakePart:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, parts) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self) -> None:
        self.content = FakeContent([FakePart("answer")])

    def is_final_response(self) -> bool:
        return True


class FakeInner:
    def __init__(self) -> None:
        self.messages: list[types.Content] = []

    async def run_async(self, **kwargs):
        self.messages.append(kwargs["new_message"])
        yield FakeEvent()


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


class FakeRag:
    def __init__(self, block: str | None = None, error: Exception | None = None) -> None:
        self.block = block
        self.error = error
        self.seen = None

    async def prefix(self, invocation) -> str:
        self.seen = invocation
        if self.error is not None:
            raise self.error
        return self.block or ""


def _runner(inner: FakeInner, audit: FakeAudit, rag: FakeRag | None) -> AuditedRunner:
    return AuditedRunner(
        inner,
        agent_name="bot",
        principal=Principal(tenant="local", subject="mcp_user", kind="service"),
        audit=audit,
        quota=None,
        quota_policy=None,
        rag=rag,
    )


def _run(runner: AuditedRunner) -> None:
    async def scenario() -> None:
        message = types.Content(role="user", parts=[types.Part(text="hello")])
        async for _ in runner.run_async(user_id="u", session_id="s", new_message=message):
            pass

    asyncio.run(scenario())


def test_retrieval_block_is_prepended_to_new_message():
    inner = FakeInner()
    audit = FakeAudit()
    rag = FakeRag("<retrieved_context>doc</retrieved_context>")
    _run(_runner(inner, audit, rag))

    [message] = inner.messages
    assert message.parts[0].text == "<retrieved_context>doc</retrieved_context>"
    assert message.parts[1].text == "hello"
    [event] = audit.events
    assert event.action == "agent.run"
    assert event.status == "ok"
    assert event.args_hash == hash_text("hello")


def test_retrieval_failure_is_audited_and_skips_the_agent():
    inner = FakeInner()
    audit = FakeAudit()
    rag = FakeRag(error=RagUnavailable("store down"))

    with pytest.raises(RagUnavailable):
        _run(_runner(inner, audit, rag))

    assert inner.messages == []
    [event] = audit.events
    assert event.status == "error"
    assert event.error_code == "RagUnavailable"


def test_no_rag_keeps_the_message_unchanged():
    inner = FakeInner()
    _run(_runner(inner, FakeAudit(), None))
    [message] = inner.messages
    assert [part.text for part in message.parts] == ["hello"]


def test_wrap_runner_wraps_when_only_rag_is_set():
    inner = FakeInner()
    wrapped = wrap_runner(
        inner,
        agent_name="bot",
        principal=Principal(tenant="local", subject="mcp_user", kind="service"),
        audit=FakeAudit(),
        quota=None,
        quota_policy=None,
        rag=object(),
    )
    assert isinstance(wrapped, AuditedRunner)
    assert wrap_runner(inner) is inner
