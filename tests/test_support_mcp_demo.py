"""SLICE-309: the support agent is reachable from Claude Desktop over MCP."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_AGENT = ROOT / "scripts" / "support_a2a_agent.py"
_CONFIG = ROOT / "scripts" / "mcp_desktop_config.py"
_DOC = ROOT / "docs" / "demo" / "support-mcp.md"


@pytest.fixture
def mock():
    sys.path.insert(0, str(ROOT / "scripts"))
    from support_demo_flow import free_port, start_mock

    port = free_port()
    server = start_mock(port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True


def _env(workdir: Path, mock_url: str, wait_seconds: int = 30) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "SUPPORT_MOCK_URL": mock_url,
            "SUPPORT_APPROVALS_DIR": str(workdir / "approvals"),
            "SUPPORT_AUDIT_FILE": str(workdir / "support-audit.jsonl"),
            "SUPPORT_WAIT_SECONDS": str(wait_seconds),
        }
    )
    return env


def _approve(root: Path, *, approved: bool = True) -> threading.Thread:
    def run() -> None:
        from adk_agent.approvals import FileApprovalInbox

        inbox = FileApprovalInbox(root, poll_seconds=0.05)
        deadline = time.time() + 30
        while time.time() < deadline:
            pending = inbox.pending()
            if pending:
                inbox.decide(pending[0].request_id, approved=approved, approver="tester")
                return
            time.sleep(0.05)
        raise AssertionError("no approval request appeared")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _server_params(workdir: Path, mock_url: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "adk_agent", "serve", "--agent", str(_AGENT)],
        env=_env(workdir, mock_url),
    )


def test_support_agent_lists_over_mcp(tmp_path, mock):
    async def scenario():
        async with (
            stdio_client(_server_params(tmp_path, mock)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.list_tools()

    tools = asyncio.run(scenario())

    [tool] = [item for item in tools.tools if item.name == "support_flow"]
    assert "request" in (tool.input_schema or {}).get("properties", {})


def test_support_agent_answer_over_mcp(tmp_path, mock):
    decider = _approve(tmp_path / "approvals")

    async def scenario():
        async with (
            stdio_client(_server_params(tmp_path, mock)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await session.call_tool("support_flow", {"request": "客户无法登录"})

    result = asyncio.run(scenario())
    decider.join(timeout=10)

    assert result.is_error is False
    text = "".join(getattr(item, "text", "") or "" for item in result.content)
    assert "t-1" in text, text

    from support_demo_flow import http

    assert http("GET", f"{mock}/itsm/tickets/t-1")["status"] == "open"


def test_desktop_config_generator(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(_CONFIG),
            "--workdir",
            str(tmp_path),
            "--mock-url",
            "http://127.0.0.1:8055",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    config = json.loads(proc.stdout)
    entry = config["mcpServers"]["adk-support"]
    assert entry["command"] == sys.executable
    assert entry["args"][:3] == ["-m", "adk_agent", "serve"]
    assert entry["args"][-1] == str(_AGENT)
    env = entry["env"]
    assert env["SUPPORT_MOCK_URL"] == "http://127.0.0.1:8055"
    assert env["SUPPORT_APPROVALS_DIR"] == str(tmp_path / "approvals")
    assert env["SUPPORT_AUDIT_FILE"] == str(tmp_path / "support-audit.jsonl")
    assert env["SUPPORT_WAIT_SECONDS"].isdigit()

    for blocked in (
        "http://example.com",
        "http://127.0.0.1.evil.com",
        "http://127.0.0.1@evil.com",
    ):
        refused = subprocess.run(
            [sys.executable, str(_CONFIG), "--mock-url", blocked],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert refused.returncode != 0, blocked
        assert "--mock-url must be a loopback http URL" in refused.stderr, blocked


def test_support_mcp_doc_matches_config():
    doc = _DOC.read_text(encoding="utf-8")
    script = _CONFIG.read_text(encoding="utf-8")

    assert "mcpServers" in doc and "adk-support" in doc
    assert "support_flow" in doc
    for variable in (
        "SUPPORT_MOCK_URL",
        "SUPPORT_MOCK_TOKEN",
        "SUPPORT_APPROVALS_DIR",
        "SUPPORT_AUDIT_FILE",
        "SUPPORT_WAIT_SECONDS",
    ):
        assert variable in script
        assert variable in doc
    for flag in ("--workdir", "--mock-url", "--wait-seconds", "--python"):
        assert flag in script
        assert flag in doc
    assert "claude mcp add" in doc
    assert ".mcp.json" in doc
