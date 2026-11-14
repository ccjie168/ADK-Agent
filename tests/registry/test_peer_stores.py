"""SLICE-090: file and Postgres peer stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

from adk_agent.core import PeerGrant, PeerIdentity, PeerStoreError
from adk_agent.registry import (
    FilePeerGrantStore,
    FilePeerStore,
    PostgresPeerGrantStore,
    PostgresPeerStore,
)

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _identity(**overrides) -> PeerIdentity:
    data = {"peer_id": "peer-a", "tenant": "acme", "subject": "sub-1", "enabled": True}
    data.update(overrides)
    return PeerIdentity(**data)


def _grant(**overrides) -> PeerGrant:
    data = {
        "peer_id": "peer-a",
        "tenant": "acme",
        "agent_id": "bot",
        "actions": ["read", "invoke"],
    }
    data.update(overrides)
    return PeerGrant(**data)


def test_file_peer_roundtrip(tmp_path):
    store = FilePeerStore(tmp_path)

    assert asyncio.run(store.get("peer-a")) is None
    asyncio.run(store.put(_identity()))
    assert asyncio.run(store.get("peer-a")) == _identity()
    assert asyncio.run(store.get_by_subject("sub-1")) == _identity()
    assert asyncio.run(store.list()) == [_identity()]


def test_file_peer_overwrite(tmp_path):
    store = FilePeerStore(tmp_path)

    asyncio.run(store.put(_identity()))
    asyncio.run(store.put(_identity(subject="sub-2")))

    assert asyncio.run(store.get("peer-a")) == _identity(subject="sub-2")
    assert asyncio.run(store.get_by_subject("sub-1")) is None


def test_file_peer_idempotent_put(tmp_path):
    store = FilePeerStore(tmp_path)

    assert asyncio.run(store.put(_identity())) == _identity()
    assert asyncio.run(store.put(_identity())) == _identity()
    assert len(asyncio.run(store.list())) == 1


def test_file_peer_bad_json(tmp_path):
    store = FilePeerStore(tmp_path)
    (tmp_path / "peers").mkdir(parents=True)
    (tmp_path / "peers" / "peer-a.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(PeerStoreError):
        asyncio.run(store.get("peer-a"))


def test_file_grant_roundtrip(tmp_path):
    store = FilePeerGrantStore(tmp_path)

    assert asyncio.run(store.get("peer-a", "bot")) is None
    asyncio.run(store.put(_grant()))
    assert asyncio.run(store.get("peer-a", "bot")) == _grant()
    assert asyncio.run(store.list()) == [_grant()]


def test_file_grant_overwrite(tmp_path):
    store = FilePeerGrantStore(tmp_path)

    asyncio.run(store.put(_grant()))
    asyncio.run(store.put(_grant(actions=["read"])))

    assert asyncio.run(store.get("peer-a", "bot")) == _grant(actions=["read"])


def test_file_grant_bad_json(tmp_path):
    store = FilePeerGrantStore(tmp_path)
    (tmp_path / "grants" / "peer-a").mkdir(parents=True)
    (tmp_path / "grants" / "peer-a" / "bot.json").write_text("{", encoding="utf-8")

    with pytest.raises(PeerStoreError):
        asyncio.run(store.get("peer-a", "bot"))


@_live
@_needs_driver
def test_postgres_peer_roundtrip():
    store = PostgresPeerStore(_LIVE_URL)
    peer = _identity(peer_id="p" + uuid.uuid4().hex[:12])

    assert asyncio.run(store.put(peer)) == peer
    assert asyncio.run(store.put(peer)) == peer
    assert asyncio.run(store.get(peer.peer_id)) == peer
    assert asyncio.run(store.get_by_subject(peer.subject)) == peer

    changed = peer.model_copy(update={"subject": "sub-2"})
    assert asyncio.run(store.put(changed)) == changed
    assert asyncio.run(store.get_by_subject("sub-1")) is None


@_live
@_needs_driver
def test_postgres_grant_roundtrip():
    store = PostgresPeerGrantStore(_LIVE_URL)
    grant = _grant(peer_id="p" + uuid.uuid4().hex[:12])

    assert asyncio.run(store.put(grant)) == grant
    assert asyncio.run(store.put(grant)) == grant
    assert asyncio.run(store.get(grant.peer_id, "bot")) == grant

    changed = grant.model_copy(update={"actions": ["read"]})
    assert asyncio.run(store.put(changed)) == changed
    assert asyncio.run(store.get(grant.peer_id, "bot")) == changed
