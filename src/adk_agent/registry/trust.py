"""Trusted publisher keys for artifact verification (ADR-0008)."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from ..core import AgentArtifact
from .signing import verify_digest


class ArtifactTrustError(RuntimeError):
    """An artifact is unsigned, signed by an unknown key, or tampered with."""


class TrustStore:
    """Ed25519 public keys indexed by key id."""

    def __init__(self, keys: Mapping[str, bytes]) -> None:
        self._keys = {kid: bytes(value) for kid, value in keys.items()}

    def verify(self, artifact: AgentArtifact) -> None:
        if artifact.signature is None or artifact.key_id is None:
            raise ArtifactTrustError("artifact has no signature")
        key_bytes = self._keys.get(artifact.key_id)
        if key_bytes is None:
            raise ArtifactTrustError("artifact key id is not trusted")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
        except ImportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ArtifactTrustError("trusted key is not a valid Ed25519 public key") from exc
        if not verify_digest(artifact.digest, artifact.signature, public_key):
            raise ArtifactTrustError("artifact signature is invalid")

    @classmethod
    def from_json(cls, text: str) -> TrustStore:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise ArtifactTrustError("artifact keys must be a JSON object") from None
        if not isinstance(data, dict):
            raise ArtifactTrustError("artifact keys must be a JSON object")
        keys: dict[str, bytes] = {}
        for kid, value in data.items():
            if not isinstance(kid, str) or not kid:
                raise ArtifactTrustError("artifact key ids must be non-empty strings")
            if not isinstance(value, str) or len(value) != 64:
                raise ArtifactTrustError("artifact keys must be 64 hex characters")
            try:
                keys[kid] = bytes.fromhex(value)
            except ValueError:
                raise ArtifactTrustError("artifact keys must be 64 hex characters") from None
        return cls(keys)

    @classmethod
    def from_env(cls, variable: str = "ADK_ARTIFACT_KEYS") -> TrustStore | None:
        value = os.environ.get(variable)
        return None if value is None else cls.from_json(value)


__all__ = ["ArtifactTrustError", "TrustStore"]
