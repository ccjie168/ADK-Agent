"""HTTP client for the registry control plane (ADR-0009)."""

from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import quote

from ..core import AgentArtifact, AgentRef, PublishedAgent
from ..core.artifact import MEDIA_TYPE
from .file import RegistryConflict, RegistryError


class RegistryServiceUnavailable(RegistryError):
    """The registry service could not be reached or answered with 5xx."""


class RegistryForbidden(RegistryError):
    """The registry service rejected the caller's credentials."""


class RegistryRejected(RegistryError):
    """The registry service rejected the request content."""


def _raise_for_status(response: Any, *, conflict: bool = False) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    message = f"registry service returned status {status}"
    if status in (401, 403):
        raise RegistryForbidden(message)
    if status == 409:
        raise RegistryConflict(message) if conflict else RegistryRejected(message)
    if status in (400, 413, 415):
        raise RegistryRejected(message)
    raise RegistryServiceUnavailable(message)


class HttpAgentRegistry:
    """Speak the registry control-plane contract. Implements the AgentRegistry port."""

    def __init__(
        self,
        base_url: str,
        *,
        auth_token: str | None = None,
        client: Any = None,
        timeout: float = 10.0,
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

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        if content_type is not None:
            headers["Content-Type"] = content_type
        return headers

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        import httpx

        path = "/v1/agents/{}/{}/{}".format(
            quote(tenant, safe=""), quote(ref.id, safe=""), quote(ref.version, safe="")
        )
        try:
            response = await self._http().get(f"{self.base_url}{path}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise RegistryServiceUnavailable("registry service unreachable") from exc
        if response.status_code == 404:
            return None
        _raise_for_status(response)
        return PublishedAgent.model_validate(response.json())

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        import httpx

        try:
            response = await self._http().post(
                f"{self.base_url}/v1/agents",
                json=agent.model_dump(mode="json"),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise RegistryServiceUnavailable("registry service unreachable") from exc
        _raise_for_status(response, conflict=True)
        return PublishedAgent.model_validate(response.json())

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]:
        import httpx

        try:
            response = await self._http().get(
                f"{self.base_url}/v1/agents",
                params={"tenant": tenant},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise RegistryServiceUnavailable("registry service unreachable") from exc
        _raise_for_status(response)
        return [PublishedAgent.model_validate(item) for item in response.json()["agents"]]

    async def tenants(self) -> builtins.list[str]:
        import httpx

        try:
            response = await self._http().get(
                f"{self.base_url}/v1/tenants", headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise RegistryServiceUnavailable("registry service unreachable") from exc
        _raise_for_status(response)
        return builtins.list(response.json()["tenants"])

    async def upload_artifact(self, artifact: AgentArtifact, data: bytes) -> None:
        import httpx

        try:
            response = await self._http().put(
                f"{self.base_url}/v1/artifacts/{artifact.digest}",
                content=data,
                headers=self._headers(content_type=MEDIA_TYPE),
            )
        except httpx.HTTPError as exc:
            raise RegistryServiceUnavailable("registry service unreachable") from exc
        _raise_for_status(response)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "HttpAgentRegistry",
    "RegistryForbidden",
    "RegistryRejected",
    "RegistryServiceUnavailable",
]
