"""SLICE-086: connectors execute under an egress policy."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent import cli
from adk_agent.core import ConnectorSpec, Invocation, Principal, ToolGrant, ToolRequest
from adk_agent.secretstore import MappingSecretProvider, PrefixedEnvSecretProvider, SecretNotFound
from adk_agent.tools import (
    ConnectorDenied,
    FunctionRegistry,
    FunctionToolGateway,
    GrantPolicyEngine,
)
from adk_agent.tools.connectors import ConnectorResponse, build_connector_tools


class FakeAdapter:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"ok": 1}',
        content_type: str = "application/json",
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.content_type = content_type
        self.error = error
        self.calls: list[dict] = []

    async def request(self, *, method, url, headers, timeout, max_bytes=1024):
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
        if self.error is not None:
            raise self.error
        return ConnectorResponse(status=self.status, content_type=self.content_type, body=self.body)


class FakeAudit:
    def __init__(self) -> None:
        self.events = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _spec(**overrides) -> ConnectorSpec:
    data = {
        "connector_id": "crm",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://crm/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/"],
        "data_classes": ["internal"],
        "max_response_bytes": 64,
    }
    data.update(overrides)
    return ConnectorSpec(**data)


def _tool(spec=None, adapter=None, secrets=None):
    spec = spec or _spec()
    adapter = adapter or FakeAdapter()
    secrets = secrets or MappingSecretProvider({"secret://crm/token": "tok"})
    return build_connector_tools([spec], secrets=secrets, adapter=adapter)[0], adapter


def test_allowed_request():
    tool, adapter = _tool()

    output = asyncio.run(tool.handler(path="/v1/records", method="GET", query={"q": "x"}))

    assert output == {"status": 200, "body": {"ok": 1}}
    [call] = adapter.calls
    assert call["url"] == "https://crm.example.com/v1/records?q=x"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["timeout"] == 10
    assert tool.egress == "third_party"
    assert tool.tool_id == "crm"
    assert tool.data_classes == ("internal",)


def test_method_denied():
    tool, adapter = _tool()

    with pytest.raises(ConnectorDenied) as exc:
        asyncio.run(tool.handler(path="/v1/records", method="POST"))

    assert exc.value.error_code == "method_denied"
    assert adapter.calls == []


@pytest.mark.parametrize(
    "path", ["/v2/records", "/v1/../etc", "v1/records", "https://evil.example"]
)
def test_path_denied(path):
    tool, adapter = _tool()

    with pytest.raises(ConnectorDenied) as exc:
        asyncio.run(tool.handler(path=path))

    assert exc.value.error_code == "path_denied"
    assert adapter.calls == []


def test_redirect_denied():
    tool, _adapter = _tool(adapter=FakeAdapter(status=302))

    with pytest.raises(ConnectorDenied) as exc:
        asyncio.run(tool.handler(path="/v1/records"))

    assert exc.value.error_code == "egress_denied"


def test_response_too_large():
    tool, _adapter = _tool(adapter=FakeAdapter(body=b"x" * 65, content_type="text/plain"))

    with pytest.raises(ConnectorDenied) as exc:
        asyncio.run(tool.handler(path="/v1/records"))

    assert exc.value.error_code == "response_too_large"


def test_secret_unavailable():
    tool, _adapter = _tool(secrets=MappingSecretProvider({}))

    with pytest.raises(ConnectorDenied) as exc:
        asyncio.run(tool.handler(path="/v1/records"))

    assert exc.value.error_code == "secret_unavailable"


def test_gateway_audits_third_party():
    tool, _adapter = _tool()
    sink = FakeAudit()
    gateway = FunctionToolGateway(FunctionRegistry([tool]), audit=sink)
    invocation = Invocation(
        run_id="r1",
        trace_id="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref={"id": "bot", "version": "1.0.0", "digest": "sha256:" + "a" * 64},
        input="x",
    )

    asyncio.run(
        gateway.invoke(
            invocation,
            ToolRequest(tool_id="crm", args={"path": "/v1/records"}),
            GrantPolicyEngine([ToolGrant(tool_id="crm")]),
        )
    )

    [event] = sink.events
    assert event.egress == "third_party"
    assert event.status == "ok"


def test_prefixed_env_provider(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_CRM_TOKEN", "tok")
    provider = PrefixedEnvSecretProvider()

    assert asyncio.run(provider.resolve("secret://crm/token")) == "tok"
    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("secret://missing"))


def test_cli_merges_connectors(tmp_path, monkeypatch):
    connectors = tmp_path / "connectors"
    connectors.mkdir()
    (connectors / "crm.json").write_text(
        json.dumps(_spec().model_dump(mode="json")), encoding="utf-8"
    )
    captured: dict = {}
    monkeypatch.setattr(
        "adk_agent.tools.service.build_tool_gateway_app",
        lambda *a, **k: captured.update(gateway=a[0]),
    )
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: None)

    cli.main(
        [
            "serve-tool-gateway",
            "--connectors-dir",
            str(connectors),
            "--connector-tenant",
            "local",
            "--allow-unauthenticated",
        ]
    )

    assert captured["gateway"].registry.get("crm") is not None


def test_json_body_is_sent():
    """SLICE-308: a POST connector call carries its JSON body."""

    class BodyAdapter(FakeAdapter):
        async def request(self, *, method, url, headers, timeout, max_bytes=1024, body=None):
            self.calls.append({"headers": headers, "body": body})
            return ConnectorResponse(
                status=201, content_type="application/json", body=b'{"id": "t-1"}'
            )

    adapter = BodyAdapter()
    spec = _spec(methods=["GET", "POST"])
    tool, _ = _tool(spec=spec, adapter=adapter)

    output = asyncio.run(tool.handler(path="/v1/records", method="POST", json_body={"title": "x"}))

    assert output == {"status": 201, "body": {"id": "t-1"}}
    [call] = adapter.calls
    assert call["body"] == b'{"title": "x"}'
    assert call["headers"]["Content-Type"] == "application/json"
