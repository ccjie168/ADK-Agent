"""SLICE-160: the Vault/OpenBao Transit key backend (ADR-0027)."""

from __future__ import annotations

import base64

import pytest

from adk_agent.secretstore import (
    KeyBackendError,
    LocalKeyBackend,
    VaultKeyBackend,
    load_key_backend,
)

AAD = b"adk-credential:acme/crm"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_")


class FakeVault:
    def __init__(self, key: str = "key") -> None:
        self.version = 1
        self.key = key
        self.blobs: dict[str, bytes] = {}
        self.calls: list[str] = []

    def _store(self, data: bytes) -> str:
        token = f"{len(self.blobs):04d}"
        self.blobs[token] = data
        return f"vault:v{self.version}:{token}"

    def __call__(self, path: str, payload: dict) -> dict:
        self.calls.append(path)
        if path == f"transit/encrypt/{self.key}":
            return {"data": {"ciphertext": self._store(_unb64(payload["plaintext"]))}}
        if path == f"transit/decrypt/{self.key}":
            token = str(payload["ciphertext"]).split(":")[2]
            return {"data": {"plaintext": base64.b64encode(self.blobs[token]).decode("ascii")}}
        if path == f"transit/rewrap/{self.key}":
            token = str(payload["ciphertext"]).split(":")[2]
            return {"data": {"ciphertext": self._store(self.blobs[token])}}
        raise AssertionError(f"unexpected path {path}")


def _backend(fake: FakeVault | None = None) -> VaultKeyBackend:
    return VaultKeyBackend(fake or FakeVault(), "key")


def test_wrap_and_unwrap_roundtrip():
    backend = _backend()
    wrapped = backend.wrap(b"secret", AAD)

    assert wrapped["v"] == 2
    assert wrapped["backend"] == "vault"
    assert wrapped["key_id"] == "vault:v1"
    assert backend.unwrap(wrapped, AAD) == b"secret"


def test_unwrap_rejects_the_wrong_aad():
    backend = _backend()
    wrapped = backend.wrap(b"secret", AAD)

    with pytest.raises(KeyBackendError):
        backend.unwrap(wrapped, b"other")


def test_rewrap_moves_the_dek_to_the_current_version():
    fake = FakeVault()
    backend = _backend(fake)
    wrapped = backend.wrap(b"secret", AAD)
    fake.version = 3

    rewrapped = backend.rewrap(wrapped, AAD)

    assert rewrapped["key_id"] == "vault:v3"
    assert rewrapped["wrapped_dek"] != wrapped["wrapped_dek"]
    assert rewrapped["nonce"] == wrapped["nonce"]
    assert rewrapped["ciphertext"] == wrapped["ciphertext"]
    assert backend.unwrap(rewrapped, AAD) == b"secret"


def test_current_key_id_uses_the_transit_version():
    fake = FakeVault()
    fake.version = 4

    assert _backend(fake).current_key_id() == "vault:v4"


def test_payload_validation():
    backend = _backend()
    with pytest.raises(KeyBackendError):
        backend.unwrap({"v": 1, "key_id": "k1"}, AAD)
    with pytest.raises(KeyBackendError):
        backend.unwrap({"v": 2, "backend": "local"}, AAD)
    with pytest.raises(KeyBackendError):
        backend.unwrap(
            {"v": 2, "backend": "vault", "wrapped_dek": "x", "nonce": "!!", "ciphertext": "x"},
            AAD,
        )


def _vault_env(monkeypatch, tmp_path) -> str:
    token_file = tmp_path / "vault-token"
    token_file.write_text("token-value\n", encoding="utf-8")
    monkeypatch.setenv("ADK_SECRET_BACKEND", "vault")
    monkeypatch.setenv("ADK_VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("ADK_VAULT_KEY", "credential")
    monkeypatch.setenv("ADK_VAULT_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("ADK_VAULT_TOKEN", raising=False)
    for name in ("ADK_SECRET_KEKS", "ADK_SECRET_KEKS_FILE"):
        monkeypatch.delenv(name, raising=False)
    return str(token_file)


def test_load_key_backend_builds_the_vault_backend(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    fake = FakeVault(key="credential")
    captured: dict = {}

    def factory(addr, token, *, namespace, timeout, cacert):
        captured.update(addr=addr, token=token, namespace=namespace, timeout=timeout)
        return fake

    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", factory)

    backend = load_key_backend()

    assert isinstance(backend, VaultKeyBackend)
    assert captured == {
        "addr": "https://vault.example.com",
        "token": "token-value",
        "namespace": None,
        "timeout": 5.0,
    }
    wrapped = backend.wrap(b"secret", AAD)
    assert backend.unwrap(wrapped, AAD) == b"secret"


def test_load_key_backend_rejects_conflicting_vault_config(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADK_VAULT_TOKEN", "other-token")
    with pytest.raises(KeyBackendError):
        load_key_backend()

    monkeypatch.delenv("ADK_VAULT_TOKEN")
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", str(tmp_path / "keks.json"))
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_load_key_backend_rejects_plain_http_off_loopback(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADK_VAULT_ADDR", "http://vault.example.com")
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_load_key_backend_rejects_an_unknown_backend(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_BACKEND", "kms")
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_local_backend_still_reads_v1_records():
    backend = LocalKeyBackend({"k1": b"x" * 32}, "k1")
    wrapped = backend.wrap(b"secret", AAD)

    assert wrapped["v"] == 1
    assert backend.unwrap(wrapped, AAD) == b"secret"
