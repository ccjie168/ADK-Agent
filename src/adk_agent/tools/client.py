"""Client for the tool gateway (ADR-0024 tool mediation)."""

from __future__ import annotations

from typing import Any

import httpx

from ..core import Invocation, ToolGatewayRequest, ToolGrant, ToolRequest, ToolResponse


class ToolGatewayError(RuntimeError):
    """The tool gateway could not serve a call."""


class ToolDenied(ToolGatewayError):
    """The gateway refused the call (grant, approval, principal)."""


class ToolGatewayClient:
    """Invoke tools through the HTTP tool gateway."""

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = client

    async def invoke(
        self,
        invocation: Invocation,
        tool_id: str,
        args: dict[str, Any],
        *,
        grants: list[ToolGrant] | None = None,
    ) -> Any:
        body = ToolGatewayRequest(
            invocation=invocation,
            request=ToolRequest(tool_id=tool_id, args=args),
            grants=list(grants or ()),
        ).model_dump(mode="json")
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self.url}/v1/invoke", json=body, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.url}/v1/invoke", json=body, headers=headers
                    )
        except httpx.HTTPError as exc:
            raise ToolGatewayError("tool gateway is unreachable") from exc
        if response.status_code == 403:
            raise ToolDenied("tool gateway denied the call")
        if response.status_code >= 500:
            raise ToolGatewayError("tool gateway failed")
        if response.status_code != 200:
            raise ToolGatewayError(f"tool gateway returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolGatewayError("tool gateway returned invalid JSON") from exc
        try:
            return ToolResponse.model_validate(payload).output
        except Exception as exc:  # noqa: BLE001
            raise ToolGatewayError("tool gateway returned an invalid response") from exc


__all__ = ["ToolDenied", "ToolGatewayClient", "ToolGatewayError"]
