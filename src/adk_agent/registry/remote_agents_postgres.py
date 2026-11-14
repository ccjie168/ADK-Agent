"""Postgres-backed remote A2A agent records shared across replicas (ADR-0015)."""

from __future__ import annotations

from typing import Any

from ..core import RemoteAgent, RemoteAgentStoreUnavailable
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_remote_agents (
    remote_id text PRIMARY KEY,
    tenant text NOT NULL,
    peer_id text NOT NULL,
    agent_card_url text NOT NULL,
    credential_ref text,
    label text NOT NULL DEFAULT '',
    card_digest text NOT NULL,
    observed_digest text,
    checked_at timestamptz NOT NULL,
    status text NOT NULL,
    enabled boolean NOT NULL DEFAULT true
)
"""

_UPSERT = """
INSERT INTO adk_remote_agents (
    remote_id, tenant, peer_id, agent_card_url, credential_ref, label,
    card_digest, observed_digest, checked_at, status, enabled
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
ON CONFLICT (remote_id) DO UPDATE SET
    tenant = EXCLUDED.tenant,
    peer_id = EXCLUDED.peer_id,
    agent_card_url = EXCLUDED.agent_card_url,
    credential_ref = EXCLUDED.credential_ref,
    label = EXCLUDED.label,
    card_digest = EXCLUDED.card_digest,
    observed_digest = EXCLUDED.observed_digest,
    checked_at = EXCLUDED.checked_at,
    status = EXCLUDED.status,
    enabled = EXCLUDED.enabled
"""

_SELECT = """
SELECT remote_id, tenant, peer_id, agent_card_url, credential_ref, label,
       card_digest, observed_digest, checked_at, status, enabled
FROM adk_remote_agents WHERE remote_id = $1
"""
_SELECT_ALL = """
SELECT remote_id, tenant, peer_id, agent_card_url, credential_ref, label,
       card_digest, observed_digest, checked_at, status, enabled
FROM adk_remote_agents
"""


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(row: Any) -> RemoteAgent:
    return RemoteAgent(
        remote_id=row["remote_id"],
        tenant=row["tenant"],
        peer_id=row["peer_id"],
        agent_card_url=row["agent_card_url"],
        credential_ref=row["credential_ref"],
        label=row["label"],
        card_digest=row["card_digest"],
        observed_digest=row["observed_digest"],
        checked_at=row["checked_at"],
        status=row["status"],
        enabled=row["enabled"],
    )


class PostgresRemoteAgentStore:
    """One row per remote agent in ``adk_remote_agents``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(
            url, what="remote agents", unavailable=RemoteAgentStoreUnavailable
        )
        self._pool = LazyPool(
            self._dsn,
            what="remote agents",
            unavailable=RemoteAgentStoreUnavailable,
            setup=_ensure_schema,
        )

    async def get(self, remote_id: str) -> RemoteAgent | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, remote_id)
        except RemoteAgentStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RemoteAgentStoreUnavailable(
                f"remote agent read failed ({type(exc).__name__})"
            ) from exc
        return None if row is None else _parse(row)

    async def list(self) -> list[RemoteAgent]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_ALL)
        except RemoteAgentStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RemoteAgentStoreUnavailable(
                f"remote agent read failed ({type(exc).__name__})"
            ) from exc
        records = [_parse(row) for row in rows]
        records.sort(key=lambda record: record.remote_id)
        return records

    async def put(self, record: RemoteAgent) -> RemoteAgent:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    _UPSERT,
                    record.remote_id,
                    record.tenant,
                    record.peer_id,
                    record.agent_card_url,
                    record.credential_ref,
                    record.label,
                    record.card_digest,
                    record.observed_digest,
                    record.checked_at,
                    record.status,
                    record.enabled,
                )
                row = await conn.fetchrow(_SELECT, record.remote_id)
        except RemoteAgentStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RemoteAgentStoreUnavailable(
                f"remote agent write failed ({type(exc).__name__})"
            ) from exc
        if row is None:
            raise RemoteAgentStoreUnavailable("remote agent disappeared during write")
        return _parse(row)


__all__ = ["PostgresRemoteAgentStore"]
