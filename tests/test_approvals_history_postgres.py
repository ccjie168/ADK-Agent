"""SLICE-118: approval history over the Postgres inbox."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent.approvals_postgres import PostgresApprovalInbox
from adk_agent.core import AgentRef, ApprovalRequest, Principal

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")

UTC = timezone.utc


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _rid() -> str:
    return "r" + uuid.uuid4().hex[:12]


def _tenant() -> str:
    return "hist-" + uuid.uuid4().hex[:8]


def _request(
    request_id: str,
    *,
    tenant: str,
    expires_at: datetime | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        input="deploy prod",
        reason="touches production",
        requested_at=datetime.now(UTC),
        expires_at=expires_at,
    )


def _delete(*request_ids: str) -> None:
    async def scenario() -> None:
        import asyncpg

        conn = await asyncpg.connect(_LIVE_URL)
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


@_live
@_needs_driver
def test_history_merges_live_and_archive():
    tenant = _tenant()
    live_id = _rid()
    archived_id = _rid()
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)
    live = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01, clock=Clock(now))
    old = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01, clock=Clock(now - timedelta(hours=2)))

    async def scenario():
        try:
            await live.submit(_request(live_id, tenant=tenant, expires_at=future))
            await live.decide(live_id, approved=True, approver="alice", reason="ok")

            await old.submit(_request(archived_id, tenant=tenant, expires_at=future))
            await old.decide(archived_id, approved=False, approver="bob", reason="no")
            await old.prune(60, archive=True)

            return await live.history(tenant=tenant)
        finally:
            await live.aclose()
            await old.aclose()

    try:
        entries = asyncio.run(scenario())
    finally:
        _delete(live_id, archived_id)

    by_id = {entry.request.request_id: entry for entry in entries}
    assert by_id[live_id].archived is False
    assert by_id[live_id].status == "approved"
    assert by_id[live_id].decision is not None
    assert by_id[live_id].decision.approver == "alice"
    assert by_id[archived_id].archived is True
    assert by_id[archived_id].status == "denied"
    assert by_id[archived_id].decision is not None
    assert by_id[archived_id].decision.reason == "no"


@_live
@_needs_driver
def test_history_maps_live_expired_pending():
    tenant = _tenant()
    request_id = _rid()
    deadline = datetime.now(UTC) - timedelta(minutes=10)
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            await inbox.submit(_request(request_id, tenant=tenant, expires_at=deadline))
            return await inbox.history(tenant=tenant)
        finally:
            await inbox.aclose()

    try:
        entries = asyncio.run(scenario())
    finally:
        _delete(request_id)

    [entry] = entries
    assert entry.request.request_id == request_id
    assert entry.status == "expired"
    assert entry.decision is None
    assert entry.archived is False
    assert entry.terminal_at == deadline


@_live
@_needs_driver
def test_history_filters_order_and_limit():
    tenant = _tenant()
    request_ids = [_rid() for _ in range(3)]
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)
    clock = Clock(now)
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01, clock=clock)

    async def scenario():
        try:
            for request_id in request_ids:
                await inbox.submit(_request(request_id, tenant=tenant, expires_at=future))
            for request_id, minute, approved in (
                (request_ids[0], 1, True),
                (request_ids[1], 3, False),
                (request_ids[2], 2, True),
            ):
                clock.now = now + timedelta(minutes=minute)
                await inbox.decide(
                    request_id,
                    approved=approved,
                    approver="alice" if approved else "bob",
                )
            return (
                await inbox.history(tenant=tenant),
                await inbox.history(tenant=tenant, status="denied"),
                await inbox.history(tenant=tenant, limit=1),
                await inbox.history(tenant=tenant, limit=0),
            )
        finally:
            await inbox.aclose()

    try:
        ordered, denied, one, zero = asyncio.run(scenario())
    finally:
        _delete(*request_ids)

    assert [entry.request.request_id for entry in ordered] == [
        request_ids[1],
        request_ids[2],
        request_ids[0],
    ]
    assert [entry.request.request_id for entry in denied] == [request_ids[1]]
    assert [entry.request.request_id for entry in one] == [request_ids[1]]
    assert [entry.request.request_id for entry in zero] == [request_ids[1]]


@_live
@_needs_driver
def test_history_rejects_unknown_status():
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario() -> None:
        try:
            await inbox.history(status="pending")
        finally:
            await inbox.aclose()

    with pytest.raises(ValueError):
        asyncio.run(scenario())
