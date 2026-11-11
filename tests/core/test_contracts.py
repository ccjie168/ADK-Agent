"""SLICE-008: core contracts and domain types."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentManifest,
    AgentRef,
    AuditEvent,
    Invocation,
    Principal,
    manifest_digest,
)

ROOT = Path(__file__).resolve().parents[2]
_EXPORT = ROOT / "scripts" / "export_contracts.py"


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


def _principal(**overrides):
    data = {"tenant": "t1", "subject": "alice", "kind": "human"}
    data.update(overrides)
    return Principal(**data)


def _agent_ref(**overrides):
    data = {"id": "support-bot", "version": "1.0.0", "digest": "abc123"}
    data.update(overrides)
    return AgentRef(**data)


def _audit(**overrides):
    data = {
        "event_id": "e1",
        "run_id": "r1",
        "trace_id": "tr1",
        "tenant": "t1",
        "principal": _principal(),
        "agent_ref": _agent_ref(),
        "action": "model.call",
        "target": "litellm",
        "status": "ok",
        "timestamp": datetime(2026, 1, 1, tzinfo=UTC),
    }
    data.update(overrides)
    return AuditEvent(**data)


def test_roundtrip():
    manifest = _manifest()
    assert AgentManifest.model_validate_json(manifest.model_dump_json()) == manifest
    principal = _principal()
    assert Principal.model_validate_json(principal.model_dump_json()) == principal


def test_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _manifest(unknown="x")
    with pytest.raises(ValidationError):
        _principal(unknown="x")


def test_manifest_required():
    for missing in ("id", "version", "owner"):
        data = _manifest().model_dump()
        data.pop(missing)
        with pytest.raises(ValidationError):
            AgentManifest(**data)


def test_agent_ref_requires_digest():
    with pytest.raises(ValidationError):
        AgentRef(id="a", version="1")
    with pytest.raises(ValidationError):
        AgentRef(id="a", version="1", digest="")


def test_principal_required():
    with pytest.raises(ValidationError):
        Principal(tenant="t", kind="human")
    with pytest.raises(ValidationError):
        Principal(tenant="t", subject="s", kind="not-a-kind")


def test_invocation_required():
    with pytest.raises(ValidationError):
        Invocation(
            run_id="r",
            trace_id="",
            principal=_principal(),
            agent_ref=_agent_ref(),
            input="hi",
        )
    with pytest.raises(ValidationError):
        Invocation(
            run_id="",
            trace_id="tr",
            principal=_principal(),
            agent_ref=_agent_ref(),
            input="hi",
        )


def test_audit_required():
    with pytest.raises(ValidationError):
        _audit(trace_id="")
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="e1",
            run_id="r1",
            trace_id="tr1",
            tenant="t1",
            agent_ref=_agent_ref(),
            action="model.call",
            target="litellm",
            status="ok",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_audit_tenant_matches_principal():
    with pytest.raises(ValidationError):
        _audit(tenant="other")


def test_audit_timestamp_tz_aware():
    with pytest.raises(ValidationError):
        _audit(timestamp=datetime(2026, 1, 1))


def test_digest_stable():
    data = _manifest().model_dump()
    reordered = {key: data[key] for key in reversed(list(data))}
    assert manifest_digest(_manifest()) == manifest_digest(AgentManifest(**reordered))
    assert len(manifest_digest(_manifest())) == 64


def test_digest_changes():
    before = manifest_digest(_manifest())
    after = manifest_digest(_manifest(model_policy={"provider_allowlist": ["vllm"]}))
    assert before != after


def _load_export():
    spec = importlib.util.spec_from_file_location("export_contracts", _EXPORT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_contracts_in_sync():
    export = _load_export()
    for name, text in export.render().items():
        on_disk = (ROOT / "docs" / "contracts" / name).read_text(encoding="utf-8")
        assert on_disk == text, f"{name} is out of sync; run scripts/export_contracts.py"
