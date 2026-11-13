"""Postgres-backed lifecycle store shared across replicas (ADR-0010)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import AgentLifecycle, LifecycleStatus, LifecycleTransitionError, transition_lifecycle
from ..pg import LazyPool, normalize_dsn
from .file import RegistryError
from .postgres import RegistryStoreUnavailable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_agent_lifecycle (
    tenant text NOT NULL,
    agent_id text NOT NULL,
    version text NOT NULL,
    status text NOT NULL,
    changed_at timestamptz,
    changed_by text,
    reason text,
    PRIMARY KEY (tenant, agent_id, version)
)
"""

_SELECT = (
    "SELECT status, changed_at, changed_by, reason FROM adk_agent_lifecycle "
    "WHERE tenant = $1 AND agent_id = $2 AND version = $3"
)

_SELECT_FOR_UPDATE = _SELECT + " FOR UPDATE"

_INSERT = (
    "INSERT INTO adk_agent_lifecycle "
    "(tenant, agent_id, version, status, changed_at, changed_by, reason) "
    "VALUES ($1, $2, $3, $4, $5, $6, $7) "
    "ON CONFLICT (tenant, agent_id, version) DO NOTHING"
)

_UPDATE = (
    "UPDATE adk_agent_lifecycle SET status = $4, changed_at = $5, changed_by = $6, reason = $7 "
    "WHERE tenant = $1 AND agent_id = $2 AND version = $3"
)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(row: Any) -> AgentLifecycle:
    return AgentLifecycle(
        status=row["status"],
        changed_at=row["changed_at"],
        changed_by=row["changed_by"],
        reason=row["reason"] or "",
    )


class PostgresAgentLifecycleStore:
    """One current lifecycle row per version in ``adk_agent_lifecycle``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="lifecycle", unavailable=RegistryStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="lifecycle",
            unavailable=RegistryStoreUnavailable,
            setup=_ensure_schema,
        )

    async def get(self, tenant: str, agent_id: str, version: str) -> AgentLifecycle:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, tenant, agent_id, version)
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(f"lifecycle read failed ({type(exc).__name__})") from exc
        if row is None:
            return AgentLifecycle.default()
        return _parse(row)

    async def set(
        self,
        tenant: str,
        agent_id: str,
        version: str,
        *,
        status: LifecycleStatus,
        changed_by: str,
        reason: str,
    ) -> AgentLifecycle:
        now = datetime.now(timezone.utc)
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow(_SELECT_FOR_UPDATE, tenant, agent_id, version)
                if row is None:
                    initial = transition_lifecycle(
                        AgentLifecycle.default(),
                        status,
                        changed_by=changed_by,
                        reason=reason,
                        now=now,
                    )
                    await conn.execute(
                        _INSERT,
                        tenant,
                        agent_id,
                        version,
                        initial.status,
                        initial.changed_at,
                        initial.changed_by,
                        initial.reason,
                    )
                    row = await conn.fetchrow(_SELECT_FOR_UPDATE, tenant, agent_id, version)
                if row is None:
                    raise RegistryStoreUnavailable("lifecycle row disappeared during write")
                current = _parse(row)
                record = transition_lifecycle(
                    current, status, changed_by=changed_by, reason=reason, now=now
                )
                if record is current:
                    return current
                await conn.execute(
                    _UPDATE,
                    tenant,
                    agent_id,
                    version,
                    record.status,
                    record.changed_at,
                    record.changed_by,
                    record.reason,
                )
                return record
        except (RegistryError, LifecycleTransitionError):
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(
                f"lifecycle write failed ({type(exc).__name__})"
            ) from exc


__all__ = ["PostgresAgentLifecycleStore"]
