"""Every audit backend feeds callers in ascending time order."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, Principal

AUTH = {"Authorization": "Bearer secret"}


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _event(index: int, action: str = "tool.call", **extra) -> AuditEvent:
    stamp = datetime(2026, 11, 24, tzinfo=timezone.utc) + timedelta(minutes=index)
    return AuditEvent(
        event_id=f"e{index}",
        run_id=f"r{index}",
        trace_id=f"t{index}",
        tenant="local",
        principal=Principal(tenant="local", subject="u", kind="human"),
        agent_ref=AgentRef(id="bot", version=f"v{index}", digest="sha256:x"),
        action=action,
        target=f"bot@v{index}",
        status="ok",
        timestamp=stamp,
        **extra,
    )


class _DescQuery:
    """Looks like the file/Postgres/HTTP queries: newest first."""

    def __init__(self, events: list[AuditEvent]) -> None:
        self._events = list(events)

    async def events(self, **_kwargs) -> list[AuditEvent]:
        return list(self._events)


def _client(events: list[AuditEvent]) -> TestClient:
    app = build_console_app(
        _agents(),
        auth_token="secret",
        roles=["admin"],
        audit_query=_DescQuery(events),
    )
    return TestClient(app)


def test_audit_returns_the_newest_events_in_ascending_order():
    newest_first = [_event(5), _event(4), _event(3), _event(2), _event(1), _event(0)]
    with _client(newest_first) as client:
        body = client.get("/api/audit?limit=2", headers=AUTH).json()

    assert [event["target"] for event in body] == ["bot@v4", "bot@v5"]


def test_rag_summary_uses_the_newest_retrieval():
    newest_first = [
        _event(2, action="rag.retrieve", rag_top_k=3, rag_returned=1),
        _event(1, action="rag.retrieve", rag_top_k=5, rag_returned=4),
    ]
    with _client(newest_first) as client:
        body = client.get("/api/rag", headers=AUTH).json()

    assert body["last_top_k"] == 3
    assert body["last_returned"] == 1
