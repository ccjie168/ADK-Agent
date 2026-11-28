"""HTTP connector execution under an enforced egress policy (ADR-0013)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

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

    def __init__(self, *, trust_env: bool = True) -> None:
        self.trust_env = trust_env

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout: float,
        max_bytes: int,
        body: bytes | None = None,
    ) -> ConnectorResponse:
        import httpx

        async with (
            httpx.AsyncClient(follow_redirects=False, trust_env=self.trust_env) as client,
            client.stream(method, url, headers=headers, content=body, timeout=timeout) as response,
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
        call: dict[str, Any] = {
            "method": verb,
            "url": url,
            "headers": headers,
            "timeout": spec.timeout_seconds,
            "max_bytes": spec.max_response_bytes,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            call["body"] = json.dumps(json_body).encode("utf-8")
        try:
            response = await adapter.request(**call)
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


_PATH_PARAM = re.compile(r"\{([^}]+)\}")


def _fill_path(template: str, params: dict[str, Any]) -> str:
    """Substitute ``{name}`` placeholders, rejecting anything path-like."""
    out = template
    for name in _PATH_PARAM.findall(template):
        if name not in params:
            raise ConnectorDenied("path_param_missing")
        value = params[name]
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ConnectorDenied("path_param_invalid")
        text = str(value)
        if "/" in text or "\\" in text or ".." in text:
            raise ConnectorDenied("path_param_invalid")
        out = out.replace("{" + name + "}", quote(text, safe=""))
    return out


def _operation_handler(spec: ConnectorSpec, operation: Any, secrets: SecretProvider, adapter: Any):
    handler = _handler(spec, secrets, adapter)

    async def call(
        query: dict[str, str] | None = None,
        path_params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> dict[str, Any]:
        path = _fill_path(operation.path, path_params or {})
        return await handler(path, operation.method, query, json_body)

    return call


def build_connector_tools(
    specs: list[ConnectorSpec],
    *,
    secrets: SecretProvider,
    adapter: Any = None,
) -> list[ToolSpec]:
    """Turn enabled connectors into third-party tools for the gateway.

    A connector with imported ``operations`` contributes one tool per operation,
    named by the operation's tool id; any other connector keeps the single
    connector-level tool.
    """
    http = adapter if adapter is not None else HttpxAdapter()
    tools: list[ToolSpec] = []
    for spec in specs:
        if not spec.enabled:
            continue
        if spec.operations:
            for operation in spec.operations:
                risk, classes = spec.operation_governance(operation)
                tools.append(
                    ToolSpec(
                        tool_id=operation.tool_id,
                        handler=_operation_handler(spec, operation, secrets, http),
                        data_classes=tuple(classes),
                        requires_approval=risk in ("L3", "L4"),
                        egress="third_party",
                        write=operation.write,
                        risk_level=risk,
                        delegation=spec.delegation,
                    )
                )
            continue
        tools.append(
            ToolSpec(
                tool_id=spec.connector_id,
                handler=_handler(spec, secrets, http),
                data_classes=tuple(spec.data_classes),
                egress="third_party",
                risk_level=spec.risk_level,
                delegation=spec.delegation,
            )
        )
    return tools


__all__ = ["ConnectorDenied", "ConnectorResponse", "HttpxAdapter", "build_connector_tools"]
