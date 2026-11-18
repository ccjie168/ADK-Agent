"""SLICE-139: envelope encryption for tenant credentials (ADR-0025)."""

from __future__ import annotations

import base64
import json
import os

import pytest

from adk_agent.secretstore import LocalKeyBackend
from adk_agent.secretstore.keys import KeyBackendError


def _keyring() -> LocalKeyBackend:
    return LocalKeyBackend({"k1": os.urandom(32)}, "k1")


def test_round_trip_with_aad():
    backend = _keyring()
    aad = b"adk-credential:acme:crm"

    wrapped = backend.wrap(b"token", aad)

    assert backend.unwrap(wrapped, aad) == b"token"
    assert wrapped["key_id"] == "k1"
    assert "token" not in str(wrapped)


def test_aad_mismatch_is_rejected():
    backend = _keyring()
    wrapped = backend.wrap(b"token", b"adk-credential:acme:crm")

    with pytest.raises(KeyBackendError):
        backend.unwrap(wrapped, b"adk-credential:other:crm")


def test_unknown_key_id_is_rejected():
    backend = _keyring()
    wrapped = backend.wrap(b"token", b"aad")
    wrapped["key_id"] = "gone"

    with pytest.raises(KeyBackendError):
        backend.unwrap(wrapped, b"aad")


def test_rotation_keeps_old_keys():
    first = _keyring()
    wrapped = first.wrap(b"token", b"aad")
    old = first._keys["k1"]

    rotated = LocalKeyBackend({"k1": old, "k2": os.urandom(32)}, "k2")

    assert rotated.current_key_id() == "k2"
    assert rotated.unwrap(wrapped, b"aad") == b"token"


def test_from_json_and_env(monkeypatch):
    raw = os.urandom(32)
    text = '{"active": "k1", "keys": {"k1": "' + base64.b64encode(raw).decode("ascii") + '"}}'

    backend = LocalKeyBackend.from_json(text)

    assert backend.current_key_id() == "k1"
    monkeypatch.setenv("ADK_SECRET_KEKS", text)
    assert LocalKeyBackend.from_env() is not None


def test_bad_keyring_is_rejected():
    with pytest.raises(KeyBackendError):
        LocalKeyBackend.from_json("{}")


def test_rewrap_moves_the_data_key_to_the_active_key():
    old = _keyring()
    aad = b"adk-credential:acme:crm"
    wrapped = old.wrap(b"token", aad)
    rotated = LocalKeyBackend({"k1": old._keys["k1"], "k2": os.urandom(32)}, "k2")

    rewrapped = rotated.rewrap(wrapped, aad)

    assert rewrapped["key_id"] == "k2"
    assert rewrapped["ciphertext"] == wrapped["ciphertext"]
    assert rewrapped["nonce"] == wrapped["nonce"]
    assert rotated.unwrap(rewrapped, aad) == b"token"
    with pytest.raises(KeyBackendError):
        old.unwrap(rewrapped, aad)


def test_rewrap_is_idempotent_on_the_active_key():
    backend = _keyring()
    wrapped = backend.wrap(b"token", b"aad")

    assert backend.rewrap(wrapped, b"aad") == wrapped


def test_rewrap_rejects_a_different_aad():
    backend = _keyring()
    wrapped = backend.wrap(b"token", b"adk-credential:acme:crm")

    with pytest.raises(KeyBackendError):
        backend.rewrap(wrapped, b"adk-credential:other:crm")


def test_rewrap_rejects_an_unknown_key_id():
    backend = _keyring()
    wrapped = backend.wrap(b"token", b"aad")
    wrapped["key_id"] = "gone"

    with pytest.raises(KeyBackendError):
        backend.rewrap(wrapped, b"aad")


def test_rewrap_rejects_a_malformed_payload():
    old = _keyring()
    aad = b"aad"
    wrapped = old.wrap(b"token", aad)
    rotated = LocalKeyBackend({"k1": old._keys["k1"], "k2": os.urandom(32)}, "k2")

    bad_nonce = dict(wrapped, nonce=123)
    with pytest.raises(KeyBackendError):
        rotated.rewrap(bad_nonce, aad)

    short_nonce = dict(wrapped, nonce=base64.b64encode(b"x").decode("ascii"))
    with pytest.raises(KeyBackendError):
        rotated.rewrap(short_nonce, aad)

    garbage_nonce = dict(wrapped, nonce="!!!")
    with pytest.raises(KeyBackendError):
        rotated.rewrap(garbage_nonce, aad)

    short_dek_nonce = dict(wrapped, dek_nonce=base64.b64encode(b"x").decode("ascii"))
    with pytest.raises(KeyBackendError):
        rotated.rewrap(short_dek_nonce, aad)


def _keyring_text(raw: bytes) -> str:
    return json.dumps({"active": "k1", "keys": {"k1": base64.b64encode(raw).decode("ascii")}})


def test_load_key_backend_reads_a_file(tmp_path, monkeypatch):
    from adk_agent.secretstore import load_key_backend

    path = tmp_path / "keks.json"
    path.write_text(_keyring_text(os.urandom(32)), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", str(path))

    backend = load_key_backend()

    assert backend is not None
    assert backend.current_key_id() == "k1"


def test_load_key_backend_rejects_env_and_file(monkeypatch):
    from adk_agent.secretstore import load_key_backend

    monkeypatch.setenv("ADK_SECRET_KEKS", _keyring_text(os.urandom(32)))
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", "keks.json")

    with pytest.raises(KeyBackendError, match="only one"):
        load_key_backend()


@pytest.mark.skipif(os.name == "nt", reason="file modes are not enforced on Windows")
def test_keyring_file_permissions_are_checked(tmp_path, monkeypatch):
    from adk_agent.secretstore import load_key_backend

    path = tmp_path / "keks.json"
    path.write_text(_keyring_text(os.urandom(32)), encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", str(path))

    with pytest.raises(KeyBackendError, match="group or world"):
        load_key_backend()


def test_keyring_file_missing_is_rejected(tmp_path, monkeypatch):
    from adk_agent.secretstore import load_key_backend

    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", str(tmp_path / "missing.json"))

    with pytest.raises(KeyBackendError, match="cannot read"):
        load_key_backend()


def test_keyring_file_must_be_utf8(tmp_path, monkeypatch):
    from adk_agent.secretstore import load_key_backend

    path = tmp_path / "keks.bin"
    path.write_bytes(b"\xff\xfe\x00")
    if os.name != "nt":
        path.chmod(0o600)
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", str(path))

    with pytest.raises(KeyBackendError, match="UTF-8"):
        load_key_backend()


def test_empty_file_variable_does_not_conflict(monkeypatch):
    from adk_agent.secretstore import load_key_backend

    monkeypatch.setenv("ADK_SECRET_KEKS", _keyring_text(os.urandom(32)))
    monkeypatch.setenv("ADK_SECRET_KEKS_FILE", "")

    backend = load_key_backend()

    assert backend is not None
