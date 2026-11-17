"""SLICE-129: run a sandboxed artifact in a child process."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import time

import pytest

from adk_agent.core import AgentArtifact
from adk_agent.registry import artifact_digest
from adk_agent.registry.packaging import pack_files
from adk_agent.sandbox.agent import (
    SandboxResult,
    agent_sandbox_available,
    set_agent_sandbox_backend,
)
from adk_agent.sandbox.agent_process import AgentSandboxLimits, ProcessAgentSandbox
from adk_agent.sandbox.errors import SandboxCrashed, SandboxTimeout, SandboxViolation

_TEMPLATE = """
import asyncio
import os

from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types


class Fake(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        __BODY__
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


agent = LlmAgent(name="bot", model=Fake(model="fake"), instruction="x")
"""


def _source(body: str) -> str:
    return _TEMPLATE.replace("__BODY__", body)


def _artifact(source: str, *, digest_of: bytes | None = None):
    manifest = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["fake"]},
        "execution_tier": "sandboxed",
    }
    data = pack_files(
        {
            "manifest.json": json.dumps(manifest).encode("utf-8"),
            "agent.py": source.encode("utf-8"),
        }
    )
    digest = artifact_digest(data if digest_of is None else digest_of)
    return AgentArtifact(digest=digest, size=len(data)), data


def _run(artifact, data, text: str = "hi", *, wall: float = 30.0) -> SandboxResult:
    sandbox = ProcessAgentSandbox(AgentSandboxLimits(wall_seconds=wall))
    return asyncio.run(sandbox.run(artifact, data, text))


@pytest.fixture(autouse=True)
def _no_backend():
    set_agent_sandbox_backend(None)
    yield
    set_agent_sandbox_backend(None)


def test_run_returns_final_text():
    artifact, data = _artifact(_source('text = "hello from the worker"'))
    assert _run(artifact, data).text == "hello from the worker"


def test_environment_is_cleared(monkeypatch):
    monkeypatch.setenv("ADK_TEST_SECRET", "leak-me")
    artifact, data = _artifact(_source('text = "env=" + repr(sorted(os.environ))'))

    result = _run(artifact, data)

    assert "leak-me" not in result.text
    keys = ast.literal_eval(result.text.removeprefix("env="))
    allowed = {"SYSTEMROOT", "TEMP", "TMP"} if os.name == "nt" else set()
    assert set(keys) <= allowed


def test_network_access_is_denied():
    artifact, data = _artifact(
        _source(
            "import socket\n"
            '        socket.create_connection(("127.0.0.1", 9), timeout=1)\n'
            '        text = "connected"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


def test_wall_clock_timeout():
    artifact, data = _artifact(_source("await asyncio.sleep(30)\n        text = 'late'"))

    started = time.monotonic()
    with pytest.raises(SandboxTimeout):
        _run(artifact, data, wall=1.5)

    assert time.monotonic() - started < 10


def test_load_failure_is_a_crash():
    artifact, data = _artifact('raise RuntimeError("boom")\n')

    with pytest.raises(SandboxCrashed):
        _run(artifact, data)


def test_digest_mismatch_is_rejected():
    artifact, data = _artifact(_source('text = "hi"'), digest_of=b"other bytes")

    with pytest.raises(SandboxCrashed):
        _run(artifact, data)


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT is POSIX only")
def test_limits_are_reported():
    artifact, data = _artifact(_source('text = "hi"'))

    result = _run(artifact, data)

    assert result.limits == {
        "cpu_seconds": 10,
        "memory_mb": 1024,
        "open_files": 256,
        "file_bytes": 8 * 1024 * 1024,
    }


def test_artifact_stdout_is_redirected():
    artifact, data = _artifact(_source('print("noise from the artifact")\n        text = "clean"'))

    assert _run(artifact, data).text == "clean"


def test_backend_must_implement_the_protocol():
    with pytest.raises(TypeError):
        set_agent_sandbox_backend(object())

    class Stub:
        async def run(self, artifact, data, input_text):
            return SandboxResult(text="stub")

    set_agent_sandbox_backend(Stub())
    assert agent_sandbox_available() is True
