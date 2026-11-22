"""Postgres-backed global default model config shared across replicas."""

from __future__ import annotations

from typing import Any

from ..models.config_store import ModelConfigStoreUnavailable
from ..pg import LazyPool, normalize_dsn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adk_model_config (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL
)
"""

_KEY = "default"


async def _ensure_schema(pool: Any) -> None:
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)


class PostgresModelConfigStore:
    """One global default model string in ``adk_model_config``."""

    def __init__(self, url: str) -> None:
        self._dsn = normalize_dsn(url, what="model config", unavailable=ModelConfigStoreUnavailable)
        self._pool = LazyPool(
            self._dsn,
            what="model config",
            unavailable=ModelConfigStoreUnavailable,
            setup=_ensure_schema,
        )

    async def get(self) -> str | None:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                return await conn.fetchval(
                    "SELECT value FROM adk_model_config WHERE key = $1", _KEY
                )
        except ModelConfigStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelConfigStoreUnavailable(
                f"model config read failed ({type(exc).__name__})"
            ) from exc

    async def put(self, model: str) -> str:
        try:
            pool = await self._pool.get()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO adk_model_config (key, value, updated_at) "
                    "VALUES ($1, $2, now()) "
                    "ON CONFLICT (key) DO UPDATE SET "
                    "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
                    _KEY,
                    model,
                )
        except ModelConfigStoreUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelConfigStoreUnavailable(
                f"model config write failed ({type(exc).__name__})"
            ) from exc
        return model

    async def aclose(self) -> None:
        await self._pool.close()


__all__ = ["PostgresModelConfigStore"]
