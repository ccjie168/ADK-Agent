"""Postgres-backed peer grants shared across replicas (ADR-0014)."""

from __future__ import annotations

import json
from typing import Any

from ..core import PeerGrant, PeerStoreError, PeerStoreUnavailable
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_peer_grants (
    peer_id text NOT NULL,
    agent_id text NOT NULL,
    tenant text NOT NULL,
    actions jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY (peer_id, agent_id)
)
"""

_UPSERT = """
INSERT INTO adk_peer_grants (peer_id, agent_id, tenant, actions)
VALUES ($1, $2, $3, $4::jsonb)
ON CONFLICT (peer_id, agent_id) DO UPDATE SET
    tenant = EXCLUDED.tenant,
    actions = EXCLUDED.actions
"""

_SELECT = (
    "SELECT peer_id, agent_id, tenant, actions FROM adk_peer_grants "
    "WHERE peer_id = $1 AND agent_id = $2"
)
_SELECT_ALL = "SELECT peer_id, agent_id, tenant, actions FROM adk_peer_grants"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(row: Any) -> PeerGrant:
    return PeerGrant(
        peer_id=row["peer_id"],
        agent_id=row["agent_id"],
        tenant=row["tenant"],
        actions=json.loads(row["actions"]) if row["actions"] else [],
    )


class PostgresPeerGrantStore:
    """One row per (peer, agent) grant in ``adk_peer_grants``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="peer grants", unavailable=PeerStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="peer grants",
            unavailable=PeerStoreUnavailable,
            setup=_ensure_schema,
        )

    async def get(self, peer_id: str, agent_id: str) -> PeerGrant | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, peer_id, agent_id)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer grant read failed ({type(exc).__name__})") from exc
        return None if row is None else _parse(row)

    async def list(self) -> list[PeerGrant]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_ALL)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer grant read failed ({type(exc).__name__})") from exc
        records = [_parse(row) for row in rows]
        records.sort(key=lambda record: (record.peer_id, record.agent_id))
        return records

    async def put(self, grant: PeerGrant) -> PeerGrant:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    _UPSERT,
                    grant.peer_id,
                    grant.agent_id,
                    grant.tenant,
                    json.dumps(grant.actions),
                )
                row = await conn.fetchrow(_SELECT, grant.peer_id, grant.agent_id)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer grant write failed ({type(exc).__name__})") from exc
        if row is None:
            raise PeerStoreUnavailable("peer grant disappeared during write")
        return _parse(row)


__all__ = ["PostgresPeerGrantStore"]
