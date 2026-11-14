"""HTTP client for connector registration (ADR-0013)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..core import (
    ConnectorConflict,
    ConnectorForbidden,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStoreError,
    ConnectorStoreUnavailable,
)


def _raise_for_status(response: Any) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    message = f"connector service returned status {status}"
    if status in (401, 403):
        raise ConnectorForbidden(message)
    if status == 409:
        raise ConnectorConflict(message)
    if status == 404:
        raise ConnectorNotFound(message)
    if status == 400:
        raise ConnectorStoreError(message)
    raise ConnectorStoreUnavailable(message)


class HttpConnectorStore:
    """Speak the connector control-plane contract. Implements the ConnectorStore port.

    The lazily built httpx client belongs to the event loop of its first call.
    Close it in that loop, or create a new instance per loop.
    """

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

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    async def add(self, spec: ConnectorSpec) -> ConnectorSpec:
        import httpx

        try:
            response = await self._http().post(
                f"{self.base_url}/v1/connectors",
                json=spec.model_dump(mode="json"),
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ConnectorStoreUnavailable("connector service unreachable") from exc
        _raise_for_status(response)
        return ConnectorSpec.model_validate(response.json())

    async def get(self, connector_id: str) -> ConnectorSpec | None:
        import httpx

        path = "/v1/connectors/{}".format(quote(connector_id, safe=""))
        try:
            response = await self._http().get(f"{self.base_url}{path}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ConnectorStoreUnavailable("connector service unreachable") from exc
        if response.status_code == 404:
            return None
        _raise_for_status(response)
        return ConnectorSpec.model_validate(response.json())

    async def list(self, tenant: str) -> list[ConnectorSpec]:
        import httpx

        try:
            response = await self._http().get(
                f"{self.base_url}/v1/connectors",
                params={"tenant": tenant},
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise ConnectorStoreUnavailable("connector service unreachable") from exc
        _raise_for_status(response)
        return [ConnectorSpec.model_validate(item) for item in response.json()["connectors"]]

    async def disable(self, connector_id: str, *, by: str) -> ConnectorSpec:
        import httpx

        path = "/v1/connectors/{}/disable".format(quote(connector_id, safe=""))
        try:
            response = await self._http().post(f"{self.base_url}{path}", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ConnectorStoreUnavailable("connector service unreachable") from exc
        _raise_for_status(response)
        return ConnectorSpec.model_validate(response.json())

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["HttpConnectorStore"]
