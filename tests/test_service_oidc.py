"""SLICE-041: the gateway and audit services trust OIDC identity."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adk_agent.audit.service import build_audit_pipeline_app
from adk_agent.cli import main
from adk_agent.core import (
    AgentRef,
    AuditEvent,
    Invocation,
    Message,
    ModelGatewayRequest,
    ModelPolicy,
    ModelRequest,
    ModelResponse,
    Principal,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
    ToolResponse,
)
from adk_agent.identity import IdentityUnavailable, InvalidIdentity, OidcIdentityProvider
from adk_agent.models.service import build_model_gateway_app
from adk_agent.tools.service import build_tool_gateway_app

TOKEN = "alice-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CLAIMED = Principal(tenant="t1", subject="alice", kind="human")
VERIFIED = Principal(tenant="t1", subject="alice", kind="human", roles=["admin"])

CONFIG = {
    "issuer": "https://issuer.example",
    "audience": "adk",
    "jwks_url": "https://issuer.example/jwks",
}


class FakeProvider:
    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    async def resolve(self, credential: str) -> Principal:
        principal = self._principals.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


class DownProvider:
    async def resolve(self, credential: str) -> Principal:
        raise IdentityUnavailable("issuer unreachable")


class CapturingModelGateway:
    def __init__(self) -> None:
        self.invocation: Invocation | None = None

    async def complete(self, invocation, request, policy) -> ModelResponse:
        self.invocation = invocation
        return ModelResponse(
            text="ok",
            provider=request.provider,
            model=request.model,
            input_tokens=1,
            output_tokens=1,
            egress="none",
        )


class CapturingToolGateway:
    def __init__(self) -> None:
        self.invocation: Invocation | None = None

    async def invoke(self, invocation, request, policy) -> ToolResponse:
        self.invocation = invocation
        return ToolResponse(output="ok")


class CapturingPipeline:
    def __init__(self) -> None:
        self.event: AuditEvent | None = None

    async def append(self, event: AuditEvent) -> Any:
        self.event = event
        return SimpleNamespace(hash="a" * 64)


def _provider() -> FakeProvider:
    return FakeProvider({TOKEN: VERIFIED})


def _invocation(principal: Principal) -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=principal,
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _model_body(principal: Principal = CLAIMED, provider: str = "fake") -> dict:
    return ModelGatewayRequest(
        invocation=_invocation(principal),
        request=ModelRequest(
            provider=provider, model="m", messages=[Message(role="user", content="hi")]
        ),
        policy=ModelPolicy(provider_allowlist=[provider]),
    ).model_dump(mode="json")


def _tool_body(principal: Principal = CLAIMED, tool_id: str = "add") -> dict:
    return ToolGatewayRequest(
        invocation=_invocation(principal),
        request=ToolRequest(tool_id=tool_id, args={"a": 1, "b": 2}),
        grants=[ToolGrant(tool_id=tool_id)],
    ).model_dump(mode="json")


def _event_body(tenant: str = "t1", principal: Principal = CLAIMED) -> dict:
    return AuditEvent(
        event_id="e1",
        run_id="r1",
        trace_id="tr1",
        tenant=tenant,
        principal=principal,
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="model.call",
        target="fake:m",
        status="ok",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ).model_dump(mode="json")


def test_model_gateway_requires_token():
    app = build_model_gateway_app(CapturingModelGateway(), oidc=_provider())

    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_model_body())

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_model_gateway_rejects_principal_mismatch():
    gateway = CapturingModelGateway()
    app = build_model_gateway_app(gateway, oidc=_provider())
    foreign = Principal(tenant="t2", subject="alice", kind="human")

    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_model_body(foreign), headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "principal_mismatch"}
    assert gateway.invocation is None


def _resolver(policy):
    async def resolve(_invocation):
        return policy

    return resolve


def test_model_gateway_uses_token_principal():
    gateway = CapturingModelGateway()
    app = build_model_gateway_app(
        gateway,
        oidc=_provider(),
        policy_resolver=_resolver(ModelPolicy(provider_allowlist=["fake"])),
    )

    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_model_body(), headers=AUTH)

    assert response.status_code == 200
    assert gateway.invocation is not None
    assert gateway.invocation.principal.tenant == "t1"
    assert gateway.invocation.principal.roles == ["admin"]


def test_tool_gateway_requires_token():
    app = build_tool_gateway_app(CapturingToolGateway(), oidc=_provider())

    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_tool_body())

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_tool_gateway_rejects_principal_mismatch():
    gateway = CapturingToolGateway()
    app = build_tool_gateway_app(gateway, oidc=_provider())
    foreign = Principal(tenant="t2", subject="alice", kind="human")

    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_tool_body(foreign), headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "principal_mismatch"}
    assert gateway.invocation is None


def test_tool_gateway_uses_token_principal():
    gateway = CapturingToolGateway()
    app = build_tool_gateway_app(gateway, oidc=_provider())

    with TestClient(app) as client:
        response = client.post("/v1/invoke", json=_tool_body(), headers=AUTH)

    assert response.status_code == 200
    assert gateway.invocation is not None
    assert gateway.invocation.principal.roles == ["admin"]


def test_audit_service_requires_token():
    app = build_audit_pipeline_app(CapturingPipeline(), oidc=_provider())

    with TestClient(app) as client:
        response = client.post("/v1/events", json=_event_body())

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_audit_service_rejects_principal_mismatch():
    pipeline = CapturingPipeline()
    app = build_audit_pipeline_app(pipeline, oidc=_provider())
    foreign = Principal(tenant="t2", subject="alice", kind="human")

    with TestClient(app) as client:
        response = client.post("/v1/events", json=_event_body("t2", foreign), headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "principal_mismatch"}
    assert pipeline.event is None


def test_audit_service_uses_token_principal():
    pipeline = CapturingPipeline()
    app = build_audit_pipeline_app(pipeline, oidc=_provider())

    with TestClient(app) as client:
        response = client.post("/v1/events", json=_event_body(), headers=AUTH)

    assert response.status_code == 202
    assert pipeline.event is not None
    assert pipeline.event.principal.roles == ["admin"]


def test_service_maps_provider_outage_to_503():
    app = build_model_gateway_app(CapturingModelGateway(), oidc=DownProvider())

    with TestClient(app) as client:
        response = client.post("/v1/complete", json=_model_body(), headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "identity_unavailable"}


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "oidc.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")
    return path


def test_cli_accepts_oidc_config(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_builder(pipeline, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("adk_agent.audit.service.build_audit_pipeline_app", fake_builder)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    main(
        [
            "serve-audit",
            "--out",
            str(tmp_path / "audit.jsonl"),
            "--oidc-config",
            str(_config(tmp_path)),
        ]
    )

    assert isinstance(captured["oidc"], OidcIdentityProvider)


def test_cli_model_gateway_accepts_oidc_config(tmp_path, monkeypatch):
    captured: dict = {}

    def fake_providers(names, *, vllm_url=None):
        return {}

    def fake_builder(gateway, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("adk_agent.models.service.build_providers", fake_providers)
    monkeypatch.setattr("adk_agent.models.service.build_model_gateway_app", fake_builder)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    main(["serve-model-gateway", "--oidc-config", str(_config(tmp_path))])

    assert isinstance(captured["oidc"], OidcIdentityProvider)


def test_cli_rejects_oidc_with_unauthenticated(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "serve-audit",
                "--out",
                str(tmp_path / "audit.jsonl"),
                "--oidc-config",
                str(_config(tmp_path)),
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "cannot combine" in capsys.readouterr().err


def test_cli_rejects_missing_config(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "serve-audit",
                "--out",
                str(tmp_path / "audit.jsonl"),
                "--oidc-config",
                str(tmp_path / "missing.json"),
            ]
        )

    assert exc.value.code == 1
    assert "invalid oidc config" in capsys.readouterr().err
