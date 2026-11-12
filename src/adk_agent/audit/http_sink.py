"""Client for a separately deployed audit pipeline."""

from __future__ import annotations

from typing import Any

from ..core import AuditEvent


class AuditSinkUnavailable(RuntimeError):
    """The audit pipeline rejected the event or could not be reached."""


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


__all__ = ["AuditSinkUnavailable", "HttpAuditSink"]
