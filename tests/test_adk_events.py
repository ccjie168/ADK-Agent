"""SLICE-316: the platform run-event boundary (ADR-0046 2b)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "adk_agent"


class _Part(SimpleNamespace):
    pass


def _event(*parts, final=False, author="agent"):
    content = SimpleNamespace(parts=list(parts))
    return SimpleNamespace(
        author=author,
        content=content,
        is_final_response=lambda: final,
    )


def _text(value, thought=False):
    return _Part(text=value, thought=thought, function_call=None, function_response=None)


def _call(name):
    return _Part(
        text=None, thought=False, function_call=SimpleNamespace(name=name), function_response=None
    )


def _result(name):
    return _Part(
        text=None, thought=False, function_call=None, function_response=SimpleNamespace(name=name)
    )


def test_run_event_conversion_extracts_parts():
    from adk_agent.adapters.adk.events import to_run_event

    event = _event(_text("hello "), _call("lookup"), _result("lookup"), _text("world"), final=True)
    run_event = to_run_event(event)

    assert run_event.author == "agent"
    assert run_event.final is True
    assert [(part.kind, part.text, part.name) for part in run_event.parts] == [
        ("text", "hello ", None),
        ("tool_call", None, "lookup"),
        ("tool_result", None, "lookup"),
        ("text", "world", None),
    ]
    assert run_event.text == "hello world"
    assert to_run_event(run_event) is run_event


def test_run_event_drops_thought_parts():
    from adk_agent.adapters.adk.events import to_run_event

    run_event = to_run_event(
        _event(_text("thinking...", thought=True), _text("answer"), final=True)
    )

    assert run_event.text == "answer"
    assert [part.kind for part in run_event.parts] == ["text"]


def test_agent_runtime_consumes_platform_events():
    from adk_agent.core import Invocation, Principal, RunEvent, RunPart
    from adk_agent.runtime import AgentRuntime, dev_agent_ref

    class PlatformRunner:
        async def run_async(self, **kwargs):
            yield RunEvent(author="agent", parts=(RunPart(kind="text", text="hi"),))
            yield RunEvent(
                author="agent",
                final=True,
                parts=(RunPart(kind="text", text=" final"),),
            )

    seen = []

    async def on_progress(event):
        seen.append((event.kind, event.text))

    runtime = AgentRuntime(PlatformRunner())
    invocation = Invocation(
        run_id="run-1",
        trace_id="trace-1",
        principal=Principal(tenant="local", subject="tester", kind="human"),
        agent_ref=dev_agent_ref("probe"),
        input="hi",
    )
    result = asyncio.run(
        runtime.run(invocation, user_id="u", session_id="s", on_progress=on_progress)
    )

    assert result.text == "final"
    assert ("model.text", "hi") in seen
    assert ("model.text", " final") in seen


def test_audit_proxy_extracts_final_text_from_run_events():
    from adk_agent.audit import ListAuditSink
    from adk_agent.audit.hashing import hash_text
    from adk_agent.core import Principal
    from adk_agent.runtime.audit_proxy import AuditedRunner

    class Inner:
        async def run_async(self, **kwargs):
            yield _event(_text("ignored"), final=False)
            yield _event(_text("done"), final=True)

    sink = ListAuditSink()
    proxy = AuditedRunner(
        Inner(),
        agent_name="probe",
        principal=Principal(tenant="local", subject="tester", kind="human"),
        audit=sink,
        quota=None,
        quota_policy=None,
    )

    async def drain():
        return [event async for event in proxy.run_async(user_id="u")]

    events = asyncio.run(drain())
    assert len(events) == 2
    [record] = sink.recent(10)
    assert record.status == "ok"
    assert record.result_hash == hash_text("done")


_ADK_EVENT_ACCESS = re.compile(r"is_final_response|content\.parts|function_call(?!_|\w)")


def test_only_the_adapter_reads_adk_event_fields():
    offenders = []
    for path in SOURCE.rglob("*.py"):
        rel = path.relative_to(SOURCE).as_posix()
        if rel.startswith("adapters/"):
            continue
        for match in _ADK_EVENT_ACCESS.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}: {match.group(0)}")

    assert offenders == []
