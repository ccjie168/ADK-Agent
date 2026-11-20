"""SLICE-185: model alias and routing policy schema (ADR-0033 slice 1)."""

from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentManifest, ModelAlias, ModelCandidate, ModelPolicy, manifest_digest


def _manifest(**overrides) -> AgentManifest:
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


def test_manifest_accepts_model_alias_and_aliases():
    policy = ModelPolicy(
        provider_allowlist=["litellm"],
        model_aliases=[
            ModelAlias(
                alias="primary-chat",
                candidates=[
                    ModelCandidate(provider="litellm", model="deepseek/deepseek-v4-pro"),
                    ModelCandidate(
                        provider="litellm",
                        model="gemini/gemini-2.5-pro",
                        allowed_data_classes=["public", "internal"],
                    ),
                ],
            )
        ],
    )
    manifest = _manifest(model_policy=policy.model_dump(), model_alias="primary-chat")
    assert manifest.model_alias == "primary-chat"
    assert manifest.model_policy.model_aliases[0].candidates[1].model == "gemini/gemini-2.5-pro"


def test_model_alias_requires_candidates():
    with pytest.raises(ValidationError):
        ModelAlias(alias="empty", candidates=[])


def test_model_policy_rejects_duplicate_alias():
    candidate = ModelCandidate(provider="litellm", model="a")
    with pytest.raises(ValidationError):
        ModelPolicy(
            provider_allowlist=["litellm"],
            model_aliases=[
                ModelAlias(alias="dup", candidates=[candidate]),
                ModelAlias(alias="dup", candidates=[candidate]),
            ],
        )


def test_manifest_digest_unchanged_by_defaults():
    manifest = _manifest()
    payload = manifest.model_dump(mode="json")
    payload.pop("execution_tier", None)
    payload.pop("model_alias", None)
    payload.pop("rag", None)
    payload["model_policy"].pop("model_aliases", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert manifest_digest(manifest) == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_manifest_digest_covers_model_alias():
    plain = _manifest()
    with_alias = _manifest(model_alias="primary-chat")
    assert manifest_digest(plain) != manifest_digest(with_alias)
