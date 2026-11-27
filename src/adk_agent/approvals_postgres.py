"""A Postgres-backed approval inbox with a single-row state machine (ADR-0017).

One row per request, so an executor process and a console process can share an
approval across replicas without sharing memory. Decisions are atomic: the
conditional ``UPDATE`` matches only a still-pending, unexpired row, so two
concurrent decisions produce exactly one winner and one ``ApprovalConflict``.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from .approvals import (
    HISTORY_STATUSES,
    ApprovalConflict,
    ApprovalExpired,
    ApprovalHistoryEntry,
    ApprovalInboxError,
    ApprovalNotFound,
    ApprovalRecord,
    InvalidApprovalRequest,
    PruneResult,
    _checked_id,
)
from .core import AgentRef, ApprovalDecision, ApprovalRequest, Principal
from .pg import LazyPool, normalize_dsn

_logger = logging.getLogger(__name__)


class ApprovalInboxUnavailable(ApprovalInboxError):
    """The approval database could not be reached or has an invalid schema."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_approvals (
    request_id text PRIMARY KEY,
    tenant text NOT NULL,
    run_id text NOT NULL,
    trace_id text NOT NULL,
    step_id text NOT NULL,
    agent_ref jsonb NOT NULL,
    principal jsonb NOT NULL,
    input text NOT NULL,
    reason text NOT NULL DEFAULT '',
    requested_at timestamptz NOT NULL,
    expires_at timestamptz,
    status text NOT NULL,
    decided_at timestamptz,
    decided_by text,
    decision jsonb
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS adk_approvals_status_requested "
    "ON adk_approvals (status, requested_at)"
)

_ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_approvals_archive (
    request_id text PRIMARY KEY,
    tenant text NOT NULL,
    run_id text NOT NULL,
    trace_id text NOT NULL,
    step_id text NOT NULL,
    agent_ref jsonb NOT NULL,
    principal jsonb NOT NULL,
    input text NOT NULL,
    reason text NOT NULL DEFAULT '',
    requested_at timestamptz NOT NULL,
    expires_at timestamptz,
    status text NOT NULL,
    decided_at timestamptz,
    decided_by text,
    decision jsonb,
    archived_at timestamptz NOT NULL DEFAULT now()
)
"""

_INSERT = """
INSERT INTO adk_approvals
    (request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
     input, reason, requested_at, expires_at, status)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, 'pending')
ON CONFLICT (request_id) DO NOTHING
RETURNING request_id
"""

_SELECT = """
SELECT request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
       input, reason, requested_at, expires_at, status, decided_at, decided_by, decision
FROM adk_approvals
WHERE request_id = $1
"""

_SELECT_PENDING = """
SELECT request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
       input, reason, requested_at, expires_at, status, decided_at, decided_by, decision
FROM adk_approvals
WHERE status = 'pending' AND (expires_at IS NULL OR expires_at > now())
ORDER BY requested_at, request_id
"""

_SELECT_HISTORY = """
SELECT * FROM (
    SELECT request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
           input, reason, requested_at, expires_at,
           CASE WHEN status = 'pending' THEN 'expired' ELSE status END AS status,
           decided_at, decided_by, decision, false AS archived
    FROM adk_approvals
    WHERE status <> 'pending' OR (expires_at IS NOT NULL AND expires_at <= now())
    UNION ALL
    SELECT request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
           input, reason, requested_at, expires_at, status,
           decided_at, decided_by, decision, true AS archived
    FROM adk_approvals_archive
) AS history
WHERE ($1::text IS NULL OR tenant = $1)
  AND ($2::text IS NULL OR status = $2)
  AND (
    $4::timestamptz IS NULL
    OR COALESCE(decided_at, expires_at, requested_at) > $4
  )
ORDER BY COALESCE(decided_at, expires_at, requested_at) DESC, request_id
LIMIT $3
"""

_SELECT_HISTORY_ASC = _SELECT_HISTORY.replace(
    "ORDER BY COALESCE(decided_at, expires_at, requested_at) DESC, request_id",
    "ORDER BY COALESCE(decided_at, expires_at, requested_at) ASC, request_id",
)

_UPDATE_DECIDE = """
UPDATE adk_approvals
SET status = $2, decided_at = $3, decided_by = $4, decision = $5::jsonb
WHERE request_id = $1 AND status = 'pending'
  AND (expires_at IS NULL OR expires_at > now())
