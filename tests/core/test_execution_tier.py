"""SLICE-128: the manifest execution tier and its digest rules."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentManifest, declared_execution_tier, manifest_digest


def _manifest(**overrides) -> AgentManifest:
    data = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "acme",
        "owner": "acme",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    data.update(overrides)
    return AgentManifest(**data)


def _digest_without_tier(manifest: AgentManifest) -> str:
    """Digest of the payload without the fields added after a record was published."""
    payload = manifest.model_dump(mode="json")
    payload.pop("execution_tier", None)
    payload.pop("model_alias", None)
    payload["model_policy"].pop("model_aliases", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_legacy_manifest_digest_is_unchanged():
    manifest = _manifest()
    assert manifest.execution_tier is None
    assert manifest_digest(manifest) == _digest_without_tier(manifest)


def test_tier_is_part_of_the_digest():
    legacy = _manifest()
    in_process = _manifest(execution_tier="in_process")
    sandboxed = _manifest(execution_tier="sandboxed")

    assert manifest_digest(sandboxed) != manifest_digest(in_process)
    assert manifest_digest(sandboxed) != manifest_digest(legacy)
    assert manifest_digest(in_process) != manifest_digest(legacy)


def test_unknown_tier_is_rejected():
    with pytest.raises(ValidationError):
        _manifest(execution_tier="container")


def test_declared_tier_rules():
    assert declared_execution_tier({"execution_tier": "sandboxed"}) == "sandboxed"
    assert declared_execution_tier({"execution_tier": "in_process"}) == "in_process"

    with pytest.raises(ValueError):
        declared_execution_tier({})
    with pytest.raises(ValueError):
        declared_execution_tier({"execution_tier": None})
    with pytest.raises(ValueError):
        declared_execution_tier({"execution_tier": "container"})
