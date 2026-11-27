"""SLICE-312: deferred approvals in the MCP-served support demo."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_AGENT = ROOT / "scripts" / "support_a2a_agent.py"
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


def _params(workdir: Path, mock_url: str) -> StdioServerParameters:
    env = dict(os.environ)
    env.update(
        {
            "SUPPORT_MOCK_URL": mock_url,
            "SUPPORT_APPROVALS_DIR": str(workdir / "approvals"),
            "SUPPORT_AUDIT_FILE": str(workdir / "support-audit.jsonl"),
            "SUPPORT_WAIT_SECONDS": "60",
            "SUPPORT_DEFER": "1",
        }
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "adk_agent", "serve", "--agent", str(_AGENT)],
        env=env,
    )


def _decide(root: Path, *, approved: bool) -> str:
    from adk_agent.approvals import FileApprovalInbox

    inbox = FileApprovalInbox(root, poll_seconds=0.05)
    deadline = time.time() + 30
    while time.time() < deadline:
        pending = inbox.pending()
        if pending:
            inbox.decide(pending[0].request_id, approved=approved, approver="tester")
            return pending[0].request_id
        time.sleep(0.05)
    raise AssertionError("no approval request appeared")


def _ticket(mock_url: str, ticket_id: str) -> dict | None:
    import json
    import urllib.request

    request = urllib.request.Request(
        f"{mock_url}/itsm/tickets/{ticket_id}",
        headers={"Authorization": "Bearer demo-token"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _wait_ticket(mock_url: str, ticket_id: str, timeout: float = 20.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = _ticket(mock_url, ticket_id)
        if found is not None:
            return found
        time.sleep(0.2)
    return None


def test_mcp_deferred_call_returns_ack(tmp_path, mock):
    async def scenario() -> tuple[str, float]:
        async with (
            stdio_client(_params(tmp_path, mock)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            started = time.monotonic()
            result = await session.call_tool("support_flow", {"request": "客户无法登录"})
            elapsed = time.monotonic() - started
            text = "".join(getattr(item, "text", "") or "" for item in result.content)
            return text, elapsed

    text, elapsed = asyncio.run(scenario())

    assert "request_id=" in text, text
    assert "已提交" in text, text
    assert elapsed < 2
    assert _ticket(mock, "t-1") is None


def test_deferred_mcp_resumes_after_approval(tmp_path, mock):
    async def scenario() -> str:
        async with (
            stdio_client(_params(tmp_path, mock)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("support_flow", {"request": "客户无法登录"})
            text = "".join(getattr(item, "text", "") or "" for item in result.content)
            assert "request_id=" in text
            await asyncio.to_thread(_decide, tmp_path / "approvals", approved=True)
            ticket = await asyncio.to_thread(_wait_ticket, mock, "t-1")
            return "" if ticket is None else ticket["status"]

    status = asyncio.run(scenario())

    assert status == "open"


def test_deferred_mcp_denial_leaves_no_ticket(tmp_path, mock):
    async def scenario() -> None:
        async with (
            stdio_client(_params(tmp_path, mock)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            await session.call_tool("support_flow", {"request": "客户无法登录"})
            await asyncio.to_thread(_decide, tmp_path / "approvals", approved=False)
            await asyncio.sleep(3)

    asyncio.run(scenario())

    assert _ticket(mock, "t-1") is None


def test_deferred_doc_matches_env():
    doc = _DOC.read_text(encoding="utf-8")
    agent = _AGENT.read_text(encoding="utf-8")

    for variable in (
        "SUPPORT_DEFER",
        "SUPPORT_NOTIFY_WEBHOOK_URL",
        "SUPPORT_NOTIFY_SECRET_ENV",
    ):
        assert variable in agent
        assert variable in doc
    assert "request_id" in doc
