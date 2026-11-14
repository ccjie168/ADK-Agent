"""SLICE-099: approval backend resolution for console and prune."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent import cli
from adk_agent.approvals_postgres import PostgresApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

UTC = timezone.utc

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPROVAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("ADK_APPROVAL_DIR", raising=False)


def test_console_approval_backend_exclusive(monkeypatch, capsys):
    _clear_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli._approval_backend("dir", "db")

    assert exc.value.code == 1
    assert "--approval-dir and --approval-db are mutually exclusive" in capsys.readouterr().err


def test_console_approval_backend_precedence(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ADK_APPROVAL_DIR", "/env/dir")
    monkeypatch.setenv("APPROVAL_DATABASE_URL", "postgresql://env/db")

    assert cli._approval_backend("dir", None) == ("dir", "dir")
    assert cli._approval_backend(None, "postgresql://x/y") == ("db", "postgresql://x/y")
    assert cli._approval_backend(None, None) == ("db", "postgresql://env/db")


def test_console_approval_backend_env_and_none(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ADK_APPROVAL_DIR", "/env/dir")
    assert cli._approval_backend(None, None) == ("dir", "/env/dir")

    _clear_env(monkeypatch)
    assert cli._approval_backend(None, None) is None


def test_prune_backend_resolution(monkeypatch, capsys):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ADK_APPROVAL_DIR", "/env/dir")
    monkeypatch.setenv("APPROVAL_DATABASE_URL", "postgresql://env/db")

    assert cli._approval_backend(None, None, dir_flag="--dir", db_flag="--db") == (
        "db",
        "postgresql://env/db",
    )

    with pytest.raises(SystemExit) as exc:
        cli._approval_backend("dir", "db", dir_flag="--dir", db_flag="--db")

    assert exc.value.code == 1
    assert "--dir and --db are mutually exclusive" in capsys.readouterr().err


def _request(request_id: str) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant="acme", subject="alice", kind="human"),
        input="deploy prod",
        reason="touches production",
        requested_at=datetime.now(UTC),
    )


def _connect():
    import asyncpg

    return asyncpg.connect(_LIVE_URL)


def _cleanup(*request_ids: str) -> None:
    async def scenario() -> None:
        conn = await _connect()
        try:
            await conn.execute(
                "DELETE FROM adk_approvals WHERE request_id = ANY($1::text[])",
                list(request_ids),
            )
            await conn.execute(
                "DELETE FROM adk_approvals_archive WHERE request_id = ANY($1::text[])",
                list(request_ids),
            )
        finally:
            await conn.close()

    asyncio.run(scenario())


def _archive_status(request_id: str) -> str | None:
    async def scenario():
        conn = await _connect()
        try:
            return await conn.fetchval(
                "SELECT status FROM adk_approvals_archive WHERE request_id = $1", request_id
            )
        finally:
            await conn.close()

    return asyncio.run(scenario())


def _seed_decided(request_id: str) -> None:
    def clock() -> datetime:
        return datetime.now(UTC) - timedelta(hours=2)

    inbox = PostgresApprovalInbox(_LIVE_URL, clock=clock)

    async def scenario() -> None:
        try:
            await inbox.submit(_request(request_id))
            await inbox.decide(request_id, approved=True, approver="bob")
        finally:
            await inbox.aclose()

    asyncio.run(scenario())


@_live
@_needs_driver
def test_prune_db_archives(capsys):
    request_id = "r" + uuid.uuid4().hex[:12]
    _seed_decided(request_id)
    try:
        cli.main(["approvals", "prune", "--db", _LIVE_URL, "--older-than", "60"])

        assert "archived 1 requests" in capsys.readouterr().out
        assert _archive_status(request_id) == "approved"
    finally:
        _cleanup(request_id)
