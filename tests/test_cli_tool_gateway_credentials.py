"""SLICE-140: the tool gateway resolves stored credential ciphertext."""

from __future__ import annotations

import asyncio
import base64
import json
import os

from adk_agent import cli
from adk_agent.core import ConnectorSpec
from adk_agent.registry import FileConnectorStore, FileCredentialStore


def _spec() -> ConnectorSpec:
    return ConnectorSpec(
        connector_id="crm",
        tenant="local",
        kind="http",
        base_url="https://crm.example.com",
        auth_ref="secret://" + "local/token",
        methods=["GET"],
        path_prefixes=["/v1/crm/"],
        data_classes=["internal"],
    )


def test_tool_gateway_uses_a_routing_provider(tmp_path, monkeypatch):
    from adk_agent.secretstore import RoutingSecretProvider

    monkeypatch.setenv(
        "ADK_SECRET_KEKS",
        json.dumps(
            {"active": "k1", "keys": {"k1": base64.b64encode(os.urandom(32)).decode("ascii")}}
        ),
    )
    asyncio.run(FileConnectorStore(tmp_path / "connectors").add(_spec()))
    captured: dict = {}

    def fake_tools(specs, secrets=None, **kwargs):
        captured["secrets"] = secrets
        return []

    monkeypatch.setattr("adk_agent.tools.connectors.build_connector_tools", fake_tools)
    monkeypatch.setattr(
        "adk_agent.tools.service.build_tool_gateway_app", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    cli.main(
        [
            "serve-tool-gateway",
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--allow-unauthenticated",
        ]
    )

    assert isinstance(captured["secrets"]._inner, RoutingSecretProvider)


def test_tool_gateway_wires_routing_without_a_key_backend(tmp_path, monkeypatch):
    import pytest

    from adk_agent.core import CredentialBinding
    from adk_agent.secretstore import (
        LocalKeyBackend,
        RoutingSecretProvider,
        SecretNotFound,
        credential_aad,
    )

    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_LOCAL_TOKEN", "from-env")
    reference = "secret://" + "local/token"
    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    asyncio.run(
        FileCredentialStore(tmp_path / "credentials").add(
            CredentialBinding(
                credential_id="crm",
                tenant="local",
                secret_ref=reference,
                created_by="ops",
                created_at="2026-11-18T00:00:00Z",
                wrapped_secret=backend.wrap(b"stored", credential_aad("local", "crm")),
                secret_key_id="k1",
                secret_version=1,
            )
        )
    )
    asyncio.run(FileConnectorStore(tmp_path / "connectors").add(_spec()))
    captured: dict = {}

    def fake_tools(specs, secrets=None, **kwargs):
        captured["secrets"] = secrets
        return []

    monkeypatch.setattr("adk_agent.tools.connectors.build_connector_tools", fake_tools)
    monkeypatch.setattr(
        "adk_agent.tools.service.build_tool_gateway_app", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    cli.main(
        [
            "serve-tool-gateway",
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--allow-unauthenticated",
        ]
    )

    inner = captured["secrets"]._inner
    assert isinstance(inner, RoutingSecretProvider)
    with pytest.raises(SecretNotFound):
        asyncio.run(inner.resolve(reference))
