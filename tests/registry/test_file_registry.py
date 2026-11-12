"""SLICE-012: file registry pins immutable manifest versions by digest."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent.core import AgentManifest, AgentRef, EvalReport
from adk_agent.registry import (
    FileAgentRegistry,
    RegistryConflict,
    RegistryIntegrityError,
)
from adk_agent.registry.manifest import published_from
from adk_agent.registry.reports import FileEvalReportStore


def _manifest(**overrides):
    data = {
        "id": "support-bot",
        "version": "1.0.0",
        "tenant": "team-a",
        "owner": "team-a",
        "description": "support",
        "model_policy": {"provider_allowlist": ["litellm"]},
        "tool_grants": [{"tool_id": "crm.read", "data_classes": ["internal"]}],
        "data_scopes": ["internal"],
        "exposure": "mcp",
    }
    data.update(overrides)
    return AgentManifest(**data)


_TENANT = "team-a"


def _registry(tmp_path) -> FileAgentRegistry:
    return FileAgentRegistry(tmp_path / "registry")


def _ref(manifest: AgentManifest, digest: str) -> AgentRef:
    return AgentRef(id=manifest.id, version=manifest.version, digest=digest)


def test_publish_then_get(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    stored = asyncio.run(registry.publish(published))
    assert stored.digest == published.digest

    got = asyncio.run(registry.get(_ref(published.manifest, published.digest), _TENANT))
    assert got == published


def test_publish_is_idempotent(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    first = asyncio.run(registry.publish(published))
    second = asyncio.run(registry.publish(published))
    assert first.digest == second.digest

    path = tmp_path / "registry" / _TENANT / "support-bot" / "1.0.0.json"
    assert json.loads(path.read_text())["digest"] == published.digest


def test_same_version_different_content_conflicts(tmp_path):
    registry = _registry(tmp_path)
    asyncio.run(registry.publish(published_from(_manifest(description="one"))))
    with pytest.raises(RegistryConflict):
        asyncio.run(registry.publish(published_from(_manifest(description="two"))))


def test_get_missing_returns_none(tmp_path):
    registry = _registry(tmp_path)
    ref = AgentRef(id="support-bot", version="9.9.9", digest="sha256:missing")
    assert asyncio.run(registry.get(ref, _TENANT)) is None


def test_wrong_digest_returns_none(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))
    ref = _ref(published.manifest, "0" * 64)
    assert asyncio.run(registry.get(ref, _TENANT)) is None


def test_get_from_other_tenant_returns_none(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))

    ref = _ref(published.manifest, published.digest)
    assert asyncio.run(registry.get(ref, "team-b")) is None


def test_tampered_file_raises_integrity_error(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))

    path = tmp_path / "registry" / _TENANT / "support-bot" / "1.0.0.json"
    data = json.loads(path.read_text())
    data["manifest"]["description"] = "tampered"
    path.write_text(json.dumps(data))

    with pytest.raises(RegistryIntegrityError):
        asyncio.run(registry.get(_ref(published.manifest, published.digest), _TENANT))


def test_signature_is_integrity_marker():
    published = published_from(_manifest())
    assert published.signature == f"sha256:{published.digest}"


def test_list_returns_published_records(tmp_path):
    registry = _registry(tmp_path)
    records = [
        published_from(_manifest(id="beta-bot", version="1.0.0")),
        published_from(_manifest(id="alpha-bot", version="2.0.0")),
        published_from(_manifest(id="alpha-bot", version="1.0.0")),
    ]
    for record in records:
        asyncio.run(registry.publish(record))

    listed = asyncio.run(registry.list(_TENANT))

    assert [(item.manifest.id, item.manifest.version) for item in listed] == [
        ("alpha-bot", "1.0.0"),
        ("alpha-bot", "2.0.0"),
        ("beta-bot", "1.0.0"),
    ]
    assert {item.digest for item in listed} == {item.digest for item in records}


def test_tenants_sorted_and_missing_root(tmp_path):
    missing = FileAgentRegistry(tmp_path / "missing")
    assert asyncio.run(missing.tenants()) == []

    registry = _registry(tmp_path)
    asyncio.run(registry.publish(published_from(_manifest(tenant="team-b"))))
    asyncio.run(registry.publish(published_from(_manifest(tenant="team-a"))))
    (tmp_path / "registry" / "bad name").mkdir()

    assert asyncio.run(registry.tenants()) == ["team-a", "team-b"]


def test_list_rejects_unsafe_tenant(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(registry.list("../x"))


def test_list_surfaces_corrupt_record(tmp_path):
    registry = _registry(tmp_path)
    published = published_from(_manifest())
    asyncio.run(registry.publish(published))

    path = tmp_path / "registry" / _TENANT / "support-bot" / "1.0.0.json"
    data = json.loads(path.read_text())
    data["digest"] = "0" * 64
    path.write_text(json.dumps(data))

    with pytest.raises(RegistryIntegrityError):
        asyncio.run(registry.list(_TENANT))


def test_list_surfaces_malformed_record(tmp_path):
    registry = _registry(tmp_path)
    asyncio.run(registry.publish(published_from(_manifest())))

    path = tmp_path / "registry" / _TENANT / "support-bot" / "1.0.0.json"
    path.write_text("{not json")

    with pytest.raises(RegistryIntegrityError):
        asyncio.run(registry.list(_TENANT))


def test_list_ignores_eval_report_files(tmp_path):
    registry = _registry(tmp_path)
    asyncio.run(registry.publish(published_from(_manifest())))
    report = EvalReport(suite_id="smoke", version="1", passed=1, total=1)
    asyncio.run(
        FileEvalReportStore(tmp_path / "registry").put(_TENANT, "support-bot", "1.0.0", report)
    )

    listed = asyncio.run(registry.list(_TENANT))

    assert [(item.manifest.id, item.manifest.version) for item in listed] == [
        ("support-bot", "1.0.0")
    ]
