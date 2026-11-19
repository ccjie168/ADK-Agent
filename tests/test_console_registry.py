"""SLICE-038: the console exposes the registry and eval reports read-only."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import (
    AgentManifest,
    EvalCaseResult,
    EvalReport,
    RemoteAgent,
    RemoteAgentError,
)
from adk_agent.registry import FileAgentRegistry, FileRemoteAgentStore
from adk_agent.registry.manifest import published_from
from adk_agent.registry.reports import FileEvalReportStore

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


def _manifest(**overrides) -> AgentManifest:
    data = {
        "id": "support-bot",
        "version": "1.0.0",
        "tenant": "team-a",
        "owner": "team-a",
        "description": "support",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    data.update(overrides)
    return AgentManifest(**data)


def _report() -> EvalReport:
    return EvalReport(
        suite_id="smoke",
        version="1",
        passed=2,
        total=2,
        results=[EvalCaseResult(case_id="a", passed=True, actual="ok")],
    )


def _populated(tmp_path):
    published = published_from(_manifest())
    asyncio.run(FileAgentRegistry(tmp_path).publish(published))
    return published


def _app(
    tmp_path,
    *,
    registry: bool = True,
    eval_reports: bool = True,
    remote_agents=None,
    roles=("admin",),
):
    kwargs = {}
    if registry:
        kwargs["registry"] = FileAgentRegistry(tmp_path)
    if eval_reports:
        kwargs["eval_reports"] = FileEvalReportStore(tmp_path)
    if remote_agents is not None:
        kwargs["remote_agents"] = remote_agents
    return build_console_app(_agents(), auth_token="secret", roles=roles, **kwargs)


def _digest(char: str = "a") -> str:
    return "sha256:" + char * 64


def _record(**overrides) -> RemoteAgent:
    data = {
        "remote_id": "crm-bot",
        "tenant": "team-a",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/card.json",
        "label": "CRM bot",
        "card_digest": _digest(),
        "checked_at": datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
        "status": "pinned",
        "enabled": True,
    }
    data.update(overrides)
    return RemoteAgent(**data)


def _remote_store(tmp_path, *records: RemoteAgent) -> FileRemoteAgentStore:
    store = FileRemoteAgentStore(tmp_path / "remote-state")
    for record in records or (_record(),):
        asyncio.run(store.put(record))
    return store


class _BrokenRemoteStore:
    async def list(self) -> list[RemoteAgent]:
        raise RemoteAgentError("store down")


def test_tenants_endpoint(tmp_path):
    _populated(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/tenants", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == ["team-a"]


def test_registry_listing(tmp_path):
    published = _populated(tmp_path)
    report = _report()
    asyncio.run(FileEvalReportStore(tmp_path).put("team-a", "support-bot", "1.0.0", report))

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["tenant"] == "team-a"
    assert entry["id"] == "support-bot"
    assert entry["version"] == "1.0.0"
    assert entry["digest"] == published.digest
    assert entry["description"] == "support"
    assert entry["published_at"] == published.published_at.isoformat()
    assert entry["has_eval_report"] is True
    assert entry["manifest"] == published.manifest.model_dump(mode="json")


def test_eval_report_endpoint(tmp_path):
    _populated(tmp_path)
    report = _report()
    asyncio.run(FileEvalReportStore(tmp_path).put("team-a", "support-bot", "1.0.0", report))

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry/team-a/support-bot/1.0.0/eval", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == report.model_dump(mode="json")


def test_registry_not_configured():
    with TestClient(build_console_app(_agents(), auth_token="secret", roles=["admin"])) as client:
        for path in (
            "/api/tenants",
            "/api/registry",
            "/api/registry/team-a/support-bot/1.0.0/eval",
        ):
            response = client.get(path, headers=AUTH)
            assert response.status_code == 404
            assert response.json() == {"error": "registry_not_configured"}


def test_unsafe_tenant_is_rejected(tmp_path):
    _populated(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry", params={"tenant": "../x"}, headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}


def test_corrupt_record_is_500_without_path(tmp_path):
    _populated(tmp_path)
    path = tmp_path / "team-a" / "support-bot" / "1.0.0.json"
    data = json.loads(path.read_text())
    data["digest"] = "0" * 64
    path.write_text(json.dumps(data))

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 500
    assert response.json() == {"error": "registry_corrupt"}
    assert str(tmp_path) not in response.text
    assert "1.0.0.json" not in response.text


def test_malformed_record_is_500_without_path(tmp_path):
    _populated(tmp_path)
    path = tmp_path / "team-a" / "support-bot" / "1.0.0.json"
    path.write_text("{not json")

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 500
    assert response.json() == {"error": "registry_corrupt"}
    assert str(tmp_path) not in response.text
    assert "1.0.0.json" not in response.text


def test_entries_carry_source(tmp_path):
    _populated(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["source"] == "local"
    assert entry["version"] == "1.0.0"


def test_remote_entries_merged(tmp_path):
    _populated(tmp_path)
    store = _remote_store(tmp_path)

    with TestClient(_app(tmp_path, remote_agents=store)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    entries = response.json()
    remote = next(entry for entry in entries if entry["source"] == "remote")
    assert remote == {
        "tenant": "team-a",
        "id": "crm-bot",
        "source": "remote",
        "peer_id": "crm",
        "label": "CRM bot",
        "agent_card_url": "https://crm.example.com/card.json",
        "enabled": True,
        "trust": {
            "status": "pinned",
            "card_digest": _digest(),
            "observed_digest": None,
            "checked_at": "2026-11-14T09:30:00+00:00",
        },
    }
    local = next(entry for entry in entries if entry["source"] == "local")
    assert local["id"] == "support-bot"


def test_local_sorts_before_remote(tmp_path):
    _populated(tmp_path)
    store = _remote_store(tmp_path, _record(remote_id="support-bot"))

    with TestClient(_app(tmp_path, remote_agents=store)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    entries = response.json()
    assert [entry["source"] for entry in entries] == ["local", "remote"]
    assert {entry["id"] for entry in entries} == {"support-bot"}


def test_remote_only(tmp_path):
    store = _remote_store(tmp_path)

    with TestClient(
        _app(tmp_path, registry=False, eval_reports=False, remote_agents=store)
    ) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["source"] == "remote"
    assert entry["id"] == "crm-bot"


def test_no_sources(tmp_path):
    with TestClient(_app(tmp_path, registry=False, eval_reports=False)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "registry_not_configured"}


def test_remote_tenant_filter(tmp_path):
    _populated(tmp_path)
    store = _remote_store(
        tmp_path,
        _record(),
        _record(remote_id="other-bot", tenant="team-b"),
    )

    with TestClient(_app(tmp_path, remote_agents=store)) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    entries = response.json()
    remote_ids = [entry["id"] for entry in entries if entry["source"] == "remote"]
    assert remote_ids == ["crm-bot"]
    assert all(entry["tenant"] == "team-a" for entry in entries)


def test_remote_states_visible(tmp_path):
    store = _remote_store(
        tmp_path,
        _record(remote_id="pinned-bot"),
        _record(remote_id="changed-bot", status="changed", observed_digest=_digest("b")),
        _record(remote_id="down-bot", status="unreachable"),
        _record(remote_id="off-bot", enabled=False),
    )

    with TestClient(
        _app(tmp_path, registry=False, eval_reports=False, remote_agents=store)
    ) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 200
    entries = {entry["id"]: entry for entry in response.json()}
    assert entries["pinned-bot"]["trust"]["status"] == "pinned"
    assert entries["changed-bot"]["trust"]["status"] == "changed"
    assert entries["changed-bot"]["trust"]["observed_digest"] == _digest("b")
    assert entries["down-bot"]["trust"]["status"] == "unreachable"
    assert entries["off-bot"]["enabled"] is False


def test_remote_store_unavailable(tmp_path):
    with TestClient(
        _app(tmp_path, registry=False, eval_reports=False, remote_agents=_BrokenRemoteStore())
    ) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "remote_agent_store_unavailable"}


def test_panel_has_remote_controls(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert 'id="refresh-remote"' in response.text
    assert 'id="registry-cards"' in response.text
    assert 'id="registry-body"' not in response.text


def test_unsafe_tenant_remote_only(tmp_path):
    store = _remote_store(tmp_path)
    with TestClient(
        _app(tmp_path, registry=False, eval_reports=False, remote_agents=store)
    ) as client:
        response = client.get("/api/registry?tenant=../escape", headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "unsafe_tenant"}


def test_read_requires_capability(tmp_path):
    _populated(tmp_path)
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        listed = client.get("/api/registry", headers=AUTH)

    assert listed.status_code == 403
    assert listed.json() == {"error": "forbidden"}


def test_publisher_can_read_registry(tmp_path):
    published = published_from(_manifest(tenant="local"))
    asyncio.run(FileAgentRegistry(tmp_path).publish(published))
    with TestClient(_app(tmp_path, roles=["publisher"])) as client:
        listed = client.get("/api/registry", headers=AUTH)

    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()] == ["support-bot"]


def test_eval_read_requires_capability(tmp_path):
    published = published_from(_manifest(tenant="local"))
    asyncio.run(FileAgentRegistry(tmp_path).publish(published))
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = client.get("/api/registry/local/support-bot/1.0.0/eval", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
