"""SLICE-031: A2A provider and consumer adapters."""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncGenerator

import pytest
from google.adk.agents import LlmAgent
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from starlette.testclient import TestClient

import adk_agent.a2a as a2a_module
from adk_agent.a2a import A2aUnavailable, build_a2a_app, remote_agent, serve_a2a

_HAS_A2A = importlib.util.find_spec("a2a") is not None
needs_a2a = pytest.mark.skipif(not _HAS_A2A, reason="a2a-sdk is not installed")


class EchoLlm(BaseLlm):
    model: str = "echo"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text="hello from a2a")])
        )


def _agent() -> LlmAgent:
    return LlmAgent(name="a2a_probe", model=EchoLlm(), instruction="x")


def _missing_import(name: str) -> None:
    raise ImportError(name)


def test_network_bind_requires_token():
    with pytest.raises(ValueError):
        serve_a2a(object(), host="0.0.0.0", auth_token=None)


def test_missing_extra_has_install_hint(monkeypatch):
    monkeypatch.setattr(a2a_module, "_import_module", _missing_import)
    with pytest.raises(A2aUnavailable) as exc:
        build_a2a_app(object())
    assert "a2a-sdk" in str(exc.value)


def test_missing_extra_blocks_consumer(monkeypatch):
    monkeypatch.setattr(a2a_module, "_import_module", _missing_import)
    with pytest.raises(A2aUnavailable):
        remote_agent("probe", "http://127.0.0.1:1/.well-known/agent-card.json")


@needs_a2a
def test_agent_card_requires_token():
    with TestClient(build_a2a_app(_agent(), auth_token="secret")) as client:
        response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 401


@needs_a2a
def test_agent_card_with_token():
    with TestClient(build_a2a_app(_agent(), auth_token="secret")) as client:
        response = client.get(
            "/.well-known/agent-card.json",
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
    assert response.json()["name"] == "a2a_probe"


@needs_a2a
def test_rpc_requires_token():
    with TestClient(build_a2a_app(_agent(), auth_token="secret")) as client:
        response = client.post("/", json={"jsonrpc": "2.0", "method": "message/send"})
    assert response.status_code == 401


@needs_a2a
def test_remote_agent_constructs():
    remote = remote_agent(
        "remote_probe",
        "http://127.0.0.1:1/.well-known/agent-card.json",
        auth_token="secret",
    )
    assert remote.name == "remote_probe"
    assert type(remote).__name__ == "RemoteA2aAgent"
