"""Postgres-backed tool idempotency records shared across replicas (ADR-0034)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    DataClass,
    ToolExecutionRecord,
    ToolExecutionStatus,
    ToolIdempotencyConflict,
    ToolIdempotencyError,
    ToolIdempotencyUnavailable,
)
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_tool_idempotency (
    tenant text,
    tool_id text,
    idempotency_key text,
    record jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, tool_id, idempotency_key)
)
"""

_SELECT = (
    "SELECT record FROM adk_tool_idempotency "
    "WHERE tenant = $1 AND tool_id = $2 AND idempotency_key = $3"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresToolIdempotencyStore:
    """One execution record per ``(tenant, tool_id, idempotency_key)`` in ``adk_tool_idempotency``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(
            url, what="tool idempotency", unavailable=ToolIdempotencyUnavailable
        )
        self._pool = LazyPool(
            self._dsn,
            what="tool idempotency",
            unavailable=ToolIdempotencyUnavailable,
            setup=_ensure_schema,
        )

    async def claim(self, record: ToolExecutionRecord) -> ToolExecutionRecord:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_tool_idempotency "
                    "(tenant, tool_id, idempotency_key, record, updated_at) "
                    "VALUES ($1, $2, $3, $4::jsonb, $5) "
                    "ON CONFLICT (tenant, tool_id, idempotency_key) DO NOTHING",
                    record.tenant,
                    record.tool_id,
                    record.idempotency_key,
                    record.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(
                    _SELECT, record.tenant, record.tool_id, record.idempotency_key
                )
        except ToolIdempotencyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolIdempotencyUnavailable(
                f"tool idempotency write failed ({type(exc).__name__})"
            ) from exc
        return self._parse(stored, record.tenant, record.tool_id, record.idempotency_key)

    async def finish(
        self,
        tenant: str,
        tool_id: str,
        idempotency_key: str,
        *,
        status: ToolExecutionStatus,
        output: Any = None,
        data_classes: list[DataClass] | None = None,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> ToolExecutionRecord:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                raw = await conn.fetchval(_SELECT, tenant, tool_id, idempotency_key)
                if raw is None:
                    raise ToolIdempotencyConflict(
                        f"tool execution not found: {tenant}/{tool_id}/{idempotency_key}"
                    )
                existing = self._parse(raw, tenant, tool_id, idempotency_key)
                updated = existing.model_copy(
                    update={
                        "status": status,
                        "output": output,
                        "data_classes": list(data_classes) if data_classes is not None else [],
                        "error_code": error_code,
                        "finished_at": finished_at or datetime.now(timezone.utc),
                    }
                )
                stored = await conn.fetchval(
                    "UPDATE adk_tool_idempotency SET record = $4::jsonb, updated_at = $5 "
                    "WHERE tenant = $1 AND tool_id = $2 AND idempotency_key = $3 "
                    "RETURNING record",
                    tenant,
                    tool_id,
                    idempotency_key,
                    updated.model_dump_json(),
                    datetime.now(timezone.utc),
                )
        except ToolIdempotencyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolIdempotencyUnavailable(
                f"tool idempotency write failed ({type(exc).__name__})"
            ) from exc
        return self._parse(stored, tenant, tool_id, idempotency_key)

    async def get(
        self, tenant: str, tool_id: str, idempotency_key: str
    ) -> ToolExecutionRecord | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, tenant, tool_id, idempotency_key)
        except ToolIdempotencyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolIdempotencyUnavailable(
                f"tool idempotency read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, tenant, tool_id, idempotency_key)

    async def release(self, tenant: str, tool_id: str, idempotency_key: str) -> None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM adk_tool_idempotency "
                    "WHERE tenant = $1 AND tool_id = $2 AND idempotency_key = $3",
                    tenant,
                    tool_id,
                    idempotency_key,
                )
        except ToolIdempotencyError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ToolIdempotencyUnavailable(
                f"tool idempotency delete failed ({type(exc).__name__})"
            ) from exc

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(
        self, raw: str | None, tenant: str, tool_id: str, idempotency_key: str
    ) -> ToolExecutionRecord:
        if raw is None:
            raise ToolIdempotencyConflict(
                f"tool execution disappeared: {tenant}/{tool_id}/{idempotency_key}"
            )
        try:
            return ToolExecutionRecord.model_validate_json(raw)
        except ValueError as exc:
            raise ToolIdempotencyError(
                f"{tenant}/{tool_id}/{idempotency_key}: invalid tool execution record"
            ) from exc


__all__ = ["PostgresToolIdempotencyStore"]
