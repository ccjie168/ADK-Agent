"""Client for a separately deployed model gateway."""

from __future__ import annotations

from typing import Any

from ..core import Invocation, ModelGatewayRequest, ModelPolicy, ModelRequest, ModelResponse
from .gateway import ModelDenied


class ModelGatewayError(RuntimeError):
    """The remote model gateway failed or rejected the call."""


class HttpModelGateway:
    """Call the model gateway over HTTP. Implements the ModelGateway port."""

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

    async def complete(
        self,
        invocation: Invocation,
        request: ModelRequest,
        policy: ModelPolicy,
    ) -> ModelResponse:
        payload = ModelGatewayRequest(
            invocation=invocation, request=request, policy=policy
        ).model_dump(mode="json")
        headers = {"X-Trace-Id": invocation.trace_id}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        response = await self._http().post(
            f"{self.base_url}/v1/complete", json=payload, headers=headers
        )
        if response.status_code == 403:
            raise ModelDenied("model gateway denied the request")
        if response.status_code != 200:
            raise ModelGatewayError(f"model gateway returned status {response.status_code}")
        return ModelResponse.model_validate(response.json())

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["HttpModelGateway", "ModelGatewayError"]
