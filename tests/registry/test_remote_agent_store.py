"""SLICE-093: file and Postgres remote agent stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid
from datetime import datetime, timezone

import pytest

from adk_agent.core import RemoteAgent, RemoteAgentError
from adk_agent.registry import FileRemoteAgentStore, PostgresRemoteAgentStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _record(**overrides) -> RemoteAgent:
    data = {
        "remote_id": "crm-bot",
        "tenant": "acme",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/card.json",
        "label": "CRM bot",
        "card_digest": "sha256:" + "a" * 64,
        "checked_at": datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
        "status": "pinned",
    }
    data.update(overrides)
    return RemoteAgent(**data)


def test_file_roundtrip(tmp_path):
    store = FileRemoteAgentStore(tmp_path)

    assert asyncio.run(store.get("crm-bot")) is None
    asyncio.run(store.put(_record()))
    assert asyncio.run(store.get("crm-bot")) == _record()
    assert asyncio.run(store.list()) == [_record()]


def test_file_overwrite(tmp_path):
    store = FileRemoteAgentStore(tmp_path)

    asyncio.run(store.put(_record()))
    asyncio.run(store.put(_record(label="new")))

    assert asyncio.run(store.get("crm-bot")) == _record(label="new")


def test_file_bad_json(tmp_path):
    store = FileRemoteAgentStore(tmp_path)
    (tmp_path / "remote-agents").mkdir(parents=True)
    (tmp_path / "remote-agents" / "crm-bot.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(RemoteAgentError):
        asyncio.run(store.get("crm-bot"))


@_live
@_needs_driver
def test_postgres_roundtrip():
    store = PostgresRemoteAgentStore(_LIVE_URL)
    record = _record(remote_id="r" + uuid.uuid4().hex[:12])

    assert asyncio.run(store.put(record)) == record
    assert asyncio.run(store.put(record)) == record
    assert asyncio.run(store.get(record.remote_id)) == record

    changed = record.model_copy(update={"label": "new"})
    assert asyncio.run(store.put(changed)) == changed
    assert asyncio.run(store.get(record.remote_id)) == changed
