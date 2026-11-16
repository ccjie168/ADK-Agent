"""Postgres-backed connector registration requests shared across replicas (SLICE-122)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    ConnectorRequest,
    ConnectorRequestConflict,
    ConnectorRequestError,
    ConnectorRequestNotFound,
    ConnectorRequestStatus,
    ConnectorRequestStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_connector_requests (
    request_id text PRIMARY KEY,
    tenant text NOT NULL,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL
)
"""

_SELECT = "SELECT definition FROM adk_connector_requests WHERE request_id = $1"

_SELECT_TENANT = (
    "SELECT definition FROM adk_connector_requests "
    "WHERE tenant = $1 AND ($2::text IS NULL OR definition->>'status' = $2)"
)

_INSERT = (
    "INSERT INTO adk_connector_requests (request_id, tenant, definition, updated_at) "
    "VALUES ($1, $2, $3::jsonb, $4) ON CONFLICT (request_id) DO NOTHING"
)

_DECIDE = (
    "UPDATE adk_connector_requests SET definition = $2::jsonb, updated_at = $3 "
    "WHERE request_id = $1 AND definition->>'status' = 'pending' "
    "RETURNING definition"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(raw: Any) -> ConnectorRequest:
    try:
        return ConnectorRequest.model_validate_json(raw)
    except ValueError as exc:
        raise ConnectorRequestError("invalid connector request record") from exc


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


class PostgresConnectorRequestStore:
    """One row per connector request in ``adk_connector_requests``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(
            url, what="connector requests", unavailable=ConnectorRequestStoreUnavailable
        )
        self._pool = LazyPool(
            self._dsn,
            what="connector requests",
            unavailable=ConnectorRequestStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, record: ConnectorRequest) -> ConnectorRequest:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    _INSERT,
                    record.request_id,
                    record.tenant,
                    record.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(_SELECT, record.request_id)
        except ConnectorRequestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorRequestStoreUnavailable(
                f"connector request write failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            raise ConnectorRequestStoreUnavailable("connector request disappeared during write")
        existing = _parse(stored)
        if existing.model_dump(mode="json") != record.model_dump(mode="json"):
            raise ConnectorRequestConflict(
                f"connector request {record.request_id!r} already exists with different content"
            )
        return existing

    async def get(self, request_id: str) -> ConnectorRequest | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, request_id)
        except ConnectorRequestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorRequestStoreUnavailable(
                f"connector request read failed ({type(exc).__name__})"
            ) from exc
        return None if stored is None else _parse(stored)

    async def list(
        self,
        tenant: str,
        *,
        status: ConnectorRequestStatus | None = None,
    ) -> list[ConnectorRequest]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_TENANT, tenant, status)
        except ConnectorRequestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorRequestStoreUnavailable(
                f"connector request read failed ({type(exc).__name__})"
            ) from exc
        records = [_parse(row["definition"]) for row in rows]
        records.sort(key=lambda record: (record.requested_at, record.request_id))
        return records

    async def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str,
        registered_connector: str | None = None,
        now: datetime | None = None,
    ) -> ConnectorRequest:
        moment = _now(now)
        row: Any = None
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, request_id)
                if stored is None:
                    raise ConnectorRequestNotFound(f"connector request {request_id!r} not found")
                record = _parse(stored)
                if record.status != "pending":
                    raise ConnectorRequestConflict(
                        f"connector request {request_id!r} is {record.status}"
                    )
                decided = record.model_copy(
                    update={
                        "status": "approved" if approved else "denied",
                        "decided_by": decided_by,
                        "decided_at": moment,
                        "decision_reason": reason,
                        "registered_connector": registered_connector if approved else None,
                    }
                )
                row = await conn.fetchval(_DECIDE, request_id, decided.model_dump_json(), moment)
                if row is None:
                    raise ConnectorRequestConflict(
                        f"connector request {request_id!r} is no longer pending"
                    )
        except ConnectorRequestError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorRequestStoreUnavailable(
                f"connector request write failed ({type(exc).__name__})"
            ) from exc
        return _parse(row)

    async def aclose(self) -> None:
        await self._pool.close()


__all__ = ["PostgresConnectorRequestStore"]
