"""SLICE-065: file and Postgres artifact stores."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import uuid

import pytest

from adk_agent.core import AgentArtifact
from adk_agent.registry import ArtifactStoreError, FileArtifactStore, artifact_digest
from adk_agent.registry.artifacts_postgres import PostgresArtifactStore

_HAS_DRIVER = importlib.util.find_spec("asyncpg") is not None
_LIVE_URL = os.environ.get("TEST_POSTGRES_URL")
_live = pytest.mark.skipif(not _LIVE_URL, reason="TEST_POSTGRES_URL is not set")
_needs_driver = pytest.mark.skipif(not _HAS_DRIVER, reason="asyncpg is not installed")


def _data(payload: bytes = b"zip-bytes") -> bytes:
    return payload


def _artifact(data: bytes, **overrides) -> AgentArtifact:
    fields = {"digest": artifact_digest(data), "size": len(data)}
    fields.update(overrides)
    return AgentArtifact(**fields)


def test_file_roundtrip(tmp_path):
    store = FileArtifactStore(tmp_path)
    data = _data()

    asyncio.run(store.put(_artifact(data), data))

    assert asyncio.run(store.has(artifact_digest(data))) is True
    assert asyncio.run(store.get(artifact_digest(data))) == data


def test_file_path_is_addressed(tmp_path):
    store = FileArtifactStore(tmp_path)
    data = _data()

    asyncio.run(store.put(_artifact(data), data))

    hexdigest = artifact_digest(data).split(":", 1)[1]
    assert (tmp_path / "sha256" / hexdigest).read_bytes() == data


def test_file_put_is_idempotent(tmp_path):
    store = FileArtifactStore(tmp_path)
    data = _data()
    artifact = _artifact(data)

    asyncio.run(store.put(artifact, data))
    asyncio.run(store.put(artifact, data))

    assert asyncio.run(store.get(artifact.digest)) == data


def test_file_rejects_size_mismatch(tmp_path):
    store = FileArtifactStore(tmp_path)
    data = _data()

    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.put(_artifact(data, size=len(data) + 1), data))

    assert list(tmp_path.rglob("*")) == []


def test_file_rejects_digest_mismatch(tmp_path):
    store = FileArtifactStore(tmp_path)
    data = _data()
    artifact = _artifact(data, digest="sha256:" + "0" * 64)

    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.put(artifact, data))

    assert list(tmp_path.rglob("*")) == []


def test_file_rejects_bad_digest(tmp_path):
    store = FileArtifactStore(tmp_path)

    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.get("../escape"))
    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.has("sha256:not-hex"))


def test_file_missing(tmp_path):
    store = FileArtifactStore(tmp_path)

    assert asyncio.run(store.get("sha256:" + "a" * 64)) is None
    assert asyncio.run(store.has("sha256:" + "a" * 64)) is False


def _pg_store() -> PostgresArtifactStore:
    assert _LIVE_URL is not None
    return PostgresArtifactStore(_LIVE_URL)


@_live
@_needs_driver
def test_postgres_roundtrip():
    store = _pg_store()
    data = uuid.uuid4().bytes * 4
    artifact = _artifact(data)

    asyncio.run(store.put(artifact, data))

    assert asyncio.run(store.has(artifact.digest)) is True
    assert asyncio.run(store.get(artifact.digest)) == data


@_live
@_needs_driver
def test_postgres_put_is_idempotent():
    store = _pg_store()
    data = uuid.uuid4().bytes * 4
    artifact = _artifact(data)

    asyncio.run(store.put(artifact, data))
    asyncio.run(store.put(artifact, data))

    assert asyncio.run(store.get(artifact.digest)) == data


@_live
@_needs_driver
def test_postgres_missing_and_bad_digest():
    store = _pg_store()

    assert asyncio.run(store.get("sha256:" + "b" * 64)) is None
    with pytest.raises(ArtifactStoreError):
        asyncio.run(store.has("../escape"))
