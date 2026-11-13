"""Postgres-backed artifact bytes shared across replicas."""

from __future__ import annotations

from typing import Any

from ..core import AgentArtifact
from ..pg import LazyPool, normalize_dsn
from .artifacts import ArtifactStoreError, _hexdigest, _verified_digest

_INSTALL_HINT = "install asyncpg with: pip install asyncpg"

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


def _dsn(url: str) -> str:
    return normalize_dsn(url, what="artifact", unavailable=ArtifactStoreUnavailable)


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresArtifactStore:
    """Artifact bytes in ``adk_artifacts``, one row per digest."""

    def __init__(self, url: str) -> None:
        self._dsn = _dsn(url)
        self._pool = LazyPool(
            self._dsn,
            what="artifact",
            unavailable=ArtifactStoreUnavailable,
            setup=_ensure_schema,
        )

    async def _ensure_pool(self) -> Any:
        return await self._pool.get()

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
