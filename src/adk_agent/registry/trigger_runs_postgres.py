"""Postgres-backed trigger fire records shared across replicas (SLICE-125)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    TriggerFire,
    TriggerFireConflict,
    TriggerFireError,
    TriggerFireStatus,
    TriggerFireStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_trigger_fires (
    tenant text,
    trigger_id text,
    idempotency_key text,
    record jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, trigger_id, idempotency_key)
)
"""

_SELECT = (
    "SELECT record FROM adk_trigger_fires "
    "WHERE tenant = $1 AND trigger_id = $2 AND idempotency_key = $3"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresTriggerFireStore:
    """One fire per ``(tenant, trigger_id, idempotency_key)`` in ``adk_trigger_fires``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="trigger fire", unavailable=TriggerFireStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="trigger fire",
            unavailable=TriggerFireStoreUnavailable,
            setup=_ensure_schema,
        )

    async def claim(self, fire: TriggerFire) -> TriggerFire:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_trigger_fires "
                    "(tenant, trigger_id, idempotency_key, record, updated_at) "
                    "VALUES ($1, $2, $3, $4::jsonb, $5) "
                    "ON CONFLICT (tenant, trigger_id, idempotency_key) DO NOTHING",
                    fire.tenant,
                    fire.trigger_id,
                    fire.idempotency_key,
                    fire.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(
                    _SELECT, fire.tenant, fire.trigger_id, fire.idempotency_key
                )
        except TriggerFireError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerFireStoreUnavailable(
                f"trigger fire write failed ({type(exc).__name__})"
            ) from exc
        return self._parse(stored, fire.tenant, fire.trigger_id, fire.idempotency_key)

    async def finish(
        self,
        tenant: str,
        trigger_id: str,
        idempotency_key: str,
        *,
        status: TriggerFireStatus,
        error_code: str | None = None,
        finished_at: datetime | None = None,
    ) -> TriggerFire:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                raw = await conn.fetchval(_SELECT, tenant, trigger_id, idempotency_key)
                if raw is None:
                    raise TriggerFireConflict(
                        f"trigger fire not found: {tenant}/{trigger_id}/{idempotency_key}"
                    )
                existing = self._parse(raw, tenant, trigger_id, idempotency_key)
                updated = existing.model_copy(
                    update={
                        "status": status,
                        "error_code": error_code,
                        "finished_at": finished_at or datetime.now(timezone.utc),
                    }
                )
                stored = await conn.fetchval(
                    "UPDATE adk_trigger_fires SET record = $4::jsonb, updated_at = $5 "
                    "WHERE tenant = $1 AND trigger_id = $2 AND idempotency_key = $3 "
                    "RETURNING record",
                    tenant,
                    trigger_id,
                    idempotency_key,
                    updated.model_dump_json(),
                    datetime.now(timezone.utc),
                )
        except TriggerFireError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerFireStoreUnavailable(
                f"trigger fire write failed ({type(exc).__name__})"
            ) from exc
        return self._parse(stored, tenant, trigger_id, idempotency_key)

    async def get(self, tenant: str, trigger_id: str, idempotency_key: str) -> TriggerFire | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, tenant, trigger_id, idempotency_key)
        except TriggerFireError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerFireStoreUnavailable(
                f"trigger fire read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, tenant, trigger_id, idempotency_key)

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(
        self, raw: str | None, tenant: str, trigger_id: str, idempotency_key: str
    ) -> TriggerFire:
        if raw is None:
            raise TriggerFireConflict(
                f"trigger fire disappeared: {tenant}/{trigger_id}/{idempotency_key}"
            )
        try:
            return TriggerFire.model_validate_json(raw)
        except ValueError as exc:
            raise TriggerFireError(
                f"{tenant}/{trigger_id}/{idempotency_key}: invalid trigger fire record"
            ) from exc


__all__ = ["PostgresTriggerFireStore"]
