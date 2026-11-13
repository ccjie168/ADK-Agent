"""Postgres-backed registry shared across replicas."""

from __future__ import annotations

import builtins
from typing import Any

from ..core import AgentRef, PublishedAgent, manifest_digest
from ..pg import LazyPool, normalize_dsn
from .file import RegistryConflict, RegistryError, RegistryIntegrityError

_INSTALL_HINT = "install asyncpg with: pip install asyncpg"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_agent_versions (
    tenant text NOT NULL,
    agent_id text NOT NULL,
    version text NOT NULL,
    digest text NOT NULL,
    artifact_digest text,
    record jsonb NOT NULL,
    published_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, agent_id, version)
);
CREATE INDEX IF NOT EXISTS adk_agent_versions_tenant_idx
    ON adk_agent_versions (tenant, published_at DESC)
"""

_SELECT_RECORD = (
    "SELECT record FROM adk_agent_versions WHERE tenant = $1 AND agent_id = $2 AND version = $3"
)


class RegistryStoreUnavailable(RegistryError):
    """The shared registry backend cannot be reached or lacks its driver."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{reason}; {_INSTALL_HINT}")


def _dsn(url: str) -> str:
    return normalize_dsn(url, what="registry", unavailable=RegistryStoreUnavailable)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresAgentRegistry:
    """Published versions in ``adk_agent_versions``, one row per version."""

    def __init__(self, url: str) -> None:
        self._dsn = _dsn(url)
        self._pool = LazyPool(
            self._dsn,
            what="registry",
            unavailable=RegistryStoreUnavailable,
            setup=_ensure_schema,
        )

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        manifest = agent.manifest
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_agent_versions "
                    "(tenant, agent_id, version, digest, artifact_digest, record, published_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7) "
                    "ON CONFLICT (tenant, agent_id, version) DO NOTHING",
                    manifest.tenant,
                    manifest.id,
                    manifest.version,
                    agent.digest,
                    agent.artifact.digest if agent.artifact else None,
                    agent.model_dump_json(),
                    agent.published_at,
                )
                stored = await conn.fetchval(
                    _SELECT_RECORD, manifest.tenant, manifest.id, manifest.version
                )
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(
                f"registry publish failed ({type(exc).__name__})"
            ) from exc
        label = f"{manifest.tenant}/{manifest.id}@{manifest.version}"
        existing = self._parse(stored, label)
        if existing.digest != agent.digest:
            raise RegistryConflict(f"{label} already published with digest {existing.digest}")
        return existing

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(_SELECT_RECORD, tenant, ref.id, ref.version)
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(f"registry read failed ({type(exc).__name__})") from exc
        if stored is None:
            return None
        published = self._parse(stored, f"{tenant}/{ref.id}@{ref.version}")
        if (
            published.manifest.tenant != tenant
            or published.manifest.id != ref.id
            or published.manifest.version != ref.version
            or published.digest != ref.digest
        ):
            return None
        return published

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT record FROM adk_agent_versions WHERE tenant = $1 "
                    "ORDER BY agent_id, version",
                    tenant,
                )
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(f"registry read failed ({type(exc).__name__})") from exc
        return [self._parse(row["record"], tenant) for row in rows]

    async def tenants(self) -> builtins.list[str]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT DISTINCT tenant FROM adk_agent_versions ORDER BY tenant"
                )
        except RegistryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RegistryStoreUnavailable(f"registry read failed ({type(exc).__name__})") from exc
        return [row["tenant"] for row in rows]

    def _parse(self, raw: str | None, label: str) -> PublishedAgent:
        if raw is None:
            raise RegistryIntegrityError(f"{label}: record disappeared during publish")
        try:
            published = PublishedAgent.model_validate_json(raw)
        except ValueError as exc:
            raise RegistryIntegrityError(f"{label}: invalid published agent record") from exc
        if manifest_digest(published.manifest) != published.digest:
            raise RegistryIntegrityError(f"{label}: digest does not match its manifest")
        return published


__all__ = ["PostgresAgentRegistry", "RegistryStoreUnavailable"]
