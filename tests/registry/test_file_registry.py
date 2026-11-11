"""SLICE-012: file registry pins immutable manifest versions by digest."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent.core import AgentManifest, AgentRef
from adk_agent.registry import (
    FileAgentRegistry,
    RegistryConflict,
    RegistryIntegrityError,
)
from adk_agent.registry.manifest import published_from


def _manifest(**overrides):
    data = {
        "id": "support-bot",
        "version": "1.0.0",
        "owner": "team-a",
        "description": "support",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "tool_grants": [{"tool_id": "crm.read", "data_classes": ["internal"]}],
        "data_scopes": ["internal"],
        "exposure": "mcp",
    }
    data.update(overrides)
    return AgentManifest(**data)


def _registry(tmp_path) -> FileAgentRegistry:
    return FileAgentRegistry(tmp_path / "registry")


def _ref(manifest: AgentManifest, digest: str) -> AgentRef:
    return AgentRef(id=manifest.id, version=manifest.version, digest=digest)


def test_publish_then_get(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    stored = asyncio.run(registry.publish(published))
    assert stored.digest == published.digest

    got = asyncio.run(registry.get(_ref(published.manifest, published.digest)))
    assert got == published


def test_publish_is_idempotent(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    first = asyncio.run(registry.publish(published))
    second = asyncio.run(registry.publish(published))
    assert first.digest == second.digest

    path = tmp_path / "registry" / "support-bot" / "1.0.0.json"
    assert json.loads(path.read_text())["digest"] == published.digest


def test_same_version_different_content_conflicts(tmp_path):
    registry = _registry(tmp_path)
    asyncio.run(registry.publish(published_from(_manifest(description="one"))))
    with pytest.raises(RegistryConflict):
        asyncio.run(registry.publish(published_from(_manifest(description="two"))))


def test_get_missing_returns_none(tmp_path):
    registry = _registry(tmp_path)
    ref = AgentRef(id="support-bot", version="9.9.9", digest="sha256:missing")
    assert asyncio.run(registry.get(ref)) is None


def test_wrong_digest_returns_none(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))
    ref = _ref(published.manifest, "0" * 64)
    assert asyncio.run(registry.get(ref)) is None


def test_tampered_file_raises_integrity_error(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))

    path = tmp_path / "registry" / "support-bot" / "1.0.0.json"
    data = json.loads(path.read_text())
    data["manifest"]["description"] = "tampered"
    path.write_text(json.dumps(data))

    with pytest.raises(RegistryIntegrityError):
        asyncio.run(registry.get(_ref(published.manifest, published.digest)))


def test_signature_is_integrity_marker():
    published = published_from(_manifest())
    assert published.signature == f"sha256:{published.digest}"
