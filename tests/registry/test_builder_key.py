"""SLICE-138: builder signatures gate in_process artifacts."""

from __future__ import annotations

import importlib.util

import pytest

from adk_agent.core import AgentArtifact
from adk_agent.registry import TrustStore
from adk_agent.registry.signing import sign_digest
from adk_agent.registry.trust import ArtifactTrustError

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")


def _keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    builder = Ed25519PrivateKey.generate()
    other = Ed25519PrivateKey.generate()
    raw = builder.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return builder, other, raw


@needs_crypto
def test_builder_signature_is_verified():
    builder, _, raw = _keys()
    digest = "sha256:" + "a" * 64
    artifact = AgentArtifact(
        digest=digest,
        size=1,
        builder_signature=sign_digest(digest, builder),
        builder_key_id="builder-1",
    )
    trust = TrustStore({"builder-1": raw})

    trust.verify_builder(artifact)


@needs_crypto
def test_missing_builder_signature_is_rejected():
    artifact = AgentArtifact(digest="sha256:" + "a" * 64, size=1)

    with pytest.raises(ArtifactTrustError):
        TrustStore({}).verify_builder(artifact)


@needs_crypto
def test_untrusted_builder_key_is_rejected():
    builder, other, raw = _keys()
    digest = "sha256:" + "a" * 64
    artifact = AgentArtifact(
        digest=digest,
        size=1,
        builder_signature=sign_digest(digest, other),
        builder_key_id="builder-1",
    )

    with pytest.raises(ArtifactTrustError):
        TrustStore({"builder-1": raw}).verify_builder(artifact)
