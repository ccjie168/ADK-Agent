"""SLICE-043: OIDC principal injection for MCP HTTP."""

from __future__ import annotations

import asyncio
import weakref
from types import SimpleNamespace

from adk_agent.core import Principal
from adk_agent.mcp.server import (
    _principal_from_ctx,
    _PrincipalRunner,
    _PrincipalSessionService,
    _reap_as,
    _state_for,
)


def _principal(subject: str = "alice") -> Principal:
    return Principal(tenant="t1", subject=subject, kind="human", roles=["admin"])


class FakeConnection:
    pass


class FakeSession:
    def __init__(self, session_id: str) -> None:
        self.id = session_id


class FakeSessionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def create_session(self, *, app_name, user_id, state=None, session_id=None):
        self.calls.append(
            (
                "create_session",
                {
                    "app_name": app_name,
                    "user_id": user_id,
                    "state": state,
                    "session_id": session_id,
                },
            )
        )
        return FakeSession(session_id or "s1")

    async def get_session(self, *, app_name, user_id, session_id, config=None):
        self.calls.append(
            (
                "get_session",
                {"app_name": app_name, "user_id": user_id, "session_id": session_id},
            )
        )
        return FakeSession(session_id)

    async def delete_session(self, *, app_name, user_id, session_id):
        self.calls.append(
            (
                "delete_session",
                {"app_name": app_name, "user_id": user_id, "session_id": session_id},
            )
        )

    async def list_sessions(self, *, app_name, user_id):
        self.calls.append(("list_sessions", {"app_name": app_name, "user_id": user_id}))
        return SimpleNamespace(sessions=[])


class FakeRunner:
    app_name = "probe"

    def __init__(self) -> None:
        self.session_service = FakeSessionService()
        self.seen: list[dict] = []

    def run_async(self, *, user_id, session_id, new_message):
        self.seen.append({"user_id": user_id, "session_id": session_id, "new_message": new_message})

        async def events():
            yield "event"

        return events()


class FakeCtx:
    def __init__(self, principal: Principal | None = None) -> None:
        request = SimpleNamespace(state=SimpleNamespace(principal=principal))
        self.request_context = SimpleNamespace(request=request)


async def _drain(events):
    return [event async for event in events]


def test_principal_from_ctx():
    principal = _principal()

    assert _principal_from_ctx(FakeCtx(principal)) is principal


def test_principal_from_ctx_without_request():
    assert _principal_from_ctx(object()) is None
    assert _principal_from_ctx(FakeCtx(None)) is None


def test_runner_rewrites_user_id():
    inner = FakeRunner()
    runner = _PrincipalRunner(inner, _principal("alice"))

    events = runner.run_async(user_id="mcp_user", session_id="s1", new_message="hi")

    assert asyncio.run(_drain(events)) == ["event"]
    assert inner.seen == [{"user_id": "alice", "session_id": "s1", "new_message": "hi"}]


def test_session_service_rewrites_user_id():
    inner = FakeSessionService()
    service = _PrincipalSessionService(inner, _principal("alice"))

    async def scenario():
        await service.create_session(app_name="probe", user_id="mcp_user")
        await service.get_session(app_name="probe", user_id="mcp_user", session_id="s1")
        await service.delete_session(app_name="probe", user_id="mcp_user", session_id="s1")
        await service.list_sessions(app_name="probe", user_id="mcp_user")

    asyncio.run(scenario())

    assert [call[1]["user_id"] for call in inner.calls] == ["alice"] * 4


def test_create_session_injects_principal_state():
    inner = FakeSessionService()
    principal = _principal("alice")
    service = _PrincipalSessionService(inner, principal)

    asyncio.run(service.create_session(app_name="probe", user_id="mcp_user", state={"k": "v"}))

    name, kwargs = inner.calls[0]
    assert name == "create_session"
    assert kwargs["state"] == {"k": "v", "principal": principal.model_dump(mode="json")}


def test_delete_session_uses_subject():
    inner = FakeSessionService()
    service = _PrincipalSessionService(inner, _principal("alice"))

    asyncio.run(service.delete_session(app_name="probe", user_id="mcp_user", session_id="s1"))

    assert inner.calls == [
        (
            "delete_session",
            {"app_name": "probe", "user_id": "alice", "session_id": "s1"},
        )
    ]


def test_reap_uses_subject():
    inner = FakeRunner()
    runner = _PrincipalRunner(inner, _principal("alice"))
    sessions = weakref.WeakKeyDictionary()
    created = {"orphan"}

    asyncio.run(_reap_as(runner, sessions, created, {}))

    assert inner.session_service.calls == [
        (
            "delete_session",
            {"app_name": "probe", "user_id": "alice", "session_id": "orphan"},
        )
    ]
    assert "orphan" not in created


def test_sessions_are_scoped_by_subject():
    states: dict = {}

    alice = _state_for(states, "alice")
    bob = _state_for(states, "bob")
    same_alice = _state_for(states, "alice")

    assert alice is same_alice
    assert alice is not bob
    assert alice.sessions is not bob.sessions
    assert alice.created is not bob.created

    key = FakeConnection()
    alice.sessions[key] = "s1"
    alice.created.add("s1")

    assert key not in bob.sessions
    assert bob.created == set()
