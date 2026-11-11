"""SLICE-022: the tool sandbox isolates execution and bounds resources."""

from __future__ import annotations

import contextlib
import os
import socket
import threading

import helpers
import pytest

from adk_agent.sandbox import SandboxPolicy, SandboxTimeout, SandboxToolError, ToolSandbox


def _sandbox(**overrides) -> ToolSandbox:
    data = {"timeout_seconds": 10.0}
    data.update(overrides)
    return ToolSandbox(SandboxPolicy(**data))


@contextlib.contextmanager
def _local_server():
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    received: list[bytes] = []

    def serve() -> None:
        try:
            connection, _ = server.accept()
            with connection:
                received.append(connection.recv(16))
        finally:
            server.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port, received
    finally:
        server.close()


def test_sandbox_returns_result():
    assert _sandbox().invoke(helpers.add, (), {"a": 1, "b": 2}) == 3


def test_sandbox_async_result():
    assert _sandbox().invoke(helpers.async_add, (), {"a": 1, "b": 2}) == 3


def test_sandbox_timeout():
    with pytest.raises(SandboxTimeout):
        _sandbox(timeout_seconds=0.2).invoke(helpers.sleep_long, (), {"seconds": 2})


def test_sandbox_denies_network():
    with pytest.raises(SandboxToolError) as raised:
        _sandbox().invoke(helpers.fetch, (), {"host": "example.com", "port": 80})
    assert raised.value.error_code == "SandboxViolation"


def test_sandbox_allows_listed_host():
    with _local_server() as (port, received):
        result = _sandbox(allowed_hosts=["127.0.0.1"]).invoke(
            helpers.fetch, (), {"host": "127.0.0.1", "port": port}
        )
    assert result == "connected"
    assert received == [b"ping"]


def test_sandbox_preserves_error_class():
    with pytest.raises(SandboxToolError) as raised:
        _sandbox().invoke(helpers.boom, (), {})
    assert raised.value.error_code == "ValueError"


def test_sandbox_clears_environment(monkeypatch):
    monkeypatch.setenv("SANDBOX_SECRET", "should-not-leak")
    keys = _sandbox().invoke(helpers.env_keys, (), {})
    assert "SANDBOX_SECRET" not in keys


@pytest.mark.skipif(os.name != "posix", reason="RLIMIT_AS is POSIX-only")
def test_sandbox_memory_limit():
    with pytest.raises(SandboxToolError) as raised:
        _sandbox(max_memory_mb=64, timeout_seconds=10.0).invoke(helpers.eat_memory, (), {})
    assert raised.value.error_code in {"MemoryError", "SandboxViolation"}


def test_sandbox_unsendable_result():
    with pytest.raises(SandboxToolError) as raised:
        _sandbox().invoke(helpers.unsendable, (), {})
    assert raised.value.error_code == "SandboxSerializationError"
