"""SLICE-042: MCP HTTP transport trusts OIDC identity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from adk_agent.cli import main
from adk_agent.core import Principal
from adk_agent.identity import IdentityUnavailable, InvalidIdentity, OidcIdentityProvider
from adk_agent.mcp.http import build_http_app

TOKEN = "alice-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

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


def _provider() -> FakeProvider:
    return FakeProvider(
        {TOKEN: Principal(tenant="t1", subject="alice", kind="human", roles=["admin"])}
    )


def _app(oidc):
    return build_http_app(MCPServer(name="probe"), auth_token=None, oidc=oidc)


def test_healthz_open():
    with TestClient(_app(_provider())) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_missing_token_is_401():
    with TestClient(_app(_provider())) as client:
        response = client.post("/mcp", json={})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_invalid_token_is_401():
    with TestClient(_app(_provider())) as client:
        response = client.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


def test_provider_outage_is_503():
    with TestClient(_app(DownProvider())) as client:
        response = client.post("/mcp", json={}, headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "identity_unavailable"}


def test_valid_token_reaches_mcp_app():
    with TestClient(_app(_provider())) as client:
        response = client.post("/mcp", json={}, headers=AUTH)

    assert response.status_code != 401


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "oidc.json"
    path.write_text(json.dumps(CONFIG), encoding="utf-8")
    return path


def test_cli_serve_passes_oidc(tmp_path, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_agent",
        lambda agent, **kwargs: captured.update(kwargs),
    )

    main(
        [
            "serve",
            "--agent",
            "x.py",
            "--transport",
            "streamable-http",
            "--oidc-config",
            str(_config(tmp_path)),
        ]
    )

    assert isinstance(captured["oidc"], OidcIdentityProvider)


def test_cli_serve_many_passes_oidc(tmp_path, monkeypatch):
    captured: dict = {}

    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_many",
        lambda agents, **kwargs: captured.update(kwargs),
    )

    main(
        [
            "serve-many",
            "--agents",
            "x.py",
            "--transport",
            "streamable-http",
            "--oidc-config",
            str(_config(tmp_path)),
        ]
    )

    assert isinstance(captured["oidc"], OidcIdentityProvider)


def test_cli_rejects_oidc_on_stdio(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())

    with pytest.raises(SystemExit) as exc:
        main(["serve", "--agent", "x.py", "--oidc-config", str(_config(tmp_path))])

    assert exc.value.code == 1
    assert "requires streamable-http" in capsys.readouterr().err


def test_cli_rejects_oidc_with_unauthenticated(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "serve",
                "--agent",
                "x.py",
                "--transport",
                "streamable-http",
                "--oidc-config",
                str(_config(tmp_path)),
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "cannot combine" in capsys.readouterr().err
