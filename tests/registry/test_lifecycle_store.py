"""SLICE-076: file and Postgres lifecycle stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

from adk_agent.core import LifecycleTransitionError
from adk_agent.registry import FileAgentLifecycleStore, PostgresAgentLifecycleStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def test_file_roundtrip(tmp_path):
    store = FileAgentLifecycleStore(tmp_path)

    default = asyncio.run(store.get("acme", "bot", "1.0.0"))
    assert default.status == "published"

    changed = asyncio.run(
        store.set("acme", "bot", "1.0.0", status="deprecated", changed_by="alice", reason="old")
    )
    assert changed.status == "deprecated"
    assert changed.changed_by == "alice"
    assert asyncio.run(store.get("acme", "bot", "1.0.0")) == changed

    again = asyncio.run(
        store.set("acme", "bot", "1.0.0", status="deprecated", changed_by="bob", reason="again")
    )
    assert again == changed


def test_file_rejects_transition(tmp_path):
    store = FileAgentLifecycleStore(tmp_path)
    asyncio.run(
        store.set("acme", "bot", "1.0.0", status="retired", changed_by="alice", reason="stop")
    )

    with pytest.raises(LifecycleTransitionError):
        asyncio.run(
            store.set("acme", "bot", "1.0.0", status="published", changed_by="bob", reason="back")
        )


@_live
@_needs_driver
def test_postgres_roundtrip():
    store = PostgresAgentLifecycleStore(_LIVE_URL)
    tenant = "t" + uuid.uuid4().hex[:12]

    assert asyncio.run(store.get(tenant, "bot", "1.0.0")).status == "published"

    changed = asyncio.run(
        store.set(tenant, "bot", "1.0.0", status="deprecated", changed_by="alice", reason="old")
    )
    assert changed.status == "deprecated"
    assert asyncio.run(store.get(tenant, "bot", "1.0.0")) == changed

    retired = asyncio.run(
        store.set(tenant, "bot", "1.0.0", status="retired", changed_by="alice", reason="stop")
    )
    assert retired.status == "retired"

    with pytest.raises(LifecycleTransitionError):
        asyncio.run(
            store.set(tenant, "bot", "1.0.0", status="deprecated", changed_by="bob", reason="back")
        )
