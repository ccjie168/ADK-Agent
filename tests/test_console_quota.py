"""SLICE-044: the console enforces per-tenant quotas."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import Principal, QuotaConfig, QuotaPolicy
from adk_agent.runtime.quota import InMemoryQuotaManager
from adk_agent.runtime.quota_postgres import QuotaStoreUnavailable

AUTH = {"Authorization": "Bearer alice-token"}
ALICE = Principal(tenant="acme", subject="alice", kind="human")


class _Provider:
    async def resolve(self, credential: str) -> Principal:
        return ALICE


class FakePart:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.thought = False
        self.function_call = None
        self.function_response = None


class FakeContent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, parts: list[FakePart]) -> None:
        self.author = "probe"
        self.content = FakeContent(parts)

    def is_final_response(self) -> bool:
        return True


class _DownReservation:
    async def __aenter__(self) -> None:
        raise QuotaStoreUnavailable("down")

    async def __aexit__(self, *args: object) -> None:
        return None


class _DownQuota:
    def reserve(self, tenant: str, policy: QuotaPolicy) -> _DownReservation:
        return _DownReservation()


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _patch_runner(monkeypatch) -> dict[str, int]:
    calls = {"runs": 0}

    async def run_async(self, **kwargs):
        calls["runs"] += 1
        yield FakeEvent([FakePart("hi there")])

    monkeypatch.setattr("google.adk.runners.Runner.run_async", run_async)
    return calls


def _client(*, quota, config, audit=None) -> TestClient:
    return TestClient(
        build_console_app(
            _agents(),
            auth_token=None,
            oidc=_Provider(),
            quota=quota,
            quota_config=config,
            audit_sink=audit,
        )
    )


def _chat(client: TestClient):
    return client.post("/api/chat", json={"agent": "probe", "message": "hi"}, headers=AUTH)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        if name:
            events.append((name, json.loads(data)))
    return events


def _config(max_runs: int = 1, tenant: str = "acme") -> QuotaConfig:
    return QuotaConfig(tenants={tenant: QuotaPolicy(max_runs=max_runs, window_seconds=60)})


def test_chat_quota_exceeded(monkeypatch):
    calls = _patch_runner(monkeypatch)
    with _client(quota=InMemoryQuotaManager(), config=_config()) as client:
        first = _chat(client)
        second = _chat(client)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json() == {"error": "quota_exceeded"}
    assert calls["runs"] == 1


def test_quota_denial_is_audited(monkeypatch):
    _patch_runner(monkeypatch)
    audit = ListAuditSink()
    with _client(quota=InMemoryQuotaManager(), config=_config(), audit=audit) as client:
        _chat(client)
        _chat(client)

    denied = [event for event in audit.recent(10) if event.status == "denied"]
    [event] = denied
    assert event.action == "agent.run"
    assert event.error_code == "quota_exceeded"


def test_stream_quota_exceeded(monkeypatch):
    _patch_runner(monkeypatch)
    with _client(quota=InMemoryQuotaManager(), config=_config()) as client:
        with client.stream(
            "POST", "/api/chat/stream", json={"agent": "probe", "message": "hi"}, headers=AUTH
        ) as first:
            assert first.status_code == 200
            first_events = _parse_sse(first.read().decode())
        with client.stream(
            "POST", "/api/chat/stream", json={"agent": "probe", "message": "hi"}, headers=AUTH
        ) as second:
            assert second.status_code == 200
            second_events = _parse_sse(second.read().decode())

    assert any(name == "done" for name, _ in first_events)
    assert ("error", {"error": "quota_exceeded"}) in second_events


def test_unlisted_tenant_unlimited(monkeypatch):
    calls = _patch_runner(monkeypatch)
    with _client(quota=InMemoryQuotaManager(), config=_config(tenant="other")) as client:
        first = _chat(client)
        second = _chat(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls["runs"] == 2


def test_quota_store_unavailable(monkeypatch):
    _patch_runner(monkeypatch)
    with _client(quota=_DownQuota(), config=_config()) as client:
        response = _chat(client)

    assert response.status_code == 503
    assert response.json() == {"error": "quota_unavailable"}


def test_quota_endpoint_returns_usage():
    with _client(quota=InMemoryQuotaManager(), config=_config(max_runs=3)) as client:
        response = client.get("/api/quota", headers=AUTH)

    assert response.status_code == 200
    data = response.json()
    assert data["window_runs"] == 0
    assert data["active_leases"] == 0
    assert data["max_runs"] == 3
    assert data["window_seconds"] == 60
