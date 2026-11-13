"""SLICE-066: Ed25519 signing for published artifacts."""

from __future__ import annotations

import importlib.util

import pytest

from adk_agent.registry import PublishUnavailable, load_private_key, sign_digest, verify_digest

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")

DIGEST = "sha256:" + "a" * 64


def _key(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    path = tmp_path / "publisher.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key, path


@needs_crypto
def test_sign_and_verify(tmp_path):
    key, _ = _key(tmp_path)

    signature = sign_digest(DIGEST, key)

    assert len(signature) == 128
    assert verify_digest(DIGEST, signature, key.public_key()) is True


@needs_crypto
def test_wrong_key_fails(tmp_path):
    key, _ = _key(tmp_path)
    other, _ = _key(tmp_path)

    signature = sign_digest(DIGEST, key)

    assert verify_digest(DIGEST, signature, other.public_key()) is False


@needs_crypto
def test_tampered_digest_fails(tmp_path):
    key, _ = _key(tmp_path)
    signature = sign_digest(DIGEST, key)

    assert verify_digest("sha256:" + "b" * 64, signature, key.public_key()) is False


@needs_crypto
def test_load_private_key(tmp_path):
    key, path = _key(tmp_path)

    loaded = load_private_key(path)

    signature = sign_digest(DIGEST, loaded)
    assert verify_digest(DIGEST, signature, key.public_key()) is True


@needs_crypto
def test_load_rejects_non_ed25519(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "rsa.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    with pytest.raises(PublishUnavailable):
        load_private_key(path)
