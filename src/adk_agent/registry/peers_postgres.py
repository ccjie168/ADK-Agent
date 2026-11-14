"""Postgres-backed peer identities shared across replicas (ADR-0014)."""

from __future__ import annotations

import json
from typing import Any

from ..core import PeerIdentity, PeerStoreError, PeerStoreUnavailable
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_peers (
    peer_id text PRIMARY KEY,
    tenant text NOT NULL,
    subject text NOT NULL,
    kind text NOT NULL,
    roles jsonb NOT NULL DEFAULT '[]',
    enabled boolean NOT NULL DEFAULT true
)
"""

_UPSERT = """
INSERT INTO adk_peers (peer_id, tenant, subject, kind, roles, enabled)
VALUES ($1, $2, $3, $4, $5::jsonb, $6)
ON CONFLICT (peer_id) DO UPDATE SET
    tenant = EXCLUDED.tenant,
    subject = EXCLUDED.subject,
    kind = EXCLUDED.kind,
    roles = EXCLUDED.roles,
    enabled = EXCLUDED.enabled
"""

_SELECT = "SELECT peer_id, tenant, subject, kind, roles, enabled FROM adk_peers WHERE peer_id = $1"
_SELECT_SUBJECT = (
    "SELECT peer_id, tenant, subject, kind, roles, enabled FROM adk_peers WHERE subject = $1"
)
_SELECT_ALL = "SELECT peer_id, tenant, subject, kind, roles, enabled FROM adk_peers"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


def _parse(row: Any) -> PeerIdentity:
    return PeerIdentity(
        peer_id=row["peer_id"],
        tenant=row["tenant"],
        subject=row["subject"],
        kind=row["kind"],
        roles=json.loads(row["roles"]) if row["roles"] else [],
        enabled=row["enabled"],
    )


class PostgresPeerStore:
    """One row per peer in ``adk_peers``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="peers", unavailable=PeerStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="peers",
            unavailable=PeerStoreUnavailable,
            setup=_ensure_schema,
        )

    async def get(self, peer_id: str) -> PeerIdentity | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT, peer_id)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer read failed ({type(exc).__name__})") from exc
        return None if row is None else _parse(row)

    async def get_by_subject(self, subject: str) -> PeerIdentity | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(_SELECT_SUBJECT, subject)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer read failed ({type(exc).__name__})") from exc
        return None if row is None else _parse(row)

    async def list(self) -> list[PeerIdentity]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(_SELECT_ALL)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer read failed ({type(exc).__name__})") from exc
        records = [_parse(row) for row in rows]
        records.sort(key=lambda record: record.peer_id)
        return records

    async def put(self, identity: PeerIdentity) -> PeerIdentity:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    _UPSERT,
                    identity.peer_id,
                    identity.tenant,
                    identity.subject,
                    identity.kind,
                    json.dumps(identity.roles),
                    identity.enabled,
                )
                row = await conn.fetchrow(_SELECT, identity.peer_id)
        except PeerStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise PeerStoreUnavailable(f"peer write failed ({type(exc).__name__})") from exc
        if row is None:
            raise PeerStoreUnavailable("peer disappeared during write")
        return _parse(row)


__all__ = ["PostgresPeerStore"]
