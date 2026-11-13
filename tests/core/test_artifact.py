"""SLICE-064: agent artifact type, additive refs and contract export."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentArtifact,
    AgentManifest,
    AgentRef,
    PublishedAgent,
)

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64


def _artifact(**overrides) -> AgentArtifact:
    data = {
        "digest": DIGEST,
        "media_type": "application/vnd.adk.agent+zip",
        "size": 1024,
        "entrypoint": "agent.py",
        "signature": "b" * 128,
        "key_id": "publisher-1",
    }
    data.update(overrides)
    return AgentArtifact(**data)


def test_artifact_roundtrip():
    artifact = _artifact()

    assert AgentArtifact.model_validate_json(artifact.model_dump_json()) == artifact


def test_artifact_defaults():
    artifact = AgentArtifact(digest=DIGEST, media_type="application/vnd.adk.agent+zip", size=1)

    assert artifact.entrypoint == "agent.py"
    assert artifact.signature is None
    assert artifact.key_id is None


@pytest.mark.parametrize(
    "digest",
    ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63, "md5:" + "a" * 64],
)
def test_rejects_bad_digest(digest):
    with pytest.raises(ValidationError):
        _artifact(digest=digest)


def test_rejects_bad_media_type():
    with pytest.raises(ValidationError):
        _artifact(media_type="application/zip")


@pytest.mark.parametrize("size", [0, 8 * 1024 * 1024 + 1])
def test_rejects_bad_size(size):
    with pytest.raises(ValidationError):
        _artifact(size=size)


@pytest.mark.parametrize("entrypoint", ["agent", "../agent.py", "agent.txt", "a/b.py"])
def test_rejects_bad_entrypoint(entrypoint):
    with pytest.raises(ValidationError):
        _artifact(entrypoint=entrypoint)


@pytest.mark.parametrize("signature", ["b" * 127, "B" * 128])
def test_rejects_bad_signature(signature):
    with pytest.raises(ValidationError):
        _artifact(signature=signature)


def test_rejects_bad_key_id():
    with pytest.raises(ValidationError):
        _artifact(key_id="bad id")


def test_agent_ref_artifact_digest():
    ref = AgentRef(id="bot", version="1", digest="abc", artifact_digest=DIGEST)

    assert ref.artifact_digest == DIGEST
    with pytest.raises(ValidationError):
        AgentRef(id="bot", version="1", digest="abc", artifact_digest="x")


def test_published_agent_carries_artifact():
    manifest = AgentManifest(
        id="bot",
        version="1",
        tenant="team-a",
        owner="team-a",
        model_policy={"provider_allowlist": ["litellm"]},
    )
    published = PublishedAgent(
        manifest=manifest,
        digest="abc",
        signature="sha256:abc",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        artifact=_artifact(),
    )

    assert published.artifact == _artifact()


def test_schema_exported():
    path = ROOT / "docs" / "contracts" / "agent_artifact.schema.json"
    exported = json.loads(path.read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(AgentArtifact.model_json_schema(), indent=2, sort_keys=True))

    assert exported == expected
