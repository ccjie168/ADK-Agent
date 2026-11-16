"""Postgres-backed tenant credential bindings shared across replicas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core import (
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStoreError,
    CredentialStoreUnavailable,
)
from ..pg import LazyPool, normalize_dsn
from .credentials import _definition

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_credentials (
    tenant text,
    credential_id text,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, credential_id)
)
"""

_SELECT = "SELECT definition FROM adk_credentials WHERE tenant = $1 AND credential_id = $2"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresCredentialStore:
    """One binding per ``(tenant, credential_id)`` in ``adk_credentials``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="credential", unavailable=CredentialStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="credential",
            unavailable=CredentialStoreUnavailable,
            setup=_ensure_schema,
        )

    async def add(self, binding: CredentialBinding) -> CredentialBinding:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_credentials (tenant, credential_id, definition, updated_at) "
                    "VALUES ($1, $2, $3::jsonb, $4) "
                    "ON CONFLICT (tenant, credential_id) DO NOTHING",
                    binding.tenant,
                    binding.credential_id,
                    binding.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                stored = await conn.fetchval(_SELECT, binding.tenant, binding.credential_id)
        except CredentialStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable(
                f"credential write failed ({type(exc).__name__})"
            ) from exc
        existing = self._parse(stored, binding.tenant, binding.credential_id)
        if _definition(existing) != _definition(binding):
            raise CredentialConflict(
                f"credential {binding.tenant}/{binding.credential_id} "
                "already has a different definition"
            )
        return existing

    async def get(self, tenant: str, credential_id: str) -> CredentialBinding | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT, tenant, credential_id)
        except CredentialStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable(
                f"credential read failed ({type(exc).__name__})"
            ) from exc
        if stored is None:
            return None
        return self._parse(stored, tenant, credential_id)

    async def list(self, tenant: str) -> list[CredentialBinding]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_credentials "
                    "WHERE tenant = $1 ORDER BY credential_id",
                    tenant,
                )
        except CredentialStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable(
                f"credential read failed ({type(exc).__name__})"
            ) from exc
        return [self._parse(row["definition"], tenant, "list") for row in rows]

    async def disable(self, tenant: str, credential_id: str, *, by: str) -> CredentialBinding:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn, conn.transaction():
                row = await conn.fetchval(_SELECT, tenant, credential_id)
                if row is None:
                    raise CredentialNotFound(f"credential not found: {tenant}/{credential_id}")
                binding = self._parse(row, tenant, credential_id)
                if not binding.enabled:
                    return binding
                disabled = binding.model_copy(update={"enabled": False})
                await conn.execute(
                    "UPDATE adk_credentials SET definition = $3::jsonb, updated_at = $4 "
                    "WHERE tenant = $1 AND credential_id = $2",
                    tenant,
                    credential_id,
                    disabled.model_dump_json(),
                    datetime.now(timezone.utc),
                )
                return disabled
        except CredentialStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreUnavailable(
                f"credential write failed ({type(exc).__name__})"
            ) from exc

    async def aclose(self) -> None:
        await self._pool.close()

    def _parse(self, raw: str | None, tenant: str, credential_id: str) -> CredentialBinding:
        if raw is None:
            raise CredentialConflict(
                f"credential disappeared during write: {tenant}/{credential_id}"
            )
        try:
            return CredentialBinding.model_validate_json(raw)
        except ValueError as exc:
            raise CredentialStoreError(
                f"{tenant}/{credential_id}: invalid credential record"
            ) from exc


__all__ = ["PostgresCredentialStore"]
