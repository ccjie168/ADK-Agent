"""SLICE-160: the Vault/OpenBao Transit key backend (ADR-0027)."""

from __future__ import annotations

import base64
import http.server
import os
import threading
import time

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
    if os.name != "nt":
        token_file.chmod(0o600)
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


def test_load_key_backend_rejects_an_invalid_timeout(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADK_VAULT_TIMEOUT", "0")
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_load_key_backend_rejects_an_unknown_backend(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_BACKEND", "kms")
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_load_key_backend_rejects_invalid_addresses(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    for addr in ("https://[::1", "https://vault.example.com:notaport", "https://"):
        monkeypatch.setenv("ADK_VAULT_ADDR", addr)
        with pytest.raises(KeyBackendError):
            load_key_backend()


def test_load_key_backend_rejects_a_missing_ca_file(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ADK_VAULT_CACERT", str(tmp_path / "missing.pem"))
    with pytest.raises(KeyBackendError):
        load_key_backend()


def test_load_key_backend_rejects_a_multiline_token(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    monkeypatch.delenv("ADK_VAULT_TOKEN_FILE")
    monkeypatch.setenv("ADK_VAULT_TOKEN", "line1\nline2")
    with pytest.raises(KeyBackendError) as exc:
        load_key_backend()

    assert "line1" not in str(exc.value)


def test_load_key_backend_rejects_a_multiline_token_file(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    token_file = tmp_path / "vault-token"
    token_file.write_text("REAL-TOKEN\nstray-second-line\n", encoding="utf-8")
    if os.name != "nt":
        token_file.chmod(0o600)

    with pytest.raises(KeyBackendError) as exc:
        load_key_backend()

    assert "REAL-TOKEN" not in str(exc.value)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_token_file_permissions_are_checked(monkeypatch, tmp_path):
    _vault_env(monkeypatch, tmp_path)
    (tmp_path / "vault-token").chmod(0o644)
    with pytest.raises(KeyBackendError):
        load_key_backend()


class _VaultHandler(http.server.BaseHTTPRequestHandler):
    status = 200
    body = b'{"data": {"ciphertext": "vault:v1:x"}}'
    delay = 0.0
    hits: list[str] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        self.rfile.read(length)
        type(self).hits.append(self.path)
        if self.delay:
            time.sleep(self.delay)
        self.send_response(self.status)
        if self.status in {301, 302, 307}:
            self.send_header("Location", "/elsewhere")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args: object) -> None:
        return


def _serve(handler) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def _send(addr: str, *, timeout: float = 2.0):
    from adk_agent.secretstore.keys import _vault_transport

    return _vault_transport(addr, "secret-token", namespace=None, timeout=timeout, cacert=None)


def test_transport_maps_403_without_echoing_the_token():
    class Handler(_VaultHandler):
        status = 403
        body = b"BODY-MARKER"

    server, addr = _serve(Handler)
    try:
        with pytest.raises(KeyBackendError) as exc:
            _send(addr)("transit/encrypt/key", {"plaintext": "x"})
    finally:
        server.shutdown()

    assert "denied" in str(exc.value)
    assert "BODY-MARKER" not in str(exc.value)
    assert "secret-token" not in str(exc.value)


def test_transport_maps_invalid_json():
    class Handler(_VaultHandler):
        body = b"not json"

    server, addr = _serve(Handler)
    try:
        with pytest.raises(KeyBackendError):
            _send(addr)("transit/encrypt/key", {"plaintext": "x"})
    finally:
        server.shutdown()


def test_transport_times_out():
    class Handler(_VaultHandler):
        delay = 0.3

    server, addr = _serve(Handler)
    try:
        with pytest.raises(KeyBackendError):
            _send(addr, timeout=0.05)("transit/encrypt/key", {"plaintext": "x"})
    finally:
        server.shutdown()


def test_transport_does_not_follow_redirects():
    class Handler(_VaultHandler):
        status = 302
        hits: list[str] = []

    server, addr = _serve(Handler)
    try:
        with pytest.raises(KeyBackendError) as exc:
            _send(addr)("transit/encrypt/key", {"plaintext": "x"})
    finally:
        server.shutdown()

    assert "302" in str(exc.value)
    assert Handler.hits == ["/v1/transit/encrypt/key"]


def test_transport_rejects_an_oversized_response():
    class Handler(_VaultHandler):
        body = b"x" * 70000

    server, addr = _serve(Handler)
    try:
        with pytest.raises(KeyBackendError):
            _send(addr)("transit/encrypt/key", {"plaintext": "x"})
    finally:
        server.shutdown()


def test_local_backend_still_reads_v1_records():
    backend = LocalKeyBackend({"k1": b"x" * 32}, "k1")
    wrapped = backend.wrap(b"secret", AAD)

    assert wrapped["v"] == 1
    assert backend.unwrap(wrapped, AAD) == b"secret"
