"""SLICE-174: gateway idempotent replay and serialization-failure semantics."""

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


def _body(tool_id: str, key: str | None = None, args: dict | None = None) -> dict:
    request = ToolGatewayRequest(
        invocation=_invocation(),
        request=ToolRequest(tool_id=tool_id, args=args or {}, idempotency_key=key),
        grants=[ToolGrant(tool_id=tool_id)],
    )
    return request.model_dump(mode="json")


def _app(handler, *, write: bool, store: FileToolIdempotencyStore | None) -> TestClient:
    registry = FunctionRegistry(
        [ToolSpec(tool_id="write.po", handler=handler, data_classes=("internal",), write=write)]
    )
    gateway = FunctionToolGateway(registry, idempotency=store)
    app = build_tool_gateway_app(
        gateway,
        auth_token="secret",
        grant_resolver=_resolver([ToolGrant(tool_id="write.po")]),
    )
    return TestClient(app)


def test_duplicate_key_replays_result(tmp_path):
    calls: list[int] = []

    def write_po(amount: int) -> dict:
        calls.append(amount)
        return {"ok": True, "amount": amount}

    with _app(write_po, write=True, store=FileToolIdempotencyStore(tmp_path)) as client:
        first = client.post(
            "/v1/invoke", json=_body("write.po", key="k1", args={"amount": 5}), headers=AUTH
        )
        second = client.post(
            "/v1/invoke", json=_body("write.po", key="k1", args={"amount": 5}), headers=AUTH
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert calls == [5]


def test_serialization_failure_records_unknown(tmp_path):
    calls: list[int] = []

    class NotSerializable:
        pass

    def write_bad() -> object:
        calls.append(1)
        return NotSerializable()

    store = FileToolIdempotencyStore(tmp_path)
    with _app(write_bad, write=True, store=store) as client:
        first = client.post("/v1/invoke", json=_body("write.po", key="k1"), headers=AUTH)
        second = client.post("/v1/invoke", json=_body("write.po", key="k1"), headers=AUTH)

    assert first.status_code == 502
    assert first.json() == {"error": "tool_result_unknown"}
    assert second.status_code == 502
    assert calls == [1]
    record = asyncio.run(store.get("t1", "write.po", "k1"))
    assert record is not None
    assert record.status == "unknown"


def test_gateway_in_progress_409(tmp_path):
    def write_po() -> dict:
        return {"ok": True}

    store = FileToolIdempotencyStore(tmp_path)
    asyncio.run(
        store.claim(
            ToolExecutionRecord(
                tenant="t1",
                tool_id="write.po",
                idempotency_key="k1",
                claim_id="other",
                status="claimed",
                created_at=_NOW,
                expires_at=_NOW + timedelta(hours=24),
            )
        )
    )
    with _app(write_po, write=True, store=store) as client:
        response = client.post("/v1/invoke", json=_body("write.po", key="k1"), headers=AUTH)
    assert response.status_code == 409
    assert response.json() == {"error": "idempotency_in_progress"}


def test_read_tool_unaffected(tmp_path):
    def read(amount: int) -> int:
        return amount * 2

    with _app(read, write=False, store=FileToolIdempotencyStore(tmp_path)) as client:
        response = client.post(
            "/v1/invoke", json=_body("write.po", args={"amount": 5}), headers=AUTH
        )
    assert response.status_code == 200


def test_no_store_executes_once(tmp_path):
    calls: list[int] = []

    def write_po(amount: int) -> dict:
        calls.append(amount)
        return {"ok": True}

    with _app(write_po, write=True, store=None) as client:
        first = client.post(
            "/v1/invoke", json=_body("write.po", key="k1", args={"amount": 5}), headers=AUTH
        )
        second = client.post(
            "/v1/invoke", json=_body("write.po", key="k1", args={"amount": 5}), headers=AUTH
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [5, 5]
