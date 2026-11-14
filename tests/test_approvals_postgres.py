"""SLICE-098: Postgres-backed approval inbox matching ``FileApprovalInbox``."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from adk_agent.approvals import (
    ApprovalConflict,
    ApprovalExpired,
    ApprovalNotFound,
    InvalidApprovalRequest,
)
from adk_agent.approvals_postgres import ApprovalInboxUnavailable, PostgresApprovalInbox
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


def _request(
    request_id: str,
    *,
    expires_at: datetime | None = None,
    requested_at: datetime | None = None,
    tenant: str = "acme",
    input_text: str = "deploy prod",
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        run_id="run-1",
        trace_id="trace-1",
        step_id="step-a",
        agent_ref=AgentRef(id="worker", version="1.0.0", digest="d" * 64),
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        input=input_text,
        reason="touches production",
        requested_at=requested_at or datetime.now(UTC),
        expires_at=expires_at,
    )


def _connect():
    import asyncpg

    return asyncpg.connect(_LIVE_URL)


def _delete(*request_ids: str) -> None:
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


def _status(request_id: str) -> str | None:
    async def scenario():
        conn = await _connect()
        try:
            return await conn.fetchval(
                "SELECT status FROM adk_approvals WHERE request_id = $1", request_id
            )
        finally:
            await conn.close()

    return asyncio.run(scenario())


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


def test_unsafe_request_id_rejected():
    inbox = PostgresApprovalInbox("postgresql://adk:adk@127.0.0.1:55432/adk")

    with pytest.raises(InvalidApprovalRequest):
        asyncio.run(inbox.submit(_request("../evil")))
    with pytest.raises(InvalidApprovalRequest):
        asyncio.run(inbox.decide("../evil", approved=True, approver="bob"))


def test_unsupported_url_rejected():
    with pytest.raises(ApprovalInboxUnavailable):
        PostgresApprovalInbox("mysql://localhost/adk")


@_live
@_needs_driver
def test_submit_idempotent_and_conflict():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)
    future = datetime.now(UTC) + timedelta(hours=1)
    request = _request(request_id, expires_at=future)

    async def scenario() -> None:
        try:
            await inbox.submit(request)
            await inbox.submit(request)
            with pytest.raises(ApprovalConflict):
                await inbox.submit(
                    _request(request_id, input_text="delete prod", expires_at=future)
                )
        finally:
            await inbox.aclose()

    try:
        asyncio.run(scenario())
    finally:
        _delete(request_id)


@_live
@_needs_driver
def test_decide_once():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            await inbox.submit(
                _request(request_id, expires_at=datetime.now(UTC) + timedelta(hours=1))
            )
            decision = await inbox.decide(request_id, approved=True, approver="bob", reason="ok")
            with pytest.raises(ApprovalConflict):
                await inbox.decide(request_id, approved=False, approver="mallory")
            return decision
        finally:
            await inbox.aclose()

    try:
        decision = asyncio.run(scenario())
    finally:
        _delete(request_id)

    assert decision.approved is True
    assert decision.approver == "bob"
    assert decision.request_id == request_id


@_live
@_needs_driver
def test_expired_cannot_decide():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario() -> None:
        try:
            await inbox.submit(
                _request(request_id, expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            with pytest.raises(ApprovalExpired):
                await inbox.decide(request_id, approved=True, approver="bob")
        finally:
            await inbox.aclose()

    try:
        asyncio.run(scenario())
        status = _status(request_id)
    finally:
        _delete(request_id)

    assert status == "expired"


@_live
@_needs_driver
def test_pending_filters():
    pending_id = _rid()
    decided_id = _rid()
    expired_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)
    future = datetime.now(UTC) + timedelta(hours=1)

    async def scenario():
        try:
            await inbox.submit(_request(pending_id, expires_at=future))
            await inbox.submit(_request(decided_id, expires_at=future))
            await inbox.submit(
                _request(expired_id, expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await inbox.decide(decided_id, approved=True, approver="bob")
            return await inbox.pending()
        finally:
            await inbox.aclose()

    try:
        pending = asyncio.run(scenario())
    finally:
        _delete(pending_id, decided_id, expired_id)

    assert [record.request_id for record in pending] == [pending_id]


@_live
@_needs_driver
def test_get_returns_decision():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            await inbox.submit(
                _request(request_id, expires_at=datetime.now(UTC) + timedelta(hours=1))
            )
            decision = await inbox.decide(request_id, approved=False, approver="carol", reason="no")
            record = await inbox.get(request_id)
            return decision, record
        finally:
            await inbox.aclose()

    try:
        decision, record = asyncio.run(scenario())
    finally:
        _delete(request_id)

    assert record is not None
    assert record.decision == decision
    assert record.request.request_id == request_id


@_live
@_needs_driver
def test_prune_archive_and_delete():
    archive_id = _rid()
    delete_id = _rid()
    clock = Clock(datetime.now(UTC) - timedelta(hours=2))
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01, clock=clock)
    future = datetime.now(UTC) + timedelta(hours=1)

    async def scenario():
        try:
            await inbox.submit(_request(archive_id, expires_at=future))
            await inbox.decide(archive_id, approved=True, approver="bob")
            archived = await inbox.prune(60, archive=True)

            await inbox.submit(_request(delete_id, expires_at=future))
            await inbox.decide(delete_id, approved=True, approver="bob")
            deleted = await inbox.prune(60, archive=False)
            return archived, deleted
        finally:
            await inbox.aclose()

    try:
        archived, deleted = asyncio.run(scenario())
    finally:
        _delete(archive_id, delete_id)

    assert archived.archived == 1
    assert archived.deleted == 0
    assert deleted.deleted == 1
    assert deleted.archived == 0


@_live
@_needs_driver
def test_prune_archives_expired_without_decision():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            await inbox.submit(
                _request(request_id, expires_at=datetime.now(UTC) - timedelta(hours=2))
            )
            return await inbox.prune(60, archive=True)
        finally:
            await inbox.aclose()

    try:
        result = asyncio.run(scenario())
        live = _status(request_id)
        archived = _archive_status(request_id)
    finally:
        _delete(request_id)

    assert result.archived == 1
    assert live is None
    assert archived == "expired"


@_live
@_needs_driver
def test_prune_does_not_overwrite_archive_for_reused_id():
    request_id = _rid()
    clock = Clock(datetime.now(UTC) - timedelta(hours=2))
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01, clock=clock)
    future = datetime.now(UTC) + timedelta(hours=1)

    async def scenario():
        try:
            await inbox.submit(_request(request_id, expires_at=future))
            await inbox.decide(request_id, approved=True, approver="bob")
            first = await inbox.prune(60, archive=True)

            await inbox.submit(_request(request_id, expires_at=future))
            await inbox.decide(request_id, approved=False, approver="carol")
            second = await inbox.prune(60, archive=True)
            return first, second, await inbox.get(request_id)
        finally:
            await inbox.aclose()

    try:
        first, second, record = asyncio.run(scenario())
        archived = _archive_status(request_id)
    finally:
        _delete(request_id)

    assert first.archived == 1
    assert second.archived == 0
    assert record is not None and record.decision is not None
    assert record.decision.approver == "carol"
    assert archived == "approved"


@_live
@_needs_driver
def test_concurrent_decide():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            await inbox.submit(
                _request(request_id, expires_at=datetime.now(UTC) + timedelta(hours=1))
            )
            return await asyncio.gather(
                inbox.decide(request_id, approved=True, approver="bob"),
                inbox.decide(request_id, approved=False, approver="mallory"),
                return_exceptions=True,
            )
        finally:
            await inbox.aclose()

    try:
        results = asyncio.run(scenario())
    finally:
        _delete(request_id)

    decisions = [result for result in results if not isinstance(result, BaseException)]
    conflicts = [result for result in results if isinstance(result, ApprovalConflict)]
    assert len(decisions) == 1
    assert len(conflicts) == 1
    assert decisions[0].approver in {"bob", "mallory"}


@_live
@_needs_driver
def test_request_polls_to_decision():
    request_id = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            task = asyncio.create_task(
                inbox.request(
                    _request(request_id, expires_at=datetime.now(UTC) + timedelta(hours=1))
                )
            )
            for _ in range(200):
                if await inbox.pending():
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("request never became pending")
            await inbox.decide(request_id, approved=True, approver="bob")
            return await asyncio.wait_for(task, timeout=2)
        finally:
            await inbox.aclose()

    try:
        decision = asyncio.run(scenario())
    finally:
        _delete(request_id)

    assert decision.approved is True
    assert decision.approver == "bob"


@_live
@_needs_driver
def test_unknown_request_not_found():
    missing = _rid()
    inbox = PostgresApprovalInbox(_LIVE_URL, poll_seconds=0.01)

    async def scenario():
        try:
            record = await inbox.get(missing)
            with pytest.raises(ApprovalNotFound):
                await inbox.decide(missing, approved=True, approver="bob")
            return record
        finally:
            await inbox.aclose()

    try:
        record = asyncio.run(scenario())
    finally:
        _delete(missing)

    assert record is None
