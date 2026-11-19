"""SLICE-176: release a write-tool idempotency claim on execution failure."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from adk_agent.core import (
    AgentRef,
    Invocation,
    Principal,
    ToolExecutionRecord,
    ToolGatewayRequest,
    ToolGrant,
    ToolRequest,
)
from adk_agent.tools import (
    FileToolIdempotencyStore,
    FunctionRegistry,
    FunctionToolGateway,
    ToolSpec,
)
from adk_agent.tools.service import build_tool_gateway_app

AUTH = {"Authorization": "Bearer secret"}
_NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def _record() -> ToolExecutionRecord:
    return ToolExecutionRecord(
        tenant="t1",
        tool_id="write.po",
        idempotency_key="k1",
        status="claimed",
        created_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )


def test_release_removes_record(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    asyncio.run(store.claim(_record()))
    asyncio.run(store.release("t1", "write.po", "k1"))
    assert asyncio.run(store.get("t1", "write.po", "k1")) is None


def test_release_missing_is_noop(tmp_path):
    store = FileToolIdempotencyStore(tmp_path)
    asyncio.run(store.release("t1", "write.po", "missing"))


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        input="hi",
    )


def _resolver(grants):
    async def resolve(_invocation):
        return grants

    return resolve


def _body(tool_id: str, key: str, args: dict) -> dict:
    request = ToolGatewayRequest(
        invocation=_invocation(),
        request=ToolRequest(tool_id=tool_id, args=args, idempotency_key=key),
        grants=[ToolGrant(tool_id=tool_id)],
    )
    return request.model_dump(mode="json")


def test_execution_failure_releases_claim(tmp_path):
    state = {"fail": True}

    def write_po(amount: int) -> dict:
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("boom")
        return {"ok": True, "amount": amount}

    registry = FunctionRegistry(
        [ToolSpec(tool_id="write.po", handler=write_po, data_classes=("internal",), write=True)]
    )
    gateway = FunctionToolGateway(registry, idempotency=FileToolIdempotencyStore(tmp_path))
    app = build_tool_gateway_app(
        gateway,
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="write.po")]),
    )
    with TestClient(app) as client:
        first = client.post("/v1/invoke", json=_body("write.po", "k1", {"amount": 5}), headers=AUTH)
        second = client.post(
            "/v1/invoke", json=_body("write.po", "k1", {"amount": 5}), headers=AUTH
        )
    assert first.status_code == 502
    assert second.status_code == 200


def test_serialization_failure_keeps_unknown(tmp_path):
    class NotSerializable:
        pass

    def write_bad() -> object:
        return NotSerializable()

    store = FileToolIdempotencyStore(tmp_path)
    registry = FunctionRegistry(
        [ToolSpec(tool_id="write.po", handler=write_bad, data_classes=("internal",), write=True)]
    )
    gateway = FunctionToolGateway(registry, idempotency=store)
    app = build_tool_gateway_app(
        gateway,
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="write.po")]),
    )
    with TestClient(app) as client:
        first = client.post("/v1/invoke", json=_body("write.po", "k1", {}), headers=AUTH)
        second = client.post("/v1/invoke", json=_body("write.po", "k1", {}), headers=AUTH)
    assert first.status_code == 502
    assert second.status_code == 502
    record = asyncio.run(store.get("t1", "write.po", "k1"))
    assert record is not None
    assert record.status == "unknown"
