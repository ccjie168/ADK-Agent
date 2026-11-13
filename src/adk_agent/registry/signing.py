"""Ed25519 signatures for published artifacts (ADR-0008)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_INSTALL_HINT = "install publishing support with: pip install 'adk-agent[publish]'"


class PublishUnavailable(RuntimeError):
    """Signing support or a usable publisher key is missing."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{reason}; {_INSTALL_HINT}")


def _ed25519() -> tuple[Any, Any, Any]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise PublishUnavailable("cryptography is not installed") from exc
    return serialization, Ed25519PrivateKey, (Ed25519PublicKey, InvalidSignature)


def load_private_key(path: str | Path) -> Any:
    serialization, Ed25519PrivateKey, _ = _ed25519()
    try:
        key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    except Exception as exc:  # noqa: BLE001
        raise PublishUnavailable(
            f"could not read the publisher key ({type(exc).__name__})"
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise PublishUnavailable("publisher key must be an Ed25519 private key")
    return key


def sign_digest(digest: str, private_key: Any) -> str:
    _, Ed25519PrivateKey, _ = _ed25519()
    if not isinstance(private_key, Ed25519PrivateKey):
        raise PublishUnavailable("publisher key must be an Ed25519 private key")
    return private_key.sign(digest.encode("utf-8")).hex()


def verify_digest(digest: str, signature: str, public_key: Any) -> bool:
    _, _, (Ed25519PublicKey, InvalidSignature) = _ed25519()
    if not isinstance(public_key, Ed25519PublicKey):
        return False
    try:
        public_key.verify(bytes.fromhex(signature), digest.encode("utf-8"))
    except (InvalidSignature, ValueError):
        return False
    return True


__all__ = ["PublishUnavailable", "load_private_key", "sign_digest", "verify_digest"]
