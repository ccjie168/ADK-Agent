"""Postgres-backed connector registry shared across replicas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    ConnectorConflict,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStoreError,
    ConnectorStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn
from .connectors import _definition
from .postgres import RegistryStoreUnavailable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_connectors (
    connector_id text PRIMARY KEY,
    tenant text,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL
)
"""

_SELECT = "SELECT definition FROM adk_connectors WHERE connector_id = $1"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresConnectorStore:
    """One definition per connector id in ``adk_connectors``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="connector", unavailable=RegistryStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="connector",
            unavailable=RegistryStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, spec: ConnectorSpec) -> ConnectorSpec:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_connectors (connector_id, tenant, definition, updated_at) "
                    "VALUES ($1, $2, $3::jsonb, $4) ON CONFLICT (connector_id) DO NOTHING",
                    spec.connector_id,
                    spec.tenant,
                    spec.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(_SELECT, spec.connector_id)
        except ConnectorStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorStoreUnavailable(
                f"connector write failed ({type(exc).__name__})"
            ) from exc
        existing = self._parse(stored, spec.connector_id)
        if _definition(existing) != _definition(spec):
            raise ConnectorConflict(
                f"connector {spec.connector_id} already has a different definition"
            )
        return existing

    async def get(self, connector_id: str) -> ConnectorSpec | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, connector_id)
        except ConnectorStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorStoreUnavailable(
                f"connector read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, connector_id)

    async def list(self, tenant: str) -> list[ConnectorSpec]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_connectors "
                    "WHERE tenant IS NULL OR tenant = $1 ORDER BY connector_id",
                    tenant,
                )
        except ConnectorStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorStoreUnavailable(
                f"connector read failed ({type(exc).__name__})"
            ) from exc
        return [self._parse(row["definition"], tenant) for row in rows]

    async def disable(self, connector_id: str, *, by: str) -> ConnectorSpec:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchval(_SELECT, connector_id)
                if row is None:
                    raise ConnectorNotFound(f"connector not found: {connector_id}")
                spec = self._parse(row, connector_id)
                if not spec.enabled:
                    return spec
                disabled = spec.model_copy(update={"enabled": False})
                await conn.execute(
                    "UPDATE adk_connectors SET definition = $2::jsonb, updated_at = $3 "
                    "WHERE connector_id = $1",
                    connector_id,
                    disabled.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                return disabled
        except ConnectorStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConnectorStoreUnavailable(
                f"connector write failed ({type(exc).__name__})"
            ) from exc

    def _parse(self, raw: str | None, label: str) -> ConnectorSpec:
        if raw is None:
            raise ConnectorConflict(f"connector disappeared during write: {label}")
        try:
            return ConnectorSpec.model_validate_json(raw)
        except ValueError as exc:
            raise ConnectorStoreError(f"{label}: invalid connector record") from exc


__all__ = ["PostgresConnectorStore"]
