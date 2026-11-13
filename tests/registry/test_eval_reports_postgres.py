"""SLICE-074: eval reports live in Postgres with the published versions.

Set TEST_POSTGRES_URL to run the live cases against a real database.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

from adk_agent.core import EvalReport
from adk_agent.registry import (
    EvalReportConflict,
    PostgresEvalReportStore,
    RegistryStoreUnavailable,
)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _report(passed: int = 1, total: int = 2) -> EvalReport:
    return EvalReport(suite_id="smoke", version="1", passed=passed, total=total)


def _tenant() -> str:
    return "t" + uuid.uuid4().hex[:12]


def _store() -> PostgresEvalReportStore:
    return PostgresEvalReportStore(_LIVE_URL)


def test_unsupported_url_rejected():
    with pytest.raises(RegistryStoreUnavailable) as exc:
        PostgresEvalReportStore("mysql://localhost/adk")
    assert "postgres" in str(exc.value).lower()


@_live
@_needs_driver
def test_live_roundtrip():
    store = _store()
    tenant = _tenant()
    report = _report()

    stored = asyncio.run(store.put(tenant, "bot", "1.0.0", report))

    assert stored == report
    assert asyncio.run(store.get(tenant, "bot", "1.0.0")) == report
    assert asyncio.run(store.has(tenant, "bot", "1.0.0")) is True


@_live
@_needs_driver
def test_live_conflict():
    store = _store()
    tenant = _tenant()
    first = _report()
    assert asyncio.run(store.put(tenant, "bot", "1.0.0", first)) == first
    assert asyncio.run(store.put(tenant, "bot", "1.0.0", first)) == first

    with pytest.raises(EvalReportConflict):
        asyncio.run(store.put(tenant, "bot", "1.0.0", _report(passed=2, total=2)))


@_live
@_needs_driver
def test_live_missing():
    store = _store()
    tenant = _tenant()

    assert asyncio.run(store.get(tenant, "bot", "9.9.9")) is None
    assert asyncio.run(store.has(tenant, "bot", "9.9.9")) is False
