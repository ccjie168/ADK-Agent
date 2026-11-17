"""SLICE-139: envelope encryption for tenant credentials (ADR-0025)."""

from __future__ import annotations

import base64
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
