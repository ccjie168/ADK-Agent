"""SLICE-085: file and Postgres connector stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os

import pytest

from adk_agent.core import ConnectorSpec
from adk_agent.registry import (
    ConnectorConflict,
    FileConnectorStore,
    PostgresConnectorStore,
)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _spec(**overrides) -> ConnectorSpec:
    data = {
        "connector_id": "crm",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://crm/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/"],
        "data_classes": ["internal"],
    }
    data.update(overrides)
    return ConnectorSpec(**data)


def test_file_add_idempotent(tmp_path):
    store = FileConnectorStore(tmp_path)
    spec = _spec()

    assert asyncio.run(store.add(spec)) == spec
    assert asyncio.run(store.add(spec)) == spec
    assert asyncio.run(store.get("crm")) == spec

    with pytest.raises(ConnectorConflict):
        asyncio.run(store.add(_spec(base_url="https://other.example.com")))


def test_file_list_visibility(tmp_path):
    store = FileConnectorStore(tmp_path)
    asyncio.run(store.add(_spec(connector_id="global")))
    asyncio.run(store.add(_spec(connector_id="acme", tenant="acme")))
    asyncio.run(store.add(_spec(connector_id="other", tenant="other")))

    listed = asyncio.run(store.list("acme"))

    assert [spec.connector_id for spec in listed] == ["acme", "global"]


def test_file_disable(tmp_path):
    store = FileConnectorStore(tmp_path)
    asyncio.run(store.add(_spec()))

    disabled = asyncio.run(store.disable("crm", by="alice"))
    again = asyncio.run(store.disable("crm", by="bob"))

    assert disabled.enabled is False
    assert again.enabled is False
    assert asyncio.run(store.get("crm")).enabled is False


@_live
@_needs_driver
def test_postgres_lifecycle():
    store = PostgresConnectorStore(_LIVE_URL)
    spec = _spec(connector_id="pg-" + os.urandom(4).hex())

    assert asyncio.run(store.add(spec)) == spec
    assert asyncio.run(store.add(spec)) == spec
    assert asyncio.run(store.get(spec.connector_id)) == spec

    disabled = asyncio.run(store.disable(spec.connector_id, by="alice"))
    assert disabled.enabled is False
    assert asyncio.run(store.get(spec.connector_id)).enabled is False
