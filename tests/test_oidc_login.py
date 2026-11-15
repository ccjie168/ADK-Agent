"""SLICE-113: the console exchanges OIDC codes with PKCE."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from adk_agent.identity import OidcBrowserConfig, OidcLogin, OidcLoginError

REDIRECT = "http://127.0.0.1:8081/auth/callback"
VERIFIER = "v" * 43


def _config(**overrides) -> OidcBrowserConfig:
    data = {
        "client_id": "console",
        "authorization_endpoint": "http://127.0.0.1:9000/authorize",
        "token_endpoint": "http://127.0.0.1:9000/token",
        "redirect_uri": REDIRECT,
        "scopes": ("openid", "email"),
    }
    data.update(overrides)
    return OidcBrowserConfig(**data)


def _login(handler, config: OidcBrowserConfig | None = None) -> OidcLogin:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OidcLogin(config or _config(), client=client)


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 60}
    )


def test_public_config_hides_server_settings() -> None:
    config = _login(_ok).public_config()

    assert config["enabled"] is True
    assert config["client_id"] == "console"
    assert config["redirect_uri"] == REDIRECT
    assert "token_endpoint" not in config
    assert "client_secret_env" not in config


def test_exchange_posts_the_authorization_code() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(
            200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 60}
        )

    result = asyncio.run(
        _login(handler).exchange(code="code-1", code_verifier=VERIFIER, redirect_uri=REDIRECT)
    )

    assert result == {"access_token": "at", "token_type": "Bearer", "expires_in": 60}
    assert "grant_type=authorization_code" in seen["body"]
    assert "code=code-1" in seen["body"]
    assert f"code_verifier={VERIFIER}" in seen["body"]


def test_redirect_uri_must_match() -> None:
    with pytest.raises(OidcLoginError):
        asyncio.run(
            _login(_ok).exchange(
                code="code-1", code_verifier=VERIFIER, redirect_uri="http://evil.example/cb"
            )
        )


def test_short_verifier_is_rejected() -> None:
    with pytest.raises(OidcLoginError):
        asyncio.run(
            _login(_ok).exchange(code="code-1", code_verifier="short", redirect_uri=REDIRECT)
        )


def test_non_200_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with pytest.raises(OidcLoginError):
        asyncio.run(
            _login(handler).exchange(code="code-1", code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )


def test_missing_access_token_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "Bearer"})

    with pytest.raises(OidcLoginError):
        asyncio.run(
            _login(handler).exchange(code="code-1", code_verifier=VERIFIER, redirect_uri=REDIRECT)
        )


def test_confidential_client_secret_comes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADK_TEST_OIDC_SECRET", "server-secret")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content.decode()
        return httpx.Response(200, json={"access_token": "at"})

    login = _login(handler, _config(client_secret_env="ADK_TEST_OIDC_SECRET"))
    asyncio.run(login.exchange(code="code-1", code_verifier=VERIFIER, redirect_uri=REDIRECT))

    assert "client_secret=server-secret" in seen["body"]


def test_missing_client_secret_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ADK_TEST_OIDC_SECRET", raising=False)
    login = _login(_ok, _config(client_secret_env="ADK_TEST_OIDC_SECRET"))

    with pytest.raises(OidcLoginError):
        asyncio.run(login.exchange(code="code-1", code_verifier=VERIFIER, redirect_uri=REDIRECT))


def test_browser_config_rejects_plain_http_outside_loopback() -> None:
    with pytest.raises(ValueError):
        _config(token_endpoint="http://idp.example/token")
