"""SLICE-095: outbound A2A calls are audited at the HTTP boundary."""

from __future__ import annotations

import asyncio
import re
from datetime import timezone
from typing import Any

import httpx
import pytest

import adk_agent.a2a as a2a_module
from adk_agent.a2a import remote_agent
from adk_agent.a2a_egress import AuditTransport
from adk_agent.audit import ListAuditSink
from adk_agent.audit.hashing import hash_text
from adk_agent.core import AgentRef, Invocation, Principal
from adk_agent.core.context import reset_invocation, set_invocation

CARD = "http://peer.example/.well-known/agent-card.json"
AGENT_REF = AgentRef(id="remote_probe", version="remote", digest=f"sha256:{hash_text(CARD)}")
PEER_ID_ERROR = "peer_id is required when audit is set"


class RaisingAudit:
    async def emit(self, event: Any) -> None:
        raise RuntimeError("audit down")


def _transport(handler: Any, sink: Any, **overrides: Any) -> AuditTransport:
    kwargs = {
        "inner": httpx.MockTransport(handler),
        "audit": sink,
        "tenant": "local",
        "subject": "a2a_consumer",
        "peer_id": "crm",
        "target": "crm/remote_probe",
        "agent_ref": AGENT_REF,
    }
    kwargs.update(overrides)
    return AuditTransport(**kwargs)


def _request(handler: Any, *, method: str = "GET", path: str = "/agent/run", **kwargs: Any):
    async def scenario():
        sink = ListAuditSink()
        transport = _transport(handler, sink)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.request(method, f"http://peer.example{path}", **kwargs)
        return sink, response

    return asyncio.run(scenario())


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="trace-1",
        principal=Principal(tenant="local", subject="a2a_consumer", kind="service"),
        agent_ref=AGENT_REF,
        input="hi",
    )


def _fail(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("boom", request=request)


def _record_remote(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []

    class RecordingRemote:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

    monkeypatch.setattr(a2a_module, "_remote_a2a_agent", lambda: RecordingRemote)
    return built


def test_ok_event():
    sink, response = _request(lambda request: httpx.Response(200))

    assert response.status_code == 200
    [event] = sink.recent(10)
    assert event.action == "a2a.call"
    assert event.status == "ok"
    assert event.egress == "third_party"
    assert event.tenant == "local"
    assert event.principal == Principal(tenant="local", subject="a2a_consumer", kind="service")
    assert event.agent_ref == AGENT_REF
    assert event.target == "crm/remote_probe"
    assert event.latency_ms is not None
    assert event.latency_ms >= 0
    assert event.event_id and event.run_id
    assert event.timestamp.utcoffset() == timezone.utc.utcoffset(None)
    assert re.fullmatch(r"[0-9a-f]{32}", event.trace_id)


def test_server_error_event():
    sink, response = _request(lambda request: httpx.Response(500, text="remote exploded"))

    assert response.status_code == 500
    [event] = sink.recent(10)
    assert event.status == "error"
    assert event.egress == "third_party"


def test_transport_error_event():
    async def scenario():
        sink = ListAuditSink()
        transport = _transport(_fail, sink)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get("http://peer.example/agent/run")
        return sink

    sink = asyncio.run(scenario())
    [event] = sink.recent(10)
    assert event.action == "a2a.call"
    assert event.status == "error"
    assert event.egress == "third_party"


def test_event_shape():
    body = {"payload": "request-body-marker"}
    sink, _ = _request(
        lambda request: httpx.Response(200, json={"result": "response-body-marker"}),
        method="POST",
        path="/agent/run?token=leak",
        json=body,
    )

    [event] = sink.recent(10)
    assert event.egress == "third_party"
    assert event.target == "crm/remote_probe"
    assert event.args_hash == hash_text("POST /agent/run")
    assert event.args_hash != hash_text(f"POST /agent/run {body}")
    assert event.result_hash is None
    serialized = event.model_dump_json()
    assert "request-body-marker" not in serialized
    assert "response-body-marker" not in serialized
    assert "peer.example" not in serialized
    assert "leak" not in serialized


def test_trace_from_invocation():
    token = set_invocation(_invocation())
    try:
        sink, _ = _request(lambda request: httpx.Response(200))
    finally:
        reset_invocation(token)

    assert sink.recent(1)[0].trace_id == "trace-1"


def test_audit_failure_is_swallowed(caplog):
    async def scenario():
        transport = _transport(lambda request: httpx.Response(200), RaisingAudit())
        async with httpx.AsyncClient(transport=transport) as client:
            return await client.get("http://peer.example/agent/run")

    response = asyncio.run(scenario())
    assert response.status_code == 200
    assert any("audit" in record.message.lower() for record in caplog.records)


def test_remote_agent_requires_peer(monkeypatch):
    def unexpected() -> Any:
        raise AssertionError("must fail before building the remote agent")

    monkeypatch.setattr(a2a_module, "_remote_a2a_agent", unexpected)
    with pytest.raises(ValueError) as exc:
        remote_agent("remote_probe", CARD, audit=ListAuditSink())
    assert str(exc.value) == PEER_ID_ERROR


def test_remote_agent_without_audit(monkeypatch):
    built = _record_remote(monkeypatch)

    remote_agent("remote_probe", CARD)
    assert built[-1]["httpx_client"] is None

    remote_agent("remote_probe", CARD, auth_token="secret")
    client = built[-1]["httpx_client"]
    try:
        assert isinstance(client, httpx.AsyncClient)
        assert client.headers["Authorization"] == "Bearer secret"
    finally:
        asyncio.run(client.aclose())


def test_remote_agent_with_audit_installs_transport(monkeypatch):
    built = _record_remote(monkeypatch)
    remote_agent(
        "remote_probe",
        CARD,
        audit=ListAuditSink(),
        peer_id="crm",
        auth_token="secret",
    )

    client = built[-1]["httpx_client"]
    try:
        transport = client._transport
        assert isinstance(transport, AuditTransport)
        assert isinstance(transport._inner, httpx.AsyncHTTPTransport)
        assert transport._target == "crm/remote_probe"
        assert transport._agent_ref == AGENT_REF
        assert client.headers["Authorization"] == "Bearer secret"
    finally:
        asyncio.run(client.aclose())
