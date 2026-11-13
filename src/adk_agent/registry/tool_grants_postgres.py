"""Postgres-backed tool grant requests shared across replicas (ADR-0011)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    GrantRequestConflict,
    GrantRequestExpired,
    GrantRequestNotFound,
    GrantStatus,
    GrantStoreError,
    GrantStoreUnavailable,
    ToolGrantRequest,
    effective_status,
)
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_tool_grant_requests (
    request_id text PRIMARY KEY,
    tenant text NOT NULL,
    agent_id text NOT NULL,
    version text NOT NULL,
    digest text NOT NULL,
    tool_id text NOT NULL,
    data_classes text[] NOT NULL DEFAULT '{}',
    reason text NOT NULL,
    status text NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    decided_by text,
    decided_at timestamptz,
    decision_reason text NOT NULL DEFAULT ''
)
"""

_INSERT = (
    "INSERT INTO adk_tool_grant_requests "
    "(request_id, tenant, agent_id, version, digest, tool_id, data_classes, reason, status, "
    "requested_by, requested_at, expires_at, decided_by, decided_at, decision_reason) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15) "
    "ON CONFLICT (request_id) DO NOTHING"
)

_SELECT = (
    "SELECT request_id, tenant, agent_id, version, digest, tool_id, data_classes, reason, "
    "status, requested_by, requested_at, expires_at, decided_by, decided_at, decision_reason "
    "FROM adk_tool_grant_requests WHERE request_id = $1"
)

_SELECT_TENANT = (
    "SELECT request_id, tenant, agent_id, version, digest, tool_id, data_classes, reason, "
    "status, requested_by, requested_at, expires_at, decided_by, decided_at, decision_reason "
    "FROM adk_tool_grant_requests WHERE tenant = $1"
)

_DECIDE = (
    "UPDATE adk_tool_grant_requests "
    "SET status = $3, decided_by = $4, decided_at = $2, decision_reason = $5 "
    "WHERE request_id = $1 AND status = 'pending' AND expires_at > $2 "
    "RETURNING request_id, tenant, agent_id, version, digest, tool_id, data_classes, reason, "
    "status, requested_by, requested_at, expires_at, decided_by, decided_at, decision_reason"
)

_CANCEL = (
    "UPDATE adk_tool_grant_requests "
    "SET status = 'cancelled', decided_by = $2, decided_at = $3, decision_reason = $4 "
    "WHERE request_id = $1 AND status = 'pending' AND expires_at > $3 "
    "RETURNING request_id, tenant, agent_id, version, digest, tool_id, data_classes, reason, "
    "status, requested_by, requested_at, expires_at, decided_by, decided_at, decision_reason"
)

_ACTIVE = (
    "SELECT EXISTS ("
    "SELECT 1 FROM adk_tool_grant_requests "
    "WHERE tenant = $1 AND agent_id = $2 AND version = $3 AND digest = $4 AND tool_id = $5 "
    "AND status = 'approved' AND expires_at > $6)"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(row: Any) -> ToolGrantRequest:
    return ToolGrantRequest(
        request_id=row["request_id"],
        tenant=row["tenant"],
        agent_id=row["agent_id"],
        version=row["version"],
        digest=row["digest"],
        tool_id=row["tool_id"],
        data_classes=list(row["data_classes"]),
        reason=row["reason"],
        status=row["status"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        expires_at=row["expires_at"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        decision_reason=row["decision_reason"] or "",
    )


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


class PostgresToolGrantStore:
    """One row per grant request in ``adk_tool_grant_requests``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="tool grants", unavailable=GrantStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="tool grants",
            unavailable=GrantStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, request: ToolGrantRequest) -> ToolGrantRequest:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    _INSERT,
                    request.request_id,
                    request.tenant,
                    request.agent_id,
                    request.version,
                    request.digest,
                    request.tool_id,
                    list(request.data_classes),
                    request.reason,
                    request.status,
                    request.requested_by,
                    request.requested_at,
                    request.expires_at,
                    request.decided_by,
                    request.decided_at,
                    request.decision_reason,
                )
                row = await conn.fetchrow(_SELECT, request.request_id)
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant write failed ({type(exc).__name__})") from exc
        if row is None:
            raise GrantStoreUnavailable("tool grant request disappeared during write")
        existing = _parse(row)
        if existing.model_dump(mode="json") != request.model_dump(mode="json"):
            raise GrantRequestConflict(
                f"tool grant request {request.request_id!r} already exists with different content"
            )
        return existing

    async def get(self, request_id: str) -> ToolGrantRequest | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, request_id)
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant read failed ({type(exc).__name__})") from exc
        return None if row is None else _parse(row)

    async def list(
        self,
        tenant: str,
        *,
        status: GrantStatus | None = None,
        now: datetime | None = None,
    ) -> list[ToolGrantRequest]:
        moment = _now(now)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_TENANT, tenant)
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant read failed ({type(exc).__name__})") from exc
        records = [_parse(row) for row in rows]
        if status is not None:
            records = [r for r in records if effective_status(r, moment) == status]
        records.sort(key=lambda record: (record.requested_at, record.request_id))
        return records

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
        now: datetime | None = None,
    ) -> ToolGrantRequest:
        moment = _now(now)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    _DECIDE,
                    request_id,
                    moment,
                    "approved" if approved else "denied",
                    decided_by,
                    reason,
                )
                if row is None:
                    raise await self._decision_error(conn, request_id, moment)
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant write failed ({type(exc).__name__})") from exc
        return _parse(row)

    async def cancel(
        self,
        request_id: str,
        *,
        by: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> ToolGrantRequest:
        moment = _now(now)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_CANCEL, request_id, by, moment, reason)
                if row is None:
                    raise await self._decision_error(conn, request_id, moment)
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant write failed ({type(exc).__name__})") from exc
        return _parse(row)

    async def active(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        digest: str,
        tool_id: str,
        now: datetime | None = None,
    ) -> bool:
        moment = _now(now)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                found = await conn.fetchval(
                    _ACTIVE, tenant, agent_id, version, digest, tool_id, moment
                )
        except GrantStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise GrantStoreUnavailable(f"tool grant read failed ({type(exc).__name__})") from exc
        return bool(found)

    async def _decision_error(self, conn: Any, request_id: str, now: datetime) -> GrantStoreError:
        row = await conn.fetchrow(_SELECT, request_id)
        if row is None:
            return GrantRequestNotFound(f"tool grant request {request_id!r} not found")
        record = _parse(row)
        if effective_status(record, now) == "expired":
            return GrantRequestExpired(f"tool grant request {request_id!r} is expired")
        return GrantRequestConflict(
            f"tool grant request {request_id!r} is {effective_status(record, now)}"
        )


__all__ = ["PostgresToolGrantStore"]
