"""Postgres-backed artifact bytes shared across replicas."""

from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any

from ..core import AgentArtifact
from .artifacts import ArtifactStoreError, _hexdigest, _verified_digest

logger = logging.getLogger(__name__)

_INSTALL_HINT = "install asyncpg with: pip install asyncpg"
_POSTGRES_PREFIX = "postgresql://"
_ASYNC_PREFIX = "postgresql+asyncpg://"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_artifacts (
    digest text PRIMARY KEY,
    media_type text NOT NULL,
    size bigint NOT NULL,
    bytes bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


class ArtifactStoreUnavailable(ArtifactStoreError):
    """The shared artifact backend cannot be reached or lacks its driver."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{reason}; {_INSTALL_HINT}")


def _import_module(name: str) -> Any:
    return importlib.import_module(name)


def _dsn(url: str) -> str:
    if url.startswith(_ASYNC_PREFIX):
        return _POSTGRES_PREFIX + url[len(_ASYNC_PREFIX) :]
    if url.startswith(_POSTGRES_PREFIX):
        return url
    raise ArtifactStoreUnavailable(
        "unsupported artifact URL (expected postgresql:// or postgresql+asyncpg://)"
    )


class PostgresArtifactStore:
    """Artifact bytes in ``adk_artifacts``, one row per digest."""

    def __init__(self, url: str) -> None:
        self._dsn = _dsn(url)
        self._pool: Any | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    async def _ensure_pool(self) -> Any:
        loop = asyncio.get_running_loop()
        if self._pool is not None and self._pool_loop is loop:
            return self._pool
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
            self._pool = None
            self._pool_loop = None
        async with self._lock:
            if self._pool is not None and self._pool_loop is loop:
                return self._pool
            pool = await self._open_pool()
            self._pool = pool
            self._pool_loop = loop
            return pool

    async def _open_pool(self) -> Any:
        try:
            asyncpg = _import_module("asyncpg")
        except ImportError as exc:
            raise ArtifactStoreUnavailable("asyncpg is not installed") from exc
        try:
            pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        except Exception as exc:  # noqa: BLE001
            raise ArtifactStoreUnavailable(
                f"could not open the artifact database ({type(exc).__name__})"
            ) from exc
        try:
            async with pool.acquire() as conn:
                await conn.execute(_SCHEMA)
        except Exception as exc:  # noqa: BLE001
            try:
                await pool.close()
            except Exception:  # noqa: BLE001
                logger.exception("failed to close the artifact pool during setup")
            raise ArtifactStoreUnavailable(
                f"could not initialize the artifact schema ({type(exc).__name__})"
            ) from exc
        return pool

    async def put(self, artifact: AgentArtifact, data: bytes) -> None:
        _verified_digest(artifact, data)
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_artifacts (digest, media_type, size, bytes) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT (digest) DO NOTHING",
                    artifact.digest,
                    artifact.media_type,
                    artifact.size,
                    data,
                )
        except ArtifactStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ArtifactStoreUnavailable(f"artifact write failed ({type(exc).__name__})") from exc

    async def get(self, digest: str) -> bytes | None:
        _hexdigest(digest)
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT bytes FROM adk_artifacts WHERE digest = $1", digest
                )
        except ArtifactStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ArtifactStoreUnavailable(f"artifact read failed ({type(exc).__name__})") from exc

    async def has(self, digest: str) -> bool:
        _hexdigest(digest)
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn:
                found = await conn.fetchval("SELECT 1 FROM adk_artifacts WHERE digest = $1", digest)
                return found is not None
        except ArtifactStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ArtifactStoreUnavailable(
                f"artifact lookup failed ({type(exc).__name__})"
            ) from exc


__all__ = ["ArtifactStoreUnavailable", "PostgresArtifactStore"]
