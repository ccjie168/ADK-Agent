"""SLICE-038: the console exposes the registry and eval reports read-only."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest, EvalCaseResult, EvalReport
from adk_agent.registry import FileAgentRegistry
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


def _app(tmp_path, *, registry: bool = True, eval_reports: bool = True):
    kwargs = {}
    if registry:
        kwargs["registry"] = FileAgentRegistry(tmp_path)
    if eval_reports:
        kwargs["eval_reports"] = FileEvalReportStore(tmp_path)
    return build_console_app(_agents(), auth_token="secret", **kwargs)


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
    with TestClient(build_console_app(_agents(), auth_token="secret")) as client:
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
