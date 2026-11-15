"""SLICE-113: console auth endpoints for the browser login flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from adk_agent.console import build_console_app
from adk_agent.identity import OidcLoginError

REDIRECT = "http://127.0.0.1:8081/auth/callback"


class FakeLogin:
    def public_config(self) -> dict:
        return {
            "enabled": True,
            "client_id": "console",
            "authorization_endpoint": "http://127.0.0.1:9000/authorize",
            "redirect_uri": REDIRECT,
            "scopes": ["openid", "email"],
        }

    async def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict:
        if code == "bad":
            raise OidcLoginError("rejected")
        return {"access_token": "at", "token_type": "Bearer", "expires_in": 60}


def _client(login: FakeLogin | None = None) -> TestClient:
    return TestClient(build_console_app({}, auth_token="secret", oidc_login=login))


def test_auth_config_without_oidc_is_disabled() -> None:
    with _client() as client:
        assert client.get("/auth/config").json() == {"enabled": False}


def test_auth_config_with_oidc() -> None:
    with _client(FakeLogin()) as client:
        body = client.get("/auth/config").json()
    assert body["enabled"] is True
    assert body["client_id"] == "console"
    assert "token_endpoint" not in body


def test_auth_token_returns_the_access_token() -> None:
    with _client(FakeLogin()) as client:
        response = client.post(
            "/auth/token",
            json={"code": "ok", "code_verifier": "v" * 43, "redirect_uri": REDIRECT},
        )
    assert response.status_code == 200
    assert response.json()["access_token"] == "at"


def test_auth_token_rejects_invalid_body() -> None:
    with _client(FakeLogin()) as client:
        assert client.post("/auth/token", json={}).status_code == 400
        assert client.post("/auth/token", json={"code": "ok"}).status_code == 400


def test_auth_token_maps_exchange_errors_to_401() -> None:
    with _client(FakeLogin()) as client:
        response = client.post(
            "/auth/token",
            json={"code": "bad", "code_verifier": "v" * 43, "redirect_uri": REDIRECT},
        )
    assert response.status_code == 401
    assert response.json() == {"error": "oidc_login_failed"}


def test_auth_callback_serves_the_app() -> None:
    with _client(FakeLogin()) as client:
        response = client.get("/auth/callback")
    assert response.status_code == 200
    assert "ADK Console" in response.text
