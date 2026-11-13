"""SLICE-052: quota tables enforce tenant isolation in Postgres.

Set TEST_POSTGRES_URL to run these. The test role must be creatable by that
user; the local dev database uses a superuser.
"""

from __future__ import annotations

import asyncio
import os
import urllib.parse

import asyncpg
import pytest

from adk_agent.core import QuotaExceeded, QuotaPolicy
from adk_agent.runtime.quota_postgres import PostgresQuotaManager

DSN = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="TEST_POSTGRES_URL is not set")

APP_ROLE = "adk_quota_rls"
APP_PASSWORD = "x"


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _app_dsn(dsn: str) -> str:
    parts = urllib.parse.urlsplit(dsn)
    netloc = f"{APP_ROLE}:{APP_PASSWORD}@{parts.hostname}"
    if parts.port:
        netloc += f":{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


async def _prepare() -> str:
    assert DSN is not None
    conn = await asyncpg.connect(DSN)
    try:
        exists = await conn.fetchval("select 1 from pg_roles where rolname = $1", APP_ROLE)
        if not exists:
            await conn.execute(
                f"CREATE ROLE \"{APP_ROLE}\" LOGIN PASSWORD '{APP_PASSWORD}' "
                "NOSUPERUSER NOBYPASSRLS"
            )
        else:
            await conn.execute(f"ALTER ROLE \"{APP_ROLE}\" PASSWORD '{APP_PASSWORD}'")
        await conn.execute(f'GRANT ALL ON SCHEMA public TO "{APP_ROLE}"')
        await conn.execute("DROP TABLE IF EXISTS adk_quota_runs")
        await conn.execute("DROP TABLE IF EXISTS adk_quota_leases")
    finally:
        await conn.close()
    return _app_dsn(DSN)


async def _manager(dsn: str) -> PostgresQuotaManager:
    manager = PostgresQuotaManager(dsn, clock=Clock())
    async with manager.reserve("prepare", QuotaPolicy(max_runs=1)):
        pass
    return manager


def test_manager_enables_rls_policies():
    async def scenario() -> None:
        app_dsn = await _prepare()
        await _manager(app_dsn)
        conn = await asyncpg.connect(app_dsn)
        try:
            rows = await conn.fetch(
                "select tablename from pg_policies "
                "where schemaname = 'public' "
                "and tablename in ('adk_quota_runs', 'adk_quota_leases')"
            )
        finally:
            await conn.close()
        assert {row["tablename"] for row in rows} == {"adk_quota_runs", "adk_quota_leases"}

    asyncio.run(scenario())


def test_runs_are_hidden_without_tenant_setting():
    async def scenario() -> None:
        app_dsn = await _prepare()
        manager = PostgresQuotaManager(app_dsn, clock=Clock())
        async with manager.reserve("tenant-a", QuotaPolicy(max_runs=1)):
            pass
        conn = await asyncpg.connect(app_dsn)
        try:
            assert await conn.fetchval("select count(*) from adk_quota_runs") == 0
            await conn.execute("select set_config('app.tenant_id', $1, false)", "tenant-a")
            assert await conn.fetchval("select count(*) from adk_quota_runs") == 1
            await conn.execute("select set_config('app.tenant_id', $1, false)", "tenant-b")
            assert await conn.fetchval("select count(*) from adk_quota_runs") == 0
        finally:
            await conn.close()

    asyncio.run(scenario())


def test_leases_are_hidden_without_tenant_setting():
    async def scenario() -> None:
        app_dsn = await _prepare()
        manager = PostgresQuotaManager(app_dsn, clock=Clock())
        async with manager.reserve("tenant-a", QuotaPolicy(max_concurrent=1)):
            conn = await asyncpg.connect(app_dsn)
            try:
                assert await conn.fetchval("select count(*) from adk_quota_leases") == 0
                await conn.execute("select set_config('app.tenant_id', $1, false)", "tenant-a")
                assert await conn.fetchval("select count(*) from adk_quota_leases") == 1
                await conn.execute("select set_config('app.tenant_id', $1, false)", "tenant-b")
                assert await conn.fetchval("select count(*) from adk_quota_leases") == 0
            finally:
                await conn.close()

    asyncio.run(scenario())


def test_manager_still_enforces_limits_under_rls():
    async def scenario() -> None:
        app_dsn = await _prepare()
        manager = PostgresQuotaManager(app_dsn, clock=Clock())
        policy = QuotaPolicy(max_runs=1, window_seconds=60)
        async with manager.reserve("tenant-a", policy):
            pass
        with pytest.raises(QuotaExceeded):
            async with manager.reserve("tenant-a", policy):
                pass
        async with manager.reserve("tenant-b", policy):
            pass

    asyncio.run(scenario())
