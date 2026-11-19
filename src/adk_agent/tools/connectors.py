"""HTTP connector execution under an enforced egress policy (ADR-0013)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from ..core import ConnectorSpec, SecretProvider
from ..secretstore import SecretNotFound
from .gateway import ToolDenied
from .registry import ToolSpec


class ConnectorDenied(ToolDenied):
    """A connector call was denied by the egress policy."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class ConnectorResponse:
    status: int
    content_type: str
    body: bytes


class HttpxAdapter:
    """Stream the response and stop once ``max_bytes`` is exceeded."""

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int,
    ) -> ConnectorResponse:
        import httpx

        async with (
            httpx.AsyncClient(follow_redirects=False) as client,
            client.stream(method, url, headers=headers, timeout=timeout) as response,
        ):
            total = 0
            chunks: list[bytes] = []
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ConnectorDenied("response_too_large")
                chunks.append(chunk)
            return ConnectorResponse(
                status=response.status_code,
                content_type=response.headers.get("content-type", ""),
                body=b"".join(chunks),
            )


def _path_allowed(path: str, prefixes: list[str]) -> bool:
    if not path.startswith("/") or "\\" in path or ".." in path.split("/"):
        return False
    if "://" in path:
        return False
    return any(path.startswith(prefix) for prefix in prefixes)


def _handler(spec: ConnectorSpec, secrets: SecretProvider, adapter: Any):
    base = urlsplit(spec.base_url)

    async def call(
        path: str,
        method: str = "GET",
        query: dict[str, str] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        verb = str(method).upper()
        if verb not in spec.methods:
            raise ConnectorDenied("method_denied")
        if not isinstance(path, str) or not _path_allowed(path, spec.path_prefixes):
            raise ConnectorDenied("path_denied")
        url = spec.base_url.rstrip("/") + path
        if query:
            url += "?" + urlencode(query)
        target = urlsplit(url)
        if target.scheme != base.scheme or target.hostname != base.hostname:
            raise ConnectorDenied("egress_denied")

        headers: dict[str, str] = {}
        if spec.auth_ref is not None:
            try:
                token = await secrets.resolve(spec.auth_ref)
            except SecretNotFound:
                raise ConnectorDenied("secret_unavailable") from None
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = await adapter.request(
                method=verb,
                url=url,
                headers=headers,
                timeout=spec.timeout_seconds,
                max_bytes=spec.max_response_bytes,
            )
        except ConnectorDenied:
            raise
        except Exception:  # noqa: BLE001
            raise ConnectorDenied("connector_unavailable") from None

        if 300 <= response.status < 400:
            raise ConnectorDenied("egress_denied")
        if len(response.body) > spec.max_response_bytes:
            raise ConnectorDenied("response_too_large")
        if "application/json" in response.content_type:
            body: Any = json.loads(response.body or b"null")
        else:
            body = response.body.decode("utf-8", "replace")
        return {"status": response.status, "body": body}

    return call


def build_connector_tools(
    specs: list[ConnectorSpec],
    *,
    secrets: SecretProvider,
    adapter: Any = None,
) -> list[ToolSpec]:
    """Turn enabled connectors into third-party tools for the gateway."""
    http = adapter if adapter is not None else HttpxAdapter()
    return [
        ToolSpec(
            tool_id=spec.connector_id,
            handler=_handler(spec, secrets, http),
            data_classes=tuple(spec.data_classes),
            egress="third_party",
            risk_level=spec.risk_level,
            delegation=spec.delegation,
        )
        for spec in specs
        if spec.enabled
    ]


__all__ = ["ConnectorDenied", "ConnectorResponse", "HttpxAdapter", "build_connector_tools"]
