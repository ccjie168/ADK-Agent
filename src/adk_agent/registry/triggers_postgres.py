"""Postgres-backed trigger definitions shared across replicas."""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
from typing import Any

from ..core import (
    AgentTrigger,
    TriggerConflict,
    TriggerError,
    TriggerNotFound,
    TriggerStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn
from .triggers import _definition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_triggers (
    tenant text,
    trigger_id text,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, trigger_id)
)
"""

_SELECT = "SELECT definition FROM adk_triggers WHERE tenant = $1 AND trigger_id = $2"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresTriggerStore:
    """One trigger per ``(tenant, trigger_id)`` in ``adk_triggers``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="trigger", unavailable=TriggerStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="trigger",
            unavailable=TriggerStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, trigger: AgentTrigger) -> AgentTrigger:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_triggers (tenant, trigger_id, definition, updated_at) "
                    "VALUES ($1, $2, $3::jsonb, $4) "
                    "ON CONFLICT (tenant, trigger_id) DO NOTHING",
                    trigger.tenant,
                    trigger.trigger_id,
                    trigger.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(_SELECT, trigger.tenant, trigger.trigger_id)
        except TriggerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerStoreUnavailable(f"trigger write failed ({type(exc).__name__})") from exc
        existing = self._parse(stored, trigger.tenant, trigger.trigger_id)
        if _definition(existing) != _definition(trigger):
            raise TriggerConflict(
                f"trigger {trigger.tenant}/{trigger.trigger_id} already has a different definition"
            )
        return existing

    async def get(self, tenant: str, trigger_id: str) -> AgentTrigger | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, tenant, trigger_id)
        except TriggerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerStoreUnavailable(f"trigger read failed ({type(exc).__name__})") from exc
        if stored is None:
            return None
        return self._parse(stored, tenant, trigger_id)

    async def list(self, tenant: str) -> list[AgentTrigger]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_triggers WHERE tenant = $1 ORDER BY trigger_id",
                    tenant,
                )
        except TriggerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerStoreUnavailable(f"trigger read failed ({type(exc).__name__})") from exc
        return [self._parse(row["definition"], tenant, "list") for row in rows]

    async def list_all(self) -> builtins.list[AgentTrigger]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_triggers ORDER BY tenant, trigger_id"
                )
        except TriggerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerStoreUnavailable(f"trigger read failed ({type(exc).__name__})") from exc
        return [self._parse(row["definition"], "all", "list") for row in rows]

    async def disable(self, tenant: str, trigger_id: str, *, by: str) -> AgentTrigger:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchval(_SELECT, tenant, trigger_id)
                if row is None:
                    raise TriggerNotFound(f"trigger not found: {tenant}/{trigger_id}")
                trigger = self._parse(row, tenant, trigger_id)
                if not trigger.enabled:
                    return trigger
                disabled = trigger.model_copy(update={"enabled": False})
                await conn.execute(
                    "UPDATE adk_triggers SET definition = $3::jsonb, updated_at = $4 "
                    "WHERE tenant = $1 AND trigger_id = $2",
                    tenant,
                    trigger_id,
                    disabled.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                return disabled
        except TriggerError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TriggerStoreUnavailable(f"trigger write failed ({type(exc).__name__})") from exc

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(self, raw: str | None, tenant: str, trigger_id: str) -> AgentTrigger:
        if raw is None:
            raise TriggerConflict(f"trigger disappeared during write: {tenant}/{trigger_id}")
        try:
            return AgentTrigger.model_validate_json(raw)
        except ValueError as exc:
            raise TriggerError(f"{tenant}/{trigger_id}: invalid trigger record") from exc


__all__ = ["PostgresTriggerStore"]
