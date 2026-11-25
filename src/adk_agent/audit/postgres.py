"""Postgres-backed audit store with one hash chain per tenant (ADR-0016)."""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from ..core import AuditEvent, AuditRecord
from ..pg import LazyPool, normalize_dsn
from .keyring import SigningKeyring
from .pipeline import (
    AuditChainBroken,
    AuditSignatureInvalid,
    record_hash,
    record_signature,
)


class AuditStoreUnavailable(Exception):
    """The audit database could not be reached or has an invalid schema."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_audit_records (
    tenant text NOT NULL,
    sequence bigint NOT NULL,
    event jsonb NOT NULL,
    prev_hash text NOT NULL,
    hash text NOT NULL,
    signature text,
    kid text,
    action text NOT NULL,
    status text NOT NULL,
    trace_id text NOT NULL,
    run_id text NOT NULL,
    occurred_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, sequence)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS adk_audit_records_tenant_occurred "
    "ON adk_audit_records (tenant, occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS adk_audit_records_trace_id ON adk_audit_records (trace_id)",
    "CREATE INDEX IF NOT EXISTS adk_audit_records_run_id ON adk_audit_records (run_id)",
    "CREATE INDEX IF NOT EXISTS adk_audit_records_action ON adk_audit_records (action)",
    "CREATE INDEX IF NOT EXISTS adk_audit_records_status ON adk_audit_records (status)",
)

_INSERT = """
INSERT INTO adk_audit_records
    (tenant, sequence, event, prev_hash, hash, signature, kid, action, status,
     trace_id, run_id, occurred_at)
VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, $10, $11, $12)
"""

_SELECT_ALL = (
    "SELECT tenant, sequence, event, prev_hash, hash, signature, kid "
    "FROM adk_audit_records ORDER BY tenant, sequence"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
        for statement in _INDEXES:
            await conn.execute(statement)


def _lazy_pool(url: str) -> LazyPool:
    dsn = normalize_dsn(url, what="audit", unavailable=AuditStoreUnavailable)
    return LazyPool(
        dsn,
        what="audit",
        unavailable=AuditStoreUnavailable,
        setup=_ensure_schema,
    )


def _sign(
    digest: str,
    signing_key: str | None,
    keyring: SigningKeyring | None,
) -> tuple[str | None, str | None]:
    if keyring is not None:
        key: str | None = keyring.keys[keyring.active]
        kid = keyring.active
    else:
        key = signing_key
        kid = None
    signature = record_signature(digest, key) if key is not None else None
    return signature, kid


async def _select_events(
    pool: Any,
    *,
    tenant: str | None,
    trace_id: str | None,
    run_id: str | None,
    action: str | None,
    status: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    order: str,
    before: tuple[datetime, str] | None = None,
) -> list[AuditEvent]:
    conditions: list[str] = []
    params: list[Any] = []
    for field, value in (
        ("tenant", tenant),
        ("trace_id", trace_id),
        ("run_id", run_id),
        ("action", action),
        ("status", status),
    ):
        if value is not None:
            params.append(value)
            conditions.append(f"{field} = ${len(params)}")
    if since is not None:
        params.append(since)
        conditions.append(f"occurred_at >= ${len(params)}")
    if until is not None:
        params.append(until)
        conditions.append(f"occurred_at <= ${len(params)}")
    direction = "DESC" if order == "desc" else "ASC"
    if before is not None:
        params.append(before[0])
        timestamp_index = len(params)
        params.append(before[1])
        comparison = "<" if order == "desc" else ">"
        conditions.append(
            f"(occurred_at, event->>'event_id') {comparison} (${timestamp_index}, ${len(params)})"
        )
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)
    # Only fixed column fragments and $n placeholders are interpolated; values stay bound.
    query = (
        "SELECT event FROM adk_audit_records"  # nosec B608
        f"{where}"
        f" ORDER BY occurred_at {direction}, event->>'event_id' {direction},"
        f" tenant {direction}, sequence {direction}"
        f" LIMIT ${len(params)}"
    )
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return [AuditEvent.model_validate_json(row["event"]) for row in rows]


class PostgresAuditSink:
    def __init__(
        self,
        url: str,
        *,
        signing_key: str | None = None,
        keyring: SigningKeyring | None = None,
    ) -> None:
        if signing_key is not None and keyring is not None:
            raise ValueError("pass signing_key or keyring, not both")
        self.signing_key = signing_key
        self.keyring = keyring
        self._pool = _lazy_pool(url)

    async def append(self, event: AuditEvent) -> AuditRecord:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('adk_audit:' || $1))",
                    event.tenant,
                )
                row = await conn.fetchrow(
                    "SELECT sequence, hash FROM adk_audit_records "
                    "WHERE tenant = $1 ORDER BY sequence DESC LIMIT 1",
                    event.tenant,
                )
                prev_hash = row["hash"] if row is not None else ""
                sequence = (row["sequence"] + 1) if row is not None else 1
                event_text = event.model_dump_json()
                digest = record_hash(event_text, prev_hash)
                signature, kid = _sign(digest, self.signing_key, self.keyring)
                await conn.execute(
                    _INSERT,
                    event.tenant,
                    sequence,
                    event_text,
                    prev_hash,
                    digest,
                    signature,
                    kid,
                    event.action,
                    event.status,
                    event.trace_id,
                    event.run_id,
                    event.timestamp,
                )
        except AuditStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AuditStoreUnavailable(f"audit write failed ({type(exc).__name__})") from exc
        return AuditRecord(
            event=event, prev_hash=prev_hash, hash=digest, signature=signature, kid=kid
        )

    async def emit(self, event: AuditEvent) -> None:
        await self.append(event)

    async def aclose(self) -> None:
        await self._pool.close()


async def query_audit_records(
    url: str,
    *,
    tenant: str | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    action: str | None = None,
    status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    order: str = "desc",
) -> list[AuditEvent]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if order not in {"asc", "desc"}:
        raise ValueError("order must be 'asc' or 'desc'")
    pool = _lazy_pool(url)
    try:
        return await _select_events(
            await pool.get(),
            tenant=tenant,
            trace_id=trace_id,
            run_id=run_id,
            action=action,
            status=status,
            since=since,
            until=until,
            limit=limit,
            order=order,
        )
    except AuditStoreUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AuditStoreUnavailable(f"audit query failed ({type(exc).__name__})") from exc
    finally:
        await pool.close()


def _walk(
    rows: list[Any],
    signing_key: str | None,
    keyring: SigningKeyring | None,
) -> int:
    last: dict[str, str] = {}
    count = 0
    for row in rows:
        tenant = row["tenant"]
        sequence = row["sequence"]
        try:
            AuditEvent.model_validate_json(row["event"])
        except ValueError as exc:
            raise AuditChainBroken(sequence, tenant) from exc
        prev_hash = row["prev_hash"]
        digest = row["hash"]
        if prev_hash != last.get(tenant, ""):
            raise AuditChainBroken(sequence, tenant)
        # Hash the stored jsonb text, not the current model (ADR-0037).
        if record_hash(row["event"], prev_hash) != digest:
            raise AuditChainBroken(sequence, tenant)
        if keyring is not None:
            key = keyring.key_for(row["kid"])
            if key is None:
                raise AuditSignatureInvalid(sequence, tenant)
        elif signing_key is not None:
            if row["kid"] is not None:
                raise AuditSignatureInvalid(sequence, tenant)
            key = signing_key
        else:
            key = None
        if key is not None:
            expected = record_signature(digest, key)
            if row["signature"] is None or not hmac.compare_digest(row["signature"], expected):
                raise AuditSignatureInvalid(sequence, tenant)
        last[tenant] = digest
        count += 1
    return count


async def verify_audit_database(
    url: str,
    signing_key: str | None = None,
    keyring: SigningKeyring | None = None,
) -> int:
    if signing_key is not None and keyring is not None:
        raise ValueError("pass signing_key or keyring, not both")
    pool = _lazy_pool(url)
    try:
        db = await pool.get()
        async with db.acquire() as conn:
            rows = await conn.fetch(_SELECT_ALL)
        return _walk(rows, signing_key, keyring)
    except (AuditChainBroken, AuditSignatureInvalid, AuditStoreUnavailable):
        raise
    except Exception as exc:  # noqa: BLE001
        raise AuditStoreUnavailable(f"audit verify failed ({type(exc).__name__})") from exc
    finally:
        await pool.close()


class PostgresAuditQuery:
    def __init__(self, url: str) -> None:
        self._pool = _lazy_pool(url)

    async def events(
        self,
        *,
        tenant: str | None,
        limit: int,
        before: tuple[datetime, str] | None = None,
    ) -> list[AuditEvent]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        try:
            return await _select_events(
                await self._pool.get(),
                tenant=tenant,
                trace_id=None,
                run_id=None,
                action=None,
                status=None,
                since=None,
                until=None,
                limit=limit,
                order="desc",
                before=before,
            )
        except AuditStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AuditStoreUnavailable(f"audit query failed ({type(exc).__name__})") from exc

    async def aclose(self) -> None:
        await self._pool.close()


__all__ = [
    "AuditStoreUnavailable",
    "PostgresAuditQuery",
    "PostgresAuditSink",
    "query_audit_records",
    "verify_audit_database",
]
