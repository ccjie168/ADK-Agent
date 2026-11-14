"""Constrained outbound probe that turns a connector spec into a health verdict."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ..core import ConnectorSpec

Status = Literal[
    "healthy",
    "unauthorized",
    "not_found",
    "redirect",
    "server_error",
    "unexpected_status",
    "unreachable",
]
Reason = Literal["timeout", "connect_error"]


class ConnectorHealth(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: str
    status: Status
    status_code: int | None
    latency_ms: int
    checked_at: datetime
    reason: Reason | None = None


def _classify(status_code: int) -> Status:
    if 200 <= status_code < 300:
        return "healthy"
    if 300 <= status_code < 400:
        return "redirect"
    if status_code in (401, 403):
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if 500 <= status_code < 600:
        return "server_error"
    return "unexpected_status"


def _health(
    spec: ConnectorSpec,
    status: Status,
    *,
    started: float,
    status_code: int | None = None,
    reason: Reason | None = None,
) -> ConnectorHealth:
    elapsed = time.perf_counter() - started
    return ConnectorHealth(
        connector_id=spec.connector_id,
        status=status,
        status_code=status_code,
        latency_ms=max(0, int(elapsed * 1000)),
        checked_at=datetime.now(timezone.utc),
        reason=reason,
    )


async def check_connector(
    spec: ConnectorSpec, *, client: Any = None, max_timeout: float = 5.0
) -> ConnectorHealth:
    import httpx

    url = spec.base_url.rstrip("/") + spec.path_prefixes[0]
    timeout = min(float(spec.timeout_seconds), max_timeout)
    started = time.perf_counter()
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(follow_redirects=False)
    try:
        async with client.stream("GET", url, timeout=timeout, follow_redirects=False) as response:
            return _health(
                spec,
                _classify(response.status_code),
                started=started,
                status_code=response.status_code,
            )
    except httpx.TimeoutException:
        return _health(spec, "unreachable", started=started, reason="timeout")
    except httpx.HTTPError:
        return _health(spec, "unreachable", started=started, reason="connect_error")
    finally:
        if owns_client:
            await client.aclose()


__all__ = ["ConnectorHealth", "Status", "check_connector"]
