"""Client for a separately deployed audit pipeline."""

from __future__ import annotations

from typing import Any

from ..core import AuditEvent


class AuditSinkUnavailable(RuntimeError):
    """The audit pipeline rejected the event or could not be reached."""


class AuditQueryUnavailable(RuntimeError):
    """The audit service could not answer a query."""


class HttpAuditSink:
    """Send events to the audit service. Implements the AuditSink port."""

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

    async def emit(self, event: AuditEvent) -> None:
        headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else None
        response = await self._http().post(
            f"{self.base_url}/v1/events",
            json=event.model_dump(mode="json"),
            headers=headers,
        )
        if response.status_code != 202:
            raise AuditSinkUnavailable(f"audit pipeline returned status {response.status_code}")

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class HttpAuditQuery:
    """Read events from a separately deployed audit service."""

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

    async def events(self, *, tenant: str | None, limit: int) -> list[AuditEvent]:
        import httpx

        headers = {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else None
        params: dict[str, Any] = {"limit": limit, "order": "desc"}
        if tenant is not None:
            params["tenant"] = tenant
        try:
            response = await self._http().get(
                f"{self.base_url}/v1/events",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise AuditQueryUnavailable("audit service unreachable") from exc
        if response.status_code != 200:
            raise AuditQueryUnavailable(f"audit service returned status {response.status_code}")
        payload = response.json()
        return [AuditEvent.model_validate(item) for item in payload["events"]]

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "AuditQueryUnavailable",
    "AuditSinkUnavailable",
    "HttpAuditQuery",
    "HttpAuditSink",
]
