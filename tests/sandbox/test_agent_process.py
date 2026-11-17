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
        _run(artifact, data, wall=6.0)

    assert time.monotonic() - started < 20


def test_a_second_run_works_after_a_timeout():
    slow, slow_data = _artifact(_source("await asyncio.sleep(30)\n        text = 'late'"))
    fast, fast_data = _artifact(_source('text = "recovered"'))

    with pytest.raises(SandboxTimeout):
        _run(slow, slow_data, wall=6.0)

    assert _run(fast, fast_data).text == "recovered"


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


def test_udp_egress_is_denied():
    artifact, data = _artifact(
        _source(
            "import socket\n"
            "        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
            '        sock.sendto(b"probe", ("example.com", 9))\n'
            '        text = "sent"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


def test_process_creation_is_denied():
    artifact, data = _artifact(
        _source(
            "import subprocess\n"
            "        import sys\n"
            '        subprocess.run([sys.executable, "-c", "pass"])\n'
            '        text = "spawned"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


def test_artifact_cannot_forge_a_violation():
    artifact, data = _artifact(
        _source(
            "from adk_agent.sandbox.errors import SandboxViolation\n"
            '        raise SandboxViolation("forged")\n'
            '        text = "unreachable"'
        )
    )

    with pytest.raises(SandboxCrashed):
        _run(artifact, data)


def test_runs_in_a_removed_temp_directory():
    artifact, data = _artifact(_source("text = os.getcwd()"))

    result = _run(artifact, data)

    assert result.text != os.getcwd()
    assert not os.path.exists(result.text)


def test_clear_env_removes_secrets(monkeypatch):
    from types import SimpleNamespace

    from adk_agent.sandbox import agent_worker

    environ = {"ADK_TEST_LEAK": "leak-me"}
    if os.name == "nt":
        environ.update({"SYSTEMROOT": "root", "TEMP": "temp"})
    monkeypatch.setattr(agent_worker, "os", SimpleNamespace(name=os.name, environ=environ))

    agent_worker._clear_env()

    allowed = {"SYSTEMROOT", "TEMP"} if os.name == "nt" else set()
    assert set(environ) == allowed


def test_backend_must_implement_the_protocol():
    from types import SimpleNamespace

    for bad in (object(), SimpleNamespace(run=1), SimpleNamespace(run=lambda *a: None)):
        with pytest.raises(TypeError):
            set_agent_sandbox_backend(bad)

    class Stub:
        async def run(self, artifact, data, input_text):
            return SandboxResult(text="stub")

    set_agent_sandbox_backend(Stub())
    assert agent_sandbox_available() is True


def test_raw_socket_module_is_denied():
    artifact, data = _artifact(
        _source(
            "import _socket\n"
            "        _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)\n"
            '        text = "opened"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


@pytest.mark.skipif(not hasattr(__import__("socket"), "AF_UNIX"), reason="AF_UNIX is absent")
def test_unix_sockets_are_denied():
    artifact, data = _artifact(
        _source(
            "import socket\n"
            "        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "        sock.connect('/tmp/adk-sandbox-probe.sock')\n"
            '        text = "connected"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


@pytest.mark.skipif(os.name != "posix", reason="frame fd layout is POSIX specific")
def test_malformed_frame_does_not_hang():
    artifact, data = _artifact(
        _source(
            "import struct\n"
            "        os.write(3, struct.pack('>I', 3) + b'{{{')\n"
            "        await asyncio.sleep(60)\n"
            '        text = "never"'
        )
    )

    started = time.monotonic()
    with pytest.raises(SandboxCrashed):
        _run(artifact, data, wall=6.0)

    assert time.monotonic() - started < 15


def test_invalid_limit_values_are_rejected():
    from adk_agent.sandbox.agent_process import _applied_limits

    with pytest.raises(SandboxCrashed):
        _applied_limits({"applied": 5})
    with pytest.raises(SandboxCrashed):
        _applied_limits({"applied": {"cpu_seconds": "many"}})
    assert _applied_limits({"applied": {"cpu_seconds": 10}}) == {"cpu_seconds": 10}


@pytest.mark.skipif(os.name != "posix", reason="_fork_exec is POSIX only")
def test_low_level_fork_exec_is_denied():
    artifact, data = _artifact(
        _source(
            'import subprocess\n        subprocess._fork_exec(None, None)\n        text = "spawned"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX only")
def test_descendant_holding_pipes_does_not_hang():
    artifact, data = _artifact(
        _source(
            "import ctypes\n"
            "        import struct\n"
            "        import time\n"
            "        libc = ctypes.CDLL(None)\n"
            "        if libc.fork() == 0:\n"
            "            time.sleep(60)\n"
            "            os._exit(0)\n"
            "        os.write(3, struct.pack('>I', 3) + b'{{{')\n"
            "        await asyncio.sleep(60)\n"
            '        text = "never"'
        )
    )

    started = time.monotonic()
    with pytest.raises(SandboxCrashed):
        _run(artifact, data, wall=6.0)

    assert time.monotonic() - started < 20


@pytest.mark.skipif(os.name != "posix", reason="_posixsubprocess is POSIX only")
def test_posixsubprocess_fork_exec_is_denied():
    artifact, data = _artifact(
        _source(
            "import _posixsubprocess\n"
            "        _posixsubprocess.fork_exec()\n"
            '        text = "spawned"'
        )
    )

    with pytest.raises(SandboxViolation):
        _run(artifact, data)
