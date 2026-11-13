"""Lazy asyncpg pooling shared by the Postgres-backed adapters.

The shared stores keep their own error types, so the pool takes the error
class to raise and the noun used in its messages.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

POSTGRES_PREFIX = "postgresql://"
ASYNC_PREFIX = "postgresql+asyncpg://"

Setup = Callable[[Any], Awaitable[None]]


def normalize_dsn(url: str, *, what: str, unavailable: type[Exception]) -> str:
    if url.startswith(ASYNC_PREFIX):
        return POSTGRES_PREFIX + url[len(ASYNC_PREFIX) :]
    if url.startswith(POSTGRES_PREFIX):
        return url
    raise unavailable(f"unsupported {what} URL (expected postgresql:// or postgresql+asyncpg://)")


def require_asyncpg(*, what: str, unavailable: type[Exception]) -> Any:
    try:
        return importlib.import_module("asyncpg")
    except ImportError as exc:
        raise unavailable("asyncpg is not installed") from exc


class LazyPool:
    """Open one pool per event loop, on first use, and run the schema setup."""

    def __init__(
        self,
        dsn: str,
        *,
        what: str,
        unavailable: type[Exception],
        setup: Setup,
    ) -> None:
        self._dsn = dsn
        self._what = what
        self._unavailable = unavailable
        self._setup = setup
        self._pool: Any | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None

    async def get(self) -> Any:
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
            pool = await self._open()
            self._pool = pool
            self._pool_loop = loop
            return pool

    async def close(self) -> None:
        pool = self._pool
        self._pool = None
        self._pool_loop = None
        if pool is not None:
            await pool.close()

    async def _open(self) -> Any:
        asyncpg = require_asyncpg(what=self._what, unavailable=self._unavailable)
        try:
            pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        except Exception as exc:  # noqa: BLE001
            raise self._unavailable(
                f"could not open the {self._what} database ({type(exc).__name__})"
            ) from exc
        try:
            await self._setup(pool)
        except Exception as exc:  # noqa: BLE001
            try:
                await pool.close()
            except Exception:  # noqa: BLE001
                logger.exception("failed to close the %s pool during setup", self._what)
            raise self._unavailable(
                f"could not initialize the {self._what} schema ({type(exc).__name__})"
            ) from exc
        return pool


__all__ = ["LazyPool", "normalize_dsn", "require_asyncpg"]
