"""SLICE-061: opt-in tenant-scoped session keys."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent import cli
from adk_agent.console import build_console_app
from adk_agent.core import Principal
from adk_agent.mcp.server import _PrincipalRunner, _PrincipalSessionService
from adk_agent.runtime.sessions import scoped_user_id

AUTH_A = {"Authorization": "Bearer tenant-a-token"}
AUTH_B = {"Authorization": "Bearer tenant-b-token"}
ALICE_A = Principal(tenant="acme", subject="alice", kind="human")
ALICE_B = Principal(tenant="other", subject="alice", kind="human")


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        if credential == "tenant-a-token":
            return ALICE_A
        if credential == "tenant-b-token":
            return ALICE_B
        raise ValueError("unknown token")


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False
        self.function_call = None
        self.function_response = None


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.author = "probe"
        self.content = FakeContent(text)

    def is_final_response(self) -> bool:
        return True


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _patch_runner(monkeypatch) -> None:
    async def run_async(self, **kwargs):
        yield FakeEvent("hi there")

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)


def _app(service, **kwargs) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token=None,
            oidc=_Provider(),
            session_service=service,
            **kwargs,
        )
    )


def _chat(client: TestClient, headers: dict, session_id: str | None = None) -> str:
    body: dict = {"agent": "probe", "message": "hello"}
    if session_id is not None:
        body["session_id"] = session_id
    response = client.post("/api/chat", json=body, headers=headers)
    assert response.status_code == 200
    return response.json()["session_id"]


def test_scoped_user_id():
    assert scoped_user_id(ALICE_A) == "acme:alice"
    assert scoped_user_id(ALICE_B) == "other:alice"


def test_console_isolates_tenants(monkeypatch):
    _patch_runner(monkeypatch)
    with _app(InMemorySessionService(), session_tenant_scope=True) as client:
        first = _chat(client, AUTH_A)
        second = _chat(client, AUTH_B, session_id=first)

    assert second != first


def test_console_default_keeps_subject(monkeypatch):
    _patch_runner(monkeypatch)
    with _app(InMemorySessionService()) as client:
        first = _chat(client, AUTH_A)
        second = _chat(client, AUTH_B, session_id=first)

    assert second == first


def test_console_lists_own_tenant_only(monkeypatch):
    _patch_runner(monkeypatch)
    with _app(InMemorySessionService(), session_tenant_scope=True) as client:
        first = _chat(client, AUTH_A)
        second = _chat(client, AUTH_B)
        seen_a = client.get("/api/sessions?agent=probe", headers=AUTH_A).json()
        seen_b = client.get("/api/sessions?agent=probe", headers=AUTH_B).json()

    assert [item["session_id"] for item in seen_a] == [first]
    assert [item["session_id"] for item in seen_b] == [second]


class _Inner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_session(self, *, app_name, user_id, state=None, session_id=None):
        self.calls.append({"user_id": user_id})
        return object()

    async def get_session(self, *, app_name, user_id, session_id, config=None):
        self.calls.append({"user_id": user_id})
        return None

    async def list_sessions(self, *, app_name, user_id=None):
        self.calls.append({"user_id": user_id})
        return object()


class _Runner:
    app_name = "probe"

    def __init__(self) -> None:
        self.session_service = _Inner()
        self.seen: list[str] = []

    def run_async(self, *, user_id, **kwargs):
        self.seen.append(user_id)

        async def events():
            yield "event"

        return events()


def test_mcp_proxy_scopes_user_id():
    inner = _Inner()
    service = _PrincipalSessionService(inner, ALICE_A, tenant_scope=True)

    async def scenario():
        await service.create_session(app_name="probe", user_id="mcp_user")
        await service.get_session(app_name="probe", user_id="mcp_user", session_id="s1")
        await service.list_sessions(app_name="probe", user_id="mcp_user")

    asyncio.run(scenario())

    assert [call["user_id"] for call in inner.calls] == ["acme:alice"] * 3
    assert asyncio.run(
        _drain(
            _PrincipalRunner(_Runner(), ALICE_A, tenant_scope=True).run_async(user_id="mcp_user")
        )
    ) == ["event"]


def test_mcp_proxy_default_subject():
    inner = _Inner()
    service = _PrincipalSessionService(inner, ALICE_A)

    asyncio.run(service.create_session(app_name="probe", user_id="mcp_user"))

    assert inner.calls == [{"user_id": "alice"}]


async def _drain(events) -> list:
    return [event async for event in events]


def test_console_cli_wires_flag(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )

    cli.main(["console", "--agents", str(path), "--session-tenant-scope"])

    assert captured["session_tenant_scope"] is True
