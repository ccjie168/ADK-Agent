"""SLICE-196: the manifest carries the RAG configuration (ADR-0036)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentManifest, RagConfig, manifest_digest

ROOT = Path(__file__).resolve().parents[2]


def _manifest(**overrides) -> AgentManifest:
    base = {
        "id": "agent",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "team",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    base.update(overrides)
    return AgentManifest(**base)


def test_manifest_rag_defaults():
    rag = RagConfig()
    assert rag.enabled is False
    assert rag.top_k == 5
    assert rag.min_confidence == 0.5
    assert rag.data_classes == []
    assert rag.on_error == "deny"
    assert _manifest().rag is None


@pytest.mark.parametrize("top_k", [0, 51])
def test_manifest_rag_rejects_bad_top_k(top_k):
    with pytest.raises(ValidationError):
        RagConfig(top_k=top_k)


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_manifest_rag_rejects_bad_confidence(confidence):
    with pytest.raises(ValidationError):
        RagConfig(min_confidence=confidence)


def test_manifest_rag_rejects_bad_on_error():
    with pytest.raises(ValidationError):
        RagConfig(on_error="ignore")


def test_legacy_manifest_digest_ignores_missing_rag():
    manifest = _manifest()
    payload = manifest.model_dump(mode="json")
    payload.pop("rag")
    payload.pop("execution_tier", None)
    payload.pop("model_alias", None)
    payload["model_policy"].pop("model_aliases", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert manifest.rag is None
    assert manifest_digest(manifest) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_manifest_digest_changes_with_rag():
    without = manifest_digest(_manifest())
    disabled = manifest_digest(_manifest(rag={"enabled": False}))
    enabled = manifest_digest(_manifest(rag={"enabled": True, "top_k": 3}))
    assert without != disabled
    assert disabled != enabled


def test_manifest_schema_documents_rag():
    schema = json.loads(
        (ROOT / "docs" / "contracts" / "manifest.schema.json").read_text(encoding="utf-8")
    )
    assert "RagConfig" in json.dumps(schema)
