"""Client for a separately deployed tool gateway."""

from __future__ import annotations

from typing import Any

from ..core import (
    Invocation,
    PolicyEngine,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
    ToolResponse,
)
from .gateway import ToolDenied


class ToolGatewayError(RuntimeError):
    """The remote tool gateway failed or the call could not be serialized."""


def _grants(policy: PolicyEngine) -> list[ToolGrant]:
    grants = getattr(policy, "grants", None)
    if not isinstance(grants, list):
        raise ToolGatewayError("policy engine cannot be serialized; pass a GrantPolicyEngine")
    return grants


class HttpToolGateway:
    """Call the tool gateway over HTTP. Implements the ToolGateway port."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        client: Any = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    def _http(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def invoke(
        self,
        invocation: Invocation,
        request: ToolRequest,
        policy: PolicyEngine,
    ) -> ToolResponse:
        payload = ToolGatewayRequest(
            invocation=invocation, request=request, grants=_grants(policy)
        ).model_dump(mode="json")
        headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else None
        response = await self._http().post(
            f"{self.base_url}/v1/invoke", json=payload, headers=headers
        )
        if response.status_code == 403:
            raise ToolDenied("tool gateway denied the call")
        if response.status_code != 200:
            raise ToolGatewayError(f"tool gateway returned status {response.status_code}")
        return ToolResponse.model_validate(response.json())

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["HttpToolGateway", "ToolGatewayError"]
