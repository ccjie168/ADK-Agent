"""Postgres-backed global role definitions shared across replicas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import RoleConflict, RoleDefinition, RoleStoreError, RoleStoreUnavailable
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_roles (
    name text PRIMARY KEY,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL
)
"""


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresRoleStore:
    """One role per ``name`` in ``adk_roles`` (global, no tenant)."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="role", unavailable=RoleStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="role",
            unavailable=RoleStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, role: RoleDefinition) -> RoleDefinition:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_roles (name, definition, updated_at) "
                    "VALUES ($1, $2::jsonb, $3) "
                    "ON CONFLICT (name) DO NOTHING",
                    role.name,
                    role.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(
                    "SELECT definition FROM adk_roles WHERE name = $1", role.name
                )
        except RoleStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RoleStoreUnavailable(f"role write failed ({type(exc).__name__})") from exc
        existing = self._parse(stored, role.name)
        if existing != role:
            raise RoleConflict(f"role {role.name!r} already has a different definition")
        return existing

    async def get(self, name: str) -> RoleDefinition | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(
                    "SELECT definition FROM adk_roles WHERE name = $1", name
                )
        except RoleStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RoleStoreUnavailable(f"role read failed ({type(exc).__name__})") from exc
        if stored is None:
            return None
        return self._parse(stored, name)

    async def list(self) -> list[RoleDefinition]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT definition FROM adk_roles ORDER BY name")
        except RoleStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RoleStoreUnavailable(f"role read failed ({type(exc).__name__})") from exc
        return [self._parse(row["definition"], "list") for row in rows]

    async def delete(self, name: str) -> bool:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                status = await conn.execute("DELETE FROM adk_roles WHERE name = $1", name)
        except RoleStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RoleStoreUnavailable(f"role write failed ({type(exc).__name__})") from exc
        return status != "DELETE 0"

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(self, raw: str | None, name: str) -> RoleDefinition:
        if raw is None:
            raise RoleConflict(f"role disappeared during write: {name}")
        try:
            return RoleDefinition.model_validate_json(raw)
        except ValueError as exc:
            raise RoleStoreError(f"{name}: invalid role record") from exc


__all__ = ["PostgresRoleStore"]
