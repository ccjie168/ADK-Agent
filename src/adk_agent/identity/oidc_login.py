"""OIDC authorization-code exchange with PKCE for the console."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .oidc import OidcBrowserConfig

_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}\Z")


class OidcLoginError(RuntimeError):
    """The authorization code cannot be exchanged."""


class OidcLogin:
    def __init__(
        self, config: OidcBrowserConfig, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.config = config
        self._client = client
        self._owns_client = client is None

    def public_config(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "client_id": self.config.client_id,
            "authorization_endpoint": self.config.authorization_endpoint,
            "redirect_uri": self.config.redirect_uri,
            "scopes": list(self.config.scopes),
        }

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        if redirect_uri != self.config.redirect_uri:
            raise OidcLoginError("redirect_uri mismatch")
        if not code or not _VERIFIER.fullmatch(code_verifier):
            raise OidcLoginError("invalid code or verifier")

        form: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": code_verifier,
        }
        secret_env = self.config.client_secret_env
        if secret_env is not None:
            secret = os.environ.get(secret_env)
            if not secret:
                raise OidcLoginError("client secret is not configured")
            form["client_secret"] = secret

        try:
            response = await self._http().post(
                self.config.token_endpoint, data=form, headers={"Accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise OidcLoginError("token endpoint unreachable") from exc

        if response.status_code != 200:
            raise OidcLoginError(f"token endpoint returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OidcLoginError("token endpoint returned invalid JSON") from exc
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OidcLoginError("token endpoint returned no access token")

        result: dict[str, Any] = {
            "access_token": access_token,
            "token_type": payload.get("token_type") or "Bearer",
        }
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, int):
            result["expires_in"] = expires_in
        return result

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None


__all__ = ["OidcLogin", "OidcLoginError"]
