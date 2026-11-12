"""SLICE-040: the console runs on OIDC principals instead of one static token."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent
from google.adk.sessions import InMemorySessionService

from adk_agent.audit import ListAuditSink
from adk_agent.cli import main
from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest, AgentRef, AuditEvent, EvalReport, Principal
from adk_agent.identity import IdentityUnavailable, InvalidIdentity, OidcIdentityProvider
from adk_agent.registry import FileAgentRegistry
from adk_agent.registry.manifest import published_from
from adk_agent.registry.reports import FileEvalReportStore

ALICE_TOKEN = "alice-token"
ADMIN_TOKEN = "admin-token"
OPS_TOKEN = "ops-token"
GUEST_TOKEN = "guest-token"
BOB_TOKEN = "bob-token"
AUTH_ALICE = {"Authorization": f"Bearer {ALICE_TOKEN}"}
AUTH_ADMIN = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
AUTH_OPS = {"Authorization": f"Bearer {OPS_TOKEN}"}
AUTH_GUEST = {"Authorization": f"Bearer {GUEST_TOKEN}"}
AUTH_BOB = {"Authorization": f"Bearer {BOB_TOKEN}"}

ALICE = Principal(tenant="acme", subject="alice", kind="human")
ADMIN = Principal(tenant="acme", subject="admin", kind="human", roles=["admin"])
OPS = Principal(tenant="acme", subject="ops", kind="human", roles=["ops"])
GUEST = Principal(tenant="acme", subject="guest", kind="human")
BOB = Principal(tenant="acme", subject="bob", kind="human")

TOKENS = {
    ALICE_TOKEN: ALICE,
    ADMIN_TOKEN: ADMIN,
    OPS_TOKEN: OPS,
    GUEST_TOKEN: GUEST,
    BOB_TOKEN: BOB,
}


class _FakeProvider:
    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    async def resolve(self, credential: str) -> Principal:
        principal = self._principals.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


class _DownProvider:
    async def resolve(self, credential: str) -> Principal:
        raise IdentityUnavailable("issuer unreachable")


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _app(provider=None, **kwargs) -> TestClient:
    app = build_console_app(
        _agents(), auth_token=None, oidc=provider or _FakeProvider(TOKENS), **kwargs
    )
    return TestClient(app)


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


def _policy(version: str = "1") -> dict:
    return {
        "version": version,
        "bindings": [
            {
                "role": "ops",
                "tenant": "acme",
                "allow": ["policy.update:*"],
            }
        ],
    }


def _write_policy(path: Path) -> Path:
    path.write_text(json.dumps(_policy()), encoding="utf-8")
    return path


def _event(tenant: str, run_id: str, trace_id: str) -> AuditEvent:
    return AuditEvent(
        event_id=f"{run_id}-e",
        run_id=run_id,
        trace_id=trace_id,
        tenant=tenant,
        principal=Principal(tenant=tenant, subject="svc", kind="service"),
        agent_ref=AgentRef(id="probe", version="dev", digest="d" * 64),
        action="agent.run",
        target="probe",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _oidc_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "issuer": "https://issuer.example",
                "audience": "adk-console",
                "jwks_url": "https://issuer.example/jwks.json",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_console_accepts_oidc_token():
    with _app() as client:
        response = client.get("/api/agents", headers=AUTH_ALICE)

    assert response.status_code == 200
    assert [agent["name"] for agent in response.json()] == ["probe"]


def test_console_rejects_missing_token():
    with _app() as client:
        response = client.get("/api/agents")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_console_maps_provider_outage_to_503():
    with _app(_DownProvider()) as client:
        response = client.get("/api/agents", headers=AUTH_ALICE)

    assert response.status_code == 503
    assert response.json() == {"error": "identity_unavailable"}


def test_sessions_are_scoped_by_subject():
    service = InMemorySessionService()
    alice_session = asyncio.run(service.create_session(app_name="probe", user_id="alice"))
    bob_session = asyncio.run(service.create_session(app_name="probe", user_id="bob"))

    with _app(session_service=service) as client:
        alice_seen = client.get("/api/sessions?agent=probe", headers=AUTH_ALICE)
        bob_seen = client.get("/api/sessions?agent=probe", headers=AUTH_BOB)

    assert [item["session_id"] for item in alice_seen.json()] == [alice_session.id]
    assert [item["session_id"] for item in bob_seen.json()] == [bob_session.id]


def test_registry_tenant_is_enforced(tmp_path):
    asyncio.run(FileAgentRegistry(tmp_path).publish(published_from(_manifest())))

    with _app(
        registry=FileAgentRegistry(tmp_path),
        eval_reports=FileEvalReportStore(tmp_path),
    ) as client:
        foreign = client.get("/api/registry?tenant=team-a", headers=AUTH_GUEST)
        own = client.get("/api/registry", headers=AUTH_GUEST)
        guest_tenants = client.get("/api/tenants", headers=AUTH_GUEST)
        admin_tenants = client.get("/api/tenants", headers=AUTH_ADMIN)

    assert foreign.status_code == 403
    assert foreign.json() == {"error": "tenant_forbidden"}
    assert own.status_code == 200
    assert own.json() == []
    assert guest_tenants.json() == []
    assert admin_tenants.json() == ["team-a"]


def test_eval_report_tenant_is_enforced(tmp_path):
    asyncio.run(FileAgentRegistry(tmp_path).publish(published_from(_manifest())))
    report = EvalReport(suite_id="smoke", version="1", passed=1, total=1)
    asyncio.run(FileEvalReportStore(tmp_path).put("team-a", "support-bot", "1.0.0", report))

    with _app(
        registry=FileAgentRegistry(tmp_path),
        eval_reports=FileEvalReportStore(tmp_path),
    ) as client:
        foreign = client.get("/api/registry/team-a/support-bot/1.0.0/eval", headers=AUTH_GUEST)
        allowed = client.get("/api/registry/team-a/support-bot/1.0.0/eval", headers=AUTH_ADMIN)

    assert foreign.status_code == 403
    assert foreign.json() == {"error": "tenant_forbidden"}
    assert allowed.status_code == 200
    assert allowed.json()["suite_id"] == "smoke"


def test_registry_admin_can_cross_tenants(tmp_path):
    published = asyncio.run(FileAgentRegistry(tmp_path).publish(published_from(_manifest())))

    with _app(
        registry=FileAgentRegistry(tmp_path),
        eval_reports=FileEvalReportStore(tmp_path),
    ) as client:
        response = client.get("/api/registry?tenant=team-a", headers=AUTH_ADMIN)

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["id"] == published.manifest.id
    assert entry["tenant"] == "team-a"


def test_read_views_are_tenant_scoped():
    sink = ListAuditSink()
    asyncio.run(sink.emit(_event("acme", "r1", "tr1")))
    asyncio.run(sink.emit(_event("team-a", "r2", "tr2")))

    with _app(audit_sink=sink) as client:
        guest_audit = client.get("/api/audit", headers=AUTH_GUEST)
        guest_runs = client.get("/api/runs", headers=AUTH_GUEST)
        guest_foreign_trace = client.get("/api/traces/tr2", headers=AUTH_GUEST)
        admin_audit = client.get("/api/audit", headers=AUTH_ADMIN)

    assert {event["tenant"] for event in guest_audit.json()} == {"acme"}
    assert {run["run_id"] for run in guest_runs.json()} == {"r1"}
    assert guest_foreign_trace.json()["error"] == "trace_not_found"
    assert {event["tenant"] for event in admin_audit.json()} == {"acme", "team-a"}


def test_policy_update_uses_token_roles(tmp_path):
    policy_file = _write_policy(tmp_path / "policy.json")

    with _app(policy_file=str(policy_file)) as client:
        allowed = client.put("/api/policy", json=_policy("2"), headers=AUTH_OPS)
        denied = client.put("/api/policy", json=_policy("2"), headers=AUTH_GUEST)

    assert allowed.status_code == 200
    assert allowed.json()["version"] == "2"
    assert denied.status_code == 403
    assert denied.json() == {"error": "policy_denied"}


def test_cli_accepts_oidc_config(tmp_path, monkeypatch):
    config = _oidc_config(tmp_path / "oidc.json")
    captured: dict = {}

    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})
    monkeypatch.setattr(
        "adk_agent.console.run_console",
        lambda agents, **kwargs: captured.update(kwargs),
    )

    main(["console", "--agents", "x.py", "--oidc-config", str(config)])

    assert isinstance(captured["oidc"], OidcIdentityProvider)


def test_cli_rejects_oidc_with_unauthenticated(tmp_path, monkeypatch, capsys):
    config = _oidc_config(tmp_path / "oidc.json")
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "console",
                "--agents",
                "x.py",
                "--oidc-config",
                str(config),
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "cannot combine" in capsys.readouterr().err


def test_cli_rejects_missing_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "console",
                "--agents",
                "x.py",
                "--oidc-config",
                str(tmp_path / "missing.json"),
            ]
        )

    assert exc.value.code == 1
    assert "invalid oidc config" in capsys.readouterr().err
