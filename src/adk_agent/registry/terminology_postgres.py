"""Postgres-backed terminology (concept schemes) shared across replicas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..pg import LazyPool, normalize_dsn
from ..semantics import ConceptScheme
from ..semantics.store import ConceptSchemeStoreUnavailable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_terminology (
    tenant text,
    scheme_id text,
    definition jsonb NOT NULL,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant, scheme_id)
)
"""


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresConceptSchemeStore:
    """One scheme per ``(tenant, scheme_id)`` in ``adk_terminology``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(
            url, what="terminology", unavailable=ConceptSchemeStoreUnavailable
        )
        self._pool = LazyPool(
            self._dsn,
            what="terminology",
            unavailable=ConceptSchemeStoreUnavailable,
            setup=_ensure_schema,
        )

    async def put(self, tenant: str, scheme: ConceptScheme) -> ConceptScheme:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_terminology (tenant, scheme_id, definition, updated_at) "
                    "VALUES ($1, $2, $3::jsonb, $4) "
                    "ON CONFLICT (tenant, scheme_id) DO UPDATE SET "
                    "definition = EXCLUDED.definition, updated_at = EXCLUDED.updated_at",
                    tenant,
                    scheme.scheme_id,
                    scheme.model_dump_json(),
                    datetime.now(timezone.utc),
                )
        except ConceptSchemeStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConceptSchemeStoreUnavailable(
                f"terminology write failed ({type(exc).__name__})"
            ) from exc
        return scheme

    async def get(self, tenant: str, scheme_id: str) -> ConceptScheme | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                stored = await conn.fetchval(
                    "SELECT definition FROM adk_terminology WHERE tenant = $1 AND scheme_id = $2",
                    tenant,
                    scheme_id,
                )
        except ConceptSchemeStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConceptSchemeStoreUnavailable(
                f"terminology read failed ({type(exc).__name__})"
            ) from exc
        return None if stored is None else ConceptScheme.model_validate_json(stored)

    async def list(self, tenant: str) -> list[ConceptScheme]:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT definition FROM adk_terminology WHERE tenant = $1 ORDER BY scheme_id",
                    tenant,
                )
        except ConceptSchemeStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ConceptSchemeStoreUnavailable(
                f"terminology read failed ({type(exc).__name__})"
            ) from exc
        return [ConceptScheme.model_validate_json(row["definition"]) for row in rows]

    async def aclose(self) -> None:
        await self._pool.close()


__all__ = ["PostgresConceptSchemeStore"]
