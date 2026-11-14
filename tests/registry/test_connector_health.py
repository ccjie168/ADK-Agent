"""SLICE-089: a constrained probe turns a connector into a health verdict."""

from __future__ import annotations

import asyncio
from datetime import timezone

import httpx
import pytest

from adk_agent.core import ConnectorSpec
from adk_agent.registry import check_connector


def _spec(**overrides) -> ConnectorSpec:
    payload = {
        "connector_id": "crm",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://crm/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "timeout_seconds": 10,
    }
    payload.update(overrides)
    return ConnectorSpec(**payload)


def _check(spec: ConnectorSpec, handler) -> object:
    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
            return await check_connector(spec, client=client)

    return asyncio.run(run())


def test_healthy():
    result = _check(_spec(), lambda request: httpx.Response(200))
    assert result.connector_id == "crm"
    assert result.status == "healthy"
    assert result.status_code == 200
    assert result.reason is None
    assert result.latency_ms >= 0
    assert result.checked_at.utcoffset() == timezone.utc.utcoffset(None)


@pytest.mark.parametrize("status_code", [401, 403])
def test_unauthorized(status_code):
    result = _check(_spec(), lambda request: httpx.Response(status_code))
    assert result.status == "unauthorized"
    assert result.status_code == status_code


def test_not_found():
    result = _check(_spec(), lambda request: httpx.Response(404))
    assert result.status == "not_found"
    assert result.status_code == 404


def test_redirect_not_followed():
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://crm.example.com/elsewhere"})

    result = _check(_spec(), handler)
    assert result.status == "redirect"
    assert result.status_code == 302
    assert calls == ["https://crm.example.com/v1/crm/"]


def test_redirect_not_followed_by_a_following_client():
    calls: list[str] = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://crm.example.com/elsewhere"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            return await check_connector(_spec(), client=client)

    result = asyncio.run(run())
    assert result.status == "redirect"
    assert calls == ["https://crm.example.com/v1/crm/"]


def test_server_error():
    result = _check(_spec(), lambda request: httpx.Response(503))
    assert result.status == "server_error"
    assert result.status_code == 503


def test_unexpected_status():
    result = _check(_spec(), lambda request: httpx.Response(418))
    assert result.status == "unexpected_status"
    assert result.status_code == 418


def test_connect_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    result = _check(_spec(), handler)
    assert result.status == "unreachable"
    assert result.status_code is None
    assert result.reason == "connect_error"


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    result = _check(_spec(), handler)
    assert result.status == "unreachable"
    assert result.status_code is None
    assert result.reason == "timeout"


def test_request_shape():
    seen: dict = {}

    def handler(request):
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200)

    _check(_spec(path_prefixes=["/v1/crm/", "/v2/crm/"]), handler)
    assert seen["method"] == "GET"
    assert seen["url"] == "https://crm.example.com/v1/crm/"
    assert seen["authorization"] is None


class _RecordingClient(httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeouts: list[float] = []

    def stream(self, method, url, **kwargs):
        self.timeouts.append(kwargs["timeout"])
        return super().stream(method, url, **kwargs)


def test_timeout_cap():
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        client = _RecordingClient(transport=transport, follow_redirects=False)
        async with client:
            result = await check_connector(_spec(timeout_seconds=60), client=client)
        return result, client.timeouts

    result, timeouts = asyncio.run(run())
    assert result.status == "healthy"
    assert timeouts == [5.0]
