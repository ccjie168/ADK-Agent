"""SLICE-048: A2A runs write audit and enforce quota."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import AsyncGenerator

import pytest
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from starlette.testclient import TestClient

from adk_agent.a2a import build_a2a_app
from adk_agent.audit import ListAuditSink
from adk_agent.audit.hashing import hash_text
from adk_agent.core import QuotaConfig, QuotaPolicy
from adk_agent.runtime.quota import InMemoryQuotaManager

_HAS_A2A = importlib.util.find_spec("a2a") is not None
needs_a2a = pytest.mark.skipif(not _HAS_A2A, reason="a2a-sdk is not installed")

AUTH = {"Authorization": "Bearer secret"}
TRACE = "4bf9" * 8
PARENT = "00f0" * 4


class EchoLlm(BaseLlm):
    model: str = "echo"
    calls: int = 0

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.calls += 1
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="hello from a2a")])
        )


def _agent(llm: EchoLlm) -> LlmAgent:
    return LlmAgent(name="a2a_probe", model=llm, instruction="x")


def _payload(text: str = "hi") -> dict:
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "parts": [{"kind": "text", "text": text}],
                "messageId": "m1",
            }
        },
    }


def _post(client: TestClient, headers: dict | None = None):
    return client.post("/", json=_payload(), headers={**AUTH, **(headers or {})})


@needs_a2a
def test_a2a_audits_run():
    sink = ListAuditSink()
    with TestClient(
        build_a2a_app(_agent(EchoLlm()), auth_token="secret", audit=sink),
        raise_server_exceptions=False,
    ) as client:
        response = _post(client)

    assert response.status_code == 200
    assert "result" in response.json()

    [event] = sink.recent(10)
    assert event.action == "agent.run"
    assert event.status == "ok"
    assert event.tenant == "local"
    assert event.principal.subject == "a2a_user"
    assert event.target == "a2a_probe@dev"
    assert event.args_hash == hash_text("hi")
    assert event.result_hash == hash_text("hello from a2a")
    assert event.error_code is None


@needs_a2a
def test_a2a_quota_denies():
    llm = EchoLlm()
    sink = ListAuditSink()
    quota = InMemoryQuotaManager()
    config = QuotaConfig(tenants={"local": QuotaPolicy(max_runs=1, window_seconds=60)})
    app = build_a2a_app(
        _agent(llm),
        auth_token="secret",
        audit=sink,
        quota=quota,
        quota_config=config,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        first = _post(client)
        _post(client)

    assert "result" in first.json()
    assert llm.calls == 1
    statuses = [event.status for event in sink.recent(10)]
    assert statuses == ["ok", "denied"]
    assert sink.recent(1)[0].error_code == "quota_exceeded"


@needs_a2a
def test_a2a_uses_traceparent():
    sink = ListAuditSink()
    with TestClient(
        build_a2a_app(_agent(EchoLlm()), auth_token="secret", audit=sink),
        raise_server_exceptions=False,
    ) as client:
        _post(client, {"traceparent": f"00-{TRACE}-{PARENT}-01"})

    assert sink.recent(1)[0].trace_id == TRACE


@needs_a2a
def test_a2a_generates_trace_id():
    sink = ListAuditSink()
    with TestClient(
        build_a2a_app(_agent(EchoLlm()), auth_token="secret", audit=sink),
        raise_server_exceptions=False,
    ) as client:
        _post(client)

    assert re.fullmatch(r"[0-9a-f]{32}", sink.recent(1)[0].trace_id)
