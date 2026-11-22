"""Postgres-backed quota counters shared across replicas."""

from __future__ import annotations

import importlib
import logging
import time
import uuid
from collections.abc import Callable
from types import TracebackType
from typing import Any

from ..core import QuotaExceeded, QuotaManager, QuotaPolicy, QuotaUsage
from ..pg import LazyPool
from .quota import InMemoryQuotaManager

logger = logging.getLogger(__name__)

_INSTALL_HINT = "install asyncpg with: pip install asyncpg"
_POSTGRES_PREFIX = "postgresql://"
_ASYNC_PREFIX = "postgresql+asyncpg://"


class QuotaStoreUnavailable(RuntimeError):
    """The shared quota backend cannot be reached or lacks its driver."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{reason}; {_INSTALL_HINT}")


def _import_module(name: str) -> Any:
    return importlib.import_module(name)


def build_quota_manager(url: str | None) -> QuotaManager:
    """Pick the in-memory store for an empty URL, else a Postgres store."""
    if not url:
        return InMemoryQuotaManager()
    if url.startswith(_ASYNC_PREFIX):
        dsn = _POSTGRES_PREFIX + url[len(_ASYNC_PREFIX) :]
    elif url.startswith(_POSTGRES_PREFIX):
        dsn = url
    else:
        raise QuotaStoreUnavailable(
            "unsupported quota URL (expected postgresql:// or postgresql+asyncpg://)"
        )
    try:
        _import_module("asyncpg")
    except ImportError as exc:
        raise QuotaStoreUnavailable("asyncpg is not installed") from exc
    return PostgresQuotaManager(dsn)


class PostgresQuotaManager:
    """Run counts and concurrency leases in one database, shared by replicas.

    ``clock`` must be a wall clock because the counters are read by other
    processes. A crashed replica keeps its concurrency lease until
    ``lease_seconds`` passes.
    """

    def __init__(
        self,
        dsn: str,
        *,
        clock: Callable[[], float] = time.time,
        lease_seconds: float = 300.0,
    ) -> None:
        self._dsn = dsn
        self._clock = clock
        self._lease_seconds = lease_seconds
        self._pool = LazyPool(
            dsn,
            what="quota",
            unavailable=QuotaStoreUnavailable,
            setup=self._ensure_schema,
        )

    def reserve(self, tenant: str, policy: QuotaPolicy) -> _Reservation:
        return _Reservation(self, tenant, policy)

    async def _ensure_pool(self) -> Any:
        return await self._pool.get()

    async def _ensure_schema(self, pool: Any) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS adk_quota_runs "
                "(tenant text NOT NULL, ran_at double precision NOT NULL)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS adk_quota_runs_tenant_ran_at "
                "ON adk_quota_runs (tenant, ran_at)"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS adk_quota_leases "
                "(lease_id text PRIMARY KEY, tenant text NOT NULL, "
                "expires_at double precision NOT NULL)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS adk_quota_leases_tenant_expires_at "
                "ON adk_quota_leases (tenant, expires_at)"
            )
            for table in ("adk_quota_runs", "adk_quota_leases"):
                await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                await conn.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
                await conn.execute(f"DROP POLICY IF EXISTS {table}_tenant ON {table}")
                await conn.execute(
                    f"CREATE POLICY {table}_tenant ON {table} "
                    "USING (tenant = current_setting('app.tenant_id', true)) "
                    "WITH CHECK (tenant = current_setting('app.tenant_id', true))"
                )

    async def _enter(self, tenant: str, policy: QuotaPolicy) -> str | None:
        pool = await self._ensure_pool()
        now = float(self._clock())
        lease_id: str | None = uuid.uuid4().hex
        try:
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('adk_quota'), hashtext($1))",
                    tenant,
                )
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
                await conn.execute(
                    "DELETE FROM adk_quota_leases WHERE tenant = $1 AND expires_at <= $2",
                    tenant,
                    now,
                )
                if policy.max_runs is not None:
                    await conn.execute(
                        "DELETE FROM adk_quota_runs WHERE tenant = $1 AND ran_at <= $2",
                        tenant,
                        now - policy.window_seconds,
                    )
                    used = await conn.fetchval(
                        "SELECT count(*) FROM adk_quota_runs WHERE tenant = $1", tenant
                    )
                    if used >= policy.max_runs:
                        raise QuotaExceeded(tenant, "max_runs")
                    await conn.execute(
                        "INSERT INTO adk_quota_runs (tenant, ran_at) VALUES ($1, $2)",
                        tenant,
                        now,
                    )
                if policy.max_concurrent is not None:
                    active = await conn.fetchval(
                        "SELECT count(*) FROM adk_quota_leases "
                        "WHERE tenant = $1 AND expires_at > $2",
                        tenant,
                        now,
                    )
                    if active >= policy.max_concurrent:
                        raise QuotaExceeded(tenant, "max_concurrent")
                    await conn.execute(
                        "INSERT INTO adk_quota_leases (lease_id, tenant, expires_at) "
                        "VALUES ($1, $2, $3)",
                        lease_id,
                        tenant,
                        now + self._lease_seconds,
                    )
                else:
                    lease_id = None
        except QuotaExceeded:
            raise
        except Exception as exc:  # noqa: BLE001
            raise QuotaStoreUnavailable(f"quota transaction failed ({type(exc).__name__})") from exc
        return lease_id

    async def _release(self, lease_id: str, tenant: str) -> None:
        try:
            pool = await self._ensure_pool()
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
                await conn.execute(
                    "DELETE FROM adk_quota_leases WHERE lease_id = $1 AND tenant = $2",
                    lease_id,
                    tenant,
                )
        except Exception:  # noqa: BLE001
            logger.exception("failed to release quota lease %s", lease_id)

    async def usage(self, tenant: str, policy: QuotaPolicy) -> QuotaUsage:
        try:
            pool = await self._ensure_pool()
            now = float(self._clock())
            cutoff = now - policy.window_seconds
            async with pool.acquire() as conn, conn.transaction():
                await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
                await conn.execute(
                    "DELETE FROM adk_quota_runs WHERE tenant = $1 AND ran_at <= $2",
                    tenant,
                    cutoff,
                )
                window_runs = await conn.fetchval(
                    "SELECT count(*) FROM adk_quota_runs WHERE tenant = $1", tenant
                )
                await conn.execute(
                    "DELETE FROM adk_quota_leases WHERE tenant = $1 AND expires_at <= $2",
                    tenant,
                    now,
                )
                active_leases = await conn.fetchval(
                    "SELECT count(*) FROM adk_quota_leases WHERE tenant = $1", tenant
                )
            return QuotaUsage(
                window_runs=int(window_runs),
                active_leases=int(active_leases),
                max_runs=policy.max_runs,
                max_concurrent=policy.max_concurrent,
                window_seconds=policy.window_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            raise QuotaStoreUnavailable(f"quota usage failed ({type(exc).__name__})") from exc


class _Reservation:
    def __init__(self, manager: PostgresQuotaManager, tenant: str, policy: QuotaPolicy) -> None:
        self._manager = manager
        self._tenant = tenant
        self._policy = policy
        self._lease_id: str | None = None

    async def __aenter__(self) -> None:
        self._lease_id = await self._manager._enter(self._tenant, self._policy)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        lease_id = self._lease_id
        self._lease_id = None
        if lease_id is not None:
            await self._manager._release(lease_id, self._tenant)


__all__ = ["PostgresQuotaManager", "QuotaStoreUnavailable", "build_quota_manager"]
