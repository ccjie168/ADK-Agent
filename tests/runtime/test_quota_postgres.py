"""SLICE-044: quota counters shared across processes.

Set TEST_POSTGRES_URL to run the live cases against a real database.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

import adk_agent.runtime.quota_postgres as quota_postgres
from adk_agent.core import QuotaExceeded, QuotaPolicy
from adk_agent.runtime.quota import InMemoryQuotaManager
from adk_agent.runtime.quota_postgres import (
    PostgresQuotaManager,
    QuotaStoreUnavailable,
    build_quota_manager,
)

_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _manager(clock: Clock, lease_seconds: float = 300.0) -> PostgresQuotaManager:
    assert _LIVE_URL is not None
    return PostgresQuotaManager(_LIVE_URL, clock=clock, lease_seconds=lease_seconds)


def _tenant() -> str:
    return f"slice044-{uuid.uuid4().hex}"


def _consume(manager: PostgresQuotaManager, tenant: str, policy: QuotaPolicy, times: int) -> None:
    async def scenario() -> None:
        for _ in range(times):
            async with manager.reserve(tenant, policy):
                pass

    asyncio.run(scenario())


def test_build_in_memory():
    assert isinstance(build_quota_manager(None), InMemoryQuotaManager)
    assert isinstance(build_quota_manager(""), InMemoryQuotaManager)


@pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")
def test_build_accepts_postgres_postgresql_dsn():
    assert isinstance(
        build_quota_manager("postgresql://u:p@localhost:5432/db"), PostgresQuotaManager
    )
    assert isinstance(
        build_quota_manager("postgresql+asyncpg://u:p@localhost:5432/db"), PostgresQuotaManager
    )


def test_build_rejects_unknown_dsn():
    with pytest.raises(QuotaStoreUnavailable):
        build_quota_manager("sqlite:///quota.db")


def test_build_rejects_missing_driver(monkeypatch):
    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(quota_postgres, "_import_module", missing)

    with pytest.raises(QuotaStoreUnavailable):
        build_quota_manager("postgresql://u:p@localhost:5432/db")


@_live
def test_run_limit_is_shared():
    clock = Clock()
    first = _manager(clock)
    second = _manager(clock)
    tenant = _tenant()
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    _consume(first, tenant, policy, 1)
    with pytest.raises(QuotaExceeded) as exc:
        _consume(second, tenant, policy, 1)

    assert exc.value.limit == "max_runs"


@_live
def test_window_expiry():
    clock = Clock()
    manager = _manager(clock)
    tenant = _tenant()
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    _consume(manager, tenant, policy, 1)
    clock.now += 61
    _consume(manager, tenant, policy, 1)


@_live
def test_concurrent_limit_is_shared():
    clock = Clock()
    first = _manager(clock)
    second = _manager(clock)
    tenant = _tenant()
    policy = QuotaPolicy(max_concurrent=1)

    async def scenario() -> None:
        async with first.reserve(tenant, policy):
            with pytest.raises(QuotaExceeded) as exc:
                async with second.reserve(tenant, policy):
                    pass
            assert exc.value.limit == "max_concurrent"

    asyncio.run(scenario())


@_live
def test_release_on_exit():
    clock = Clock()
    first = _manager(clock)
    second = _manager(clock)
    tenant = _tenant()
    policy = QuotaPolicy(max_concurrent=1)

    async def scenario() -> None:
        async with first.reserve(tenant, policy):
            pass
        async with second.reserve(tenant, policy):
            pass

    asyncio.run(scenario())


@_live
def test_expired_lease_is_reclaimed():
    clock = Clock()
    first = _manager(clock, lease_seconds=10)
    second = _manager(clock, lease_seconds=10)
    tenant = _tenant()
    policy = QuotaPolicy(max_concurrent=1)

    async def scenario() -> None:
        async with first.reserve(tenant, policy):
            clock.now += 11
            async with second.reserve(tenant, policy):
                pass

    asyncio.run(scenario())


@_live
def test_denied_concurrency_does_not_consume_run():
    clock = Clock()
    first = _manager(clock)
    second = _manager(clock)
    tenant = _tenant()
    policy = QuotaPolicy(max_runs=2, max_concurrent=1, window_seconds=60)

    async def scenario() -> None:
        async with first.reserve(tenant, policy):
            with pytest.raises(QuotaExceeded):
                async with second.reserve(tenant, policy):
                    pass
        async with second.reserve(tenant, policy):
            pass
        with pytest.raises(QuotaExceeded) as exc:
            async with second.reserve(tenant, policy):
                pass
        assert exc.value.limit == "max_runs"

    asyncio.run(scenario())


@_live
def test_tenants_are_isolated():
    clock = Clock()
    manager = _manager(clock)
    one = _tenant()
    two = _tenant()
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    _consume(manager, one, policy, 1)
    _consume(manager, two, policy, 1)
    with pytest.raises(QuotaExceeded):
        _consume(manager, one, policy, 1)
