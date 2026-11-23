"""Postgres-backed tenant-scoped user-to-role bindings shared across replicas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    UserBinding,
    UserBindingConflict,
    UserBindingStoreError,
    UserBindingStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_user_bindings (
    tenant text,
    subject text,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, subject)
)
"""

_SELECT = "SELECT definition FROM adk_user_bindings WHERE tenant = $1 AND subject = $2"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresUserBindingStore:
    """One binding per ``(tenant, subject)`` in ``adk_user_bindings``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="user binding", unavailable=UserBindingStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="user binding",
            unavailable=UserBindingStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, binding: UserBinding) -> UserBinding:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_user_bindings (tenant, subject, definition, updated_at) "
                    "VALUES ($1, $2, $3::jsonb, $4) "
                    "ON CONFLICT (tenant, subject) DO NOTHING",
                    binding.tenant,
                    binding.subject,
                    binding.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(_SELECT, binding.tenant, binding.subject)
        except UserBindingStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UserBindingStoreUnavailable(
                f"user binding write failed ({type(exc).__name__})"
            ) from exc
        existing = self._parse(stored, binding.tenant, binding.subject)
        if existing != binding:
            raise UserBindingConflict(
                f"user binding {binding.tenant}/{binding.subject} already has a different role set"
            )
        return existing

    async def get(self, tenant: str, subject: str) -> UserBinding | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, tenant, subject)
        except UserBindingStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UserBindingStoreUnavailable(
                f"user binding read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, tenant, subject)

    async def list(self, tenant: str) -> list[UserBinding]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_user_bindings WHERE tenant = $1 ORDER BY subject",
                    tenant,
                )
        except UserBindingStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UserBindingStoreUnavailable(
                f"user binding read failed ({type(exc).__name__})"
            ) from exc
        return [self._parse(row["definition"], tenant, "list") for row in rows]

    async def delete(self, tenant: str, subject: str) -> bool:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                status = await conn.execute(
                    "DELETE FROM adk_user_bindings WHERE tenant = $1 AND subject = $2",
                    tenant,
                    subject,
                )
        except UserBindingStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UserBindingStoreUnavailable(
                f"user binding write failed ({type(exc).__name__})"
            ) from exc
        return status != "DELETE 0"

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(self, raw: str | None, tenant: str, subject: str) -> UserBinding:
        if raw is None:
            raise UserBindingConflict(f"user binding disappeared during write: {tenant}/{subject}")
        try:
            return UserBinding.model_validate_json(raw)
        except ValueError as exc:
            raise UserBindingStoreError(f"{tenant}/{subject}: invalid user binding record") from exc


__all__ = ["PostgresUserBindingStore"]