RETURNING *
"""

_UPDATE_EXPIRED = """
UPDATE adk_approvals
SET status = 'expired'
WHERE request_id = $1 AND status = 'pending'
"""

_PRUNE_ARCHIVE = """
WITH moved AS (
    INSERT INTO adk_approvals_archive
        (request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
         input, reason, requested_at, expires_at, status, decided_at, decided_by, decision)
    SELECT request_id, tenant, run_id, trace_id, step_id, agent_ref, principal,
           input, reason, requested_at, expires_at,
           CASE WHEN status = 'pending' THEN 'expired' ELSE status END,
           decided_at, decided_by, decision
    FROM adk_approvals
    WHERE (status IN ('approved', 'denied', 'expired', 'cancelled')
           OR (status = 'pending' AND expires_at IS NOT NULL))
      AND COALESCE(decided_at, expires_at, requested_at) < now() - make_interval(secs => $1::float8)
    ON CONFLICT (request_id) DO NOTHING
    RETURNING request_id
)
DELETE FROM adk_approvals
WHERE request_id IN (SELECT request_id FROM moved)
RETURNING request_id
"""

_PRUNE_DELETE = """
DELETE FROM adk_approvals
WHERE (status IN ('approved', 'denied', 'expired', 'cancelled')
       OR (status = 'pending' AND expires_at IS NOT NULL))
  AND COALESCE(decided_at, expires_at, requested_at) < now() - make_interval(secs => $1::float8)
