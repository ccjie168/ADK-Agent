"""Envelope encryption for tenant credentials (ADR-0025)."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = 1
_NONCE = 12


class KeyBackendError(RuntimeError):
    """The key backend cannot wrap or unwrap a secret."""


class KeyBackend(Protocol):
    def wrap(self, plaintext: bytes, aad: bytes) -> dict[str, Any]: ...

    def unwrap(self, wrapped: Mapping[str, Any], aad: bytes) -> bytes: ...

    def rewrap(self, wrapped: Mapping[str, Any], aad: bytes) -> dict[str, Any]: ...

    def current_key_id(self) -> str: ...


def _kek(raw: bytes) -> bytes:
    if len(raw) != 32:
        raise KeyBackendError("KEK must be 32 bytes")
    return raw


class LocalKeyBackend:
    """AES-256-GCM envelope encryption with local KEKs indexed by id."""

    def __init__(self, keys: Mapping[str, bytes], active: str) -> None:
        if not keys or active not in keys:
            raise KeyBackendError("active KEK id is not in the keyring")
        self._keys = {kid: _kek(bytes(value)) for kid, value in keys.items()}
        self._active = active

    def current_key_id(self) -> str:
        return self._active

    def wrap(self, plaintext: bytes, aad: bytes) -> dict[str, Any]:
        dek = os.urandom(32)
        nonce = os.urandom(_NONCE)
        ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
        kek = self._keys[self._active]
        dek_nonce = os.urandom(_NONCE)
        wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, aad)
        return {
            "v": _VERSION,
            "key_id": self._active,
            "dek_nonce": base64.b64encode(dek_nonce).decode("ascii"),
            "wrapped_dek": base64.b64encode(wrapped_dek).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def unwrap(self, wrapped: Mapping[str, Any], aad: bytes) -> bytes:
        if wrapped.get("v") != _VERSION:
            raise KeyBackendError("unsupported secret format")
        key_id = wrapped.get("key_id")
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise KeyBackendError("secret key id is not available")
        try:
            dek_nonce = base64.b64decode(wrapped["dek_nonce"], validate=True)
            wrapped_dek = base64.b64decode(wrapped["wrapped_dek"], validate=True)
            nonce = base64.b64decode(wrapped["nonce"], validate=True)
            ciphertext = base64.b64decode(wrapped["ciphertext"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise KeyBackendError("secret payload is malformed") from exc
        try:
            dek = AESGCM(self._keys[key_id]).decrypt(dek_nonce, wrapped_dek, aad)
        except InvalidTag as exc:
            raise KeyBackendError("secret payload failed to unwrap") from exc
        try:
            return AESGCM(dek).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise KeyBackendError("secret payload failed to decrypt") from exc

    def rewrap(self, wrapped: Mapping[str, Any], aad: bytes) -> dict[str, Any]:
        if wrapped.get("v") != _VERSION:
            raise KeyBackendError("unsupported secret format")
        key_id = wrapped.get("key_id")
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise KeyBackendError("secret key id is not available")
        try:
            dek_nonce = base64.b64decode(wrapped["dek_nonce"], validate=True)
            wrapped_dek = base64.b64decode(wrapped["wrapped_dek"], validate=True)
            nonce = wrapped["nonce"]
            ciphertext = wrapped["ciphertext"]
        except (KeyError, ValueError, TypeError) as exc:
            raise KeyBackendError("secret payload is malformed") from exc
        if not isinstance(nonce, str) or not isinstance(ciphertext, str):
            raise KeyBackendError("secret payload is malformed")
        try:
            dek = AESGCM(self._keys[key_id]).decrypt(dek_nonce, wrapped_dek, aad)
        except (InvalidTag, ValueError) as exc:
            raise KeyBackendError("secret payload failed to unwrap") from exc
        if key_id == self._active:
            return dict(wrapped)
        new_nonce = os.urandom(_NONCE)
        try:
            new_dek = AESGCM(self._keys[self._active]).encrypt(new_nonce, dek, aad)
        except InvalidTag as exc:  # pragma: no cover - encrypt cannot fail on a valid KEK
            raise KeyBackendError("secret payload failed to rewrap") from exc
        return {
            "v": _VERSION,
            "key_id": self._active,
            "dek_nonce": base64.b64encode(new_nonce).decode("ascii"),
            "wrapped_dek": base64.b64encode(new_dek).decode("ascii"),
            "nonce": nonce,
            "ciphertext": ciphertext,
        }

    @classmethod
    def from_json(cls, text: str) -> LocalKeyBackend:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise KeyBackendError("KEK keyring must be a JSON object") from None
        if not isinstance(data, dict):
            raise KeyBackendError("KEK keyring must be a JSON object")
        active = data.get("active")
        keys = data.get("keys")
        if not isinstance(active, str) or not isinstance(keys, dict):
            raise KeyBackendError("KEK keyring needs `active` and `keys`")
        decoded: dict[str, bytes] = {}
        for kid, value in keys.items():
            if not isinstance(kid, str) or not isinstance(value, str):
                raise KeyBackendError("KEK ids and values must be strings")
            try:
                decoded[kid] = base64.b64decode(value, validate=True)
            except ValueError:
                raise KeyBackendError("KEK values must be base64") from None
        return cls(decoded, active)

    @classmethod
    def from_env(cls, variable: str = "ADK_SECRET_KEKS") -> LocalKeyBackend | None:
        value = os.environ.get(variable)
        return None if value is None else cls.from_json(value)


__all__ = ["KeyBackend", "KeyBackendError", "LocalKeyBackend"]