RETURNING request_id
"""


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
        await conn.execute(_INDEX)
        await conn.execute(_ARCHIVE_SCHEMA)


def _lazy_pool(url: str) -> LazyPool:
    dsn = normalize_dsn(url, what="approval", unavailable=ApprovalInboxUnavailable)
    return LazyPool(
        dsn,
        what="approval",
        unavailable=ApprovalInboxUnavailable,
        setup=_ensure_schema,
    )


def _request_from_row(row: Any) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=row["request_id"],
        run_id=row["run_id"],
        trace_id=row["trace_id"],
        step_id=row["step_id"],
        agent_ref=AgentRef.model_validate_json(row["agent_ref"]),
        principal=Principal.model_validate_json(row["principal"]),
        input=row["input"],
        reason=row["reason"],
        requested_at=row["requested_at"],
        expires_at=row["expires_at"],
    )


def _record_from_row(row: Any) -> ApprovalRecord:
    decision = (
        ApprovalDecision.model_validate_json(row["decision"])
        if row["decision"] is not None
        else None
    )
    return ApprovalRecord(request=_request_from_row(row), decision=decision)


def _history_from_row(row: Any) -> ApprovalHistoryEntry:
    decision = (
        ApprovalDecision.model_validate_json(row["decision"])
        if row["decision"] is not None
        else None
    )
    return ApprovalHistoryEntry(
        request=_request_from_row(row),
        decision=decision,
        status=row["status"],
        archived=row["archived"],
        terminal_at=row["decided_at"] or row["expires_at"] or row["requested_at"],
    )


class PostgresApprovalInbox:
    """Store approval requests and decisions as one row per request."""

    def __init__(
        self,
        url: str,
        *,
        poll_seconds: float = 0.5,
        clock: Callable[[], datetime] | None = None,
        ttl_seconds: float | None = None,
        on_submit: Callable[[ApprovalRequest], Awaitable[None] | None] | None = None,
    ) -> None:
        self.poll_seconds = poll_seconds
        self.ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._on_submit = on_submit
        self._pool = _lazy_pool(url)

    def expires_at(self, request: ApprovalRequest) -> datetime | None:
        if request.expires_at is not None:
            return request.expires_at
        if self.ttl_seconds is None:
            return None
        return request.requested_at + timedelta(seconds=self.ttl_seconds)

    def is_expired(self, request: ApprovalRequest, now: datetime | None = None) -> bool:
        deadline = self.expires_at(request)
        if deadline is None:
            return False
        return (now if now is not None else self._clock()) >= deadline

    def _with_effective_expiry(self, request: ApprovalRequest) -> ApprovalRequest:
        return request.model_copy(update={"expires_at": self.expires_at(request)})

    async def submit(self, request: ApprovalRequest) -> None:
        request_id = _checked_id(request.request_id)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                inserted = await conn.fetchrow(
                    _INSERT,
                    request_id,
                    request.principal.tenant,
                    request.run_id,
                    request.trace_id,
                    request.step_id,
                    request.agent_ref.model_dump_json(),
                    request.principal.model_dump_json(),
                    request.input,
                    request.reason,
                    request.requested_at,
                    self.expires_at(request),
                )
                if inserted is not None:
                    return
                existing_row = await conn.fetchrow(_SELECT, request_id)
                if existing_row is None:
                    raise ApprovalInboxUnavailable(
                        f"approval request {request_id!r} disappeared during submit"
                    )
                if _request_from_row(existing_row) != self._with_effective_expiry(request):
                    raise ApprovalConflict(
                        f"request {request_id!r} already exists with different content"
                    )
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(
                f"approval submit failed ({type(exc).__name__})"
            ) from exc

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        approver: str,
        reason: str = "",
    ) -> ApprovalDecision:
        request_id = _checked_id(request_id)
        decision = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            approver=approver,
            reason=reason,
            decided_at=self._clock(),
        )
        status = "approved" if approved else "denied"
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    _UPDATE_DECIDE,
                    request_id,
                    status,
                    decision.decided_at,
                    approver,
                    decision.model_dump_json(),
                )
                if row is not None:
                    return decision
                existing = await conn.fetchrow(_SELECT, request_id)
                if existing is None:
                    raise ApprovalNotFound(f"no request {request_id!r}")
                if existing["status"] != "pending":
                    raise ApprovalConflict(f"request {request_id!r} already has a decision")
                await conn.execute(_UPDATE_EXPIRED, request_id)
                raise ApprovalExpired(f"approval request {request_id!r} has expired")
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(
                f"approval decide failed ({type(exc).__name__})"
            ) from exc

    async def get(self, request_id: str) -> ApprovalRecord | None:
        try:
            checked = _checked_id(request_id)
        except InvalidApprovalRequest:
            return None
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, checked)
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(f"approval get failed ({type(exc).__name__})") from exc
        return None if row is None else _record_from_row(row)

    async def pending(self) -> list[ApprovalRequest]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_PENDING)
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(
                f"approval pending failed ({type(exc).__name__})"
            ) from exc
        return [_request_from_row(row) for row in rows]

    async def history(
        self,
        *,
        tenant: str | None = None,
        status: str | None = None,
        limit: int = 50,
        oldest_first: bool = False,
        since: datetime | None = None,
    ) -> list[ApprovalHistoryEntry]:
        if status is not None and status not in HISTORY_STATUSES:
            raise ValueError(f"unknown approval history status: {status!r}")
        limit = max(1, min(200, limit))
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                sql = _SELECT_HISTORY_ASC if oldest_first else _SELECT_HISTORY
                rows = await conn.fetch(sql, tenant, status, limit, since)
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(
                f"approval history failed ({type(exc).__name__})"
            ) from exc
        return [_history_from_row(row) for row in rows]

    async def prune(
        self,
        max_age_seconds: float,
        *,
        archive: bool = True,
    ) -> PruneResult:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be greater than 0")
        statement = _PRUNE_ARCHIVE if archive else _PRUNE_DELETE
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(statement, float(max_age_seconds))
        except ApprovalInboxError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApprovalInboxUnavailable(f"approval prune failed ({type(exc).__name__})") from exc
        count = len(rows)
        return PruneResult(archived=count if archive else 0, deleted=0 if archive else count)

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """Submit, notify, then wait for a decision to be recorded."""
        await self.submit(request)
        await self._notify(request)
        request_id = request.request_id
        while True:
            record = await self.get(request_id)
            if record is not None and record.decision is not None:
                return record.decision
            if self.is_expired(request):
                raise ApprovalExpired(f"approval request {request_id!r} has expired")
            await asyncio.sleep(self.poll_seconds)

    async def _notify(self, request: ApprovalRequest) -> None:
        if self._on_submit is None:
            return
        try:
            result = self._on_submit(request)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "approval notification failed for %s: %s",
                request.request_id,
                type(exc).__name__,
            )

    async def aclose(self) -> None:
        await self._pool.close()


__all__ = ["ApprovalInboxUnavailable", "PostgresApprovalInbox"]
