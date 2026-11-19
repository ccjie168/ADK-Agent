"""Envelope encryption for tenant credentials (ADR-0025)."""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_VERSION = 1
_V2 = 2
_NONCE = 12
_SAFE_VAULT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_VAULT_CIPHERTEXT = re.compile(r"vault:(v[0-9]+):[A-Za-z0-9+/_=-]+")
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


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

    def unwrap_dek(self, wrapped: Mapping[str, Any], aad: bytes) -> bytes:
        if not isinstance(wrapped, Mapping) or wrapped.get("v") != _VERSION:
            raise KeyBackendError("unsupported secret format")
        key_id = wrapped.get("key_id")
        if not isinstance(key_id, str) or key_id not in self._keys:
            raise KeyBackendError("secret key id is not available")
        try:
            dek_nonce = base64.b64decode(wrapped["dek_nonce"], validate=True)
            wrapped_dek = base64.b64decode(wrapped["wrapped_dek"], validate=True)
        except (KeyError, ValueError, TypeError) as exc:
            raise KeyBackendError("secret payload is malformed") from exc
        try:
            return AESGCM(self._keys[key_id]).decrypt(dek_nonce, wrapped_dek, aad)
        except (InvalidTag, ValueError) as exc:
            raise KeyBackendError("secret payload failed to unwrap") from exc

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
        if not isinstance(wrapped, Mapping):
            raise KeyBackendError("secret payload is malformed")
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
            nonce_bytes = base64.b64decode(nonce, validate=True)
            value_bytes = base64.b64decode(ciphertext, validate=True)
        except ValueError as exc:
            raise KeyBackendError("secret payload is malformed") from exc
        if len(nonce_bytes) != _NONCE or not value_bytes:
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

    @classmethod
    def from_file(cls, path: str | Path) -> LocalKeyBackend:
        file = Path(path)
        try:
            if os.name != "nt":
                mode = file.stat().st_mode
                if mode & (stat.S_IRWXG | stat.S_IRWXO):
                    raise KeyBackendError(
                        f"keyring file {path} must not be group or world readable"
                    )
            text = file.read_text(encoding="utf-8")
        except OSError as exc:
            raise KeyBackendError(f"cannot read keyring file {path}") from exc
        except UnicodeDecodeError as exc:
            raise KeyBackendError(f"keyring file {path} is not valid UTF-8") from exc
        return cls.from_json(text)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise KeyBackendError("secret payload is malformed") from None


def _vault_field(data: Any, name: str) -> str:
    if not isinstance(data, dict):
        raise KeyBackendError("vault returned an invalid response")
    body = data.get("data")
    if not isinstance(body, dict):
        raise KeyBackendError("vault returned an invalid response")
    value = body.get(name)
    if not isinstance(value, str) or not value:
        raise KeyBackendError("vault returned an invalid response")
    return value


def _vault_version(ciphertext: str) -> str:
    found = _VAULT_CIPHERTEXT.fullmatch(ciphertext)
    if found is None:
        raise KeyBackendError("vault returned an invalid response")
    return f"vault:{found.group(1)}"


class VaultKeyBackend:
    """Wrap data keys with the Vault/OpenBao Transit engine (ADR-0027)."""

    def __init__(
        self,
        transport: Callable[[str, dict[str, Any]], dict[str, Any]],
        key: str,
        *,
        mount: str = "transit",
    ) -> None:
        if _SAFE_VAULT_NAME.fullmatch(key) is None:
            raise KeyBackendError("ADK_VAULT_KEY is invalid")
        if _SAFE_VAULT_NAME.fullmatch(mount) is None:
            raise KeyBackendError("ADK_VAULT_TRANSIT_MOUNT is invalid")
        self._send = transport
        self._key = key
        self._mount = mount

    def _path(self, operation: str) -> str:
        return f"{self._mount}/{operation}/{self._key}"

    def _encrypt_dek(self, dek: bytes) -> str:
        data = self._send(self._path("encrypt"), {"plaintext": _b64encode(dek)})
        ciphertext = _vault_field(data, "ciphertext")
        _vault_version(ciphertext)
        return ciphertext

    def _decrypt_dek(self, ciphertext: str) -> bytes:
        data = self._send(self._path("decrypt"), {"ciphertext": ciphertext})
        return _b64decode(_vault_field(data, "plaintext"))

    def _rewrap_dek(self, ciphertext: str) -> str:
        data = self._send(self._path("rewrap"), {"ciphertext": ciphertext})
        wrapped = _vault_field(data, "ciphertext")
        _vault_version(wrapped)
        return wrapped

    def _payload(self, wrapped: Mapping[str, Any]) -> tuple[str, str, str]:
        version = wrapped.get("v") if isinstance(wrapped, Mapping) else None
        if type(version) is not int or version != _V2 or wrapped.get("backend") != "vault":
            raise KeyBackendError("unsupported secret format")
        wrapped_dek = wrapped.get("wrapped_dek")
        nonce = wrapped.get("nonce")
        ciphertext = wrapped.get("ciphertext")
        if (
            not isinstance(wrapped_dek, str)
            or not isinstance(nonce, str)
            or not isinstance(ciphertext, str)
        ):
            raise KeyBackendError("secret payload is malformed")
        if len(_b64decode(nonce)) != _NONCE or not _b64decode(ciphertext):
            raise KeyBackendError("secret payload is malformed")
        return wrapped_dek, nonce, ciphertext

    def current_key_id(self) -> str:
        return _vault_version(self._encrypt_dek(os.urandom(32)))

    def wrap(self, plaintext: bytes, aad: bytes) -> dict[str, Any]:
        dek = os.urandom(32)
        nonce = os.urandom(_NONCE)
        try:
            ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
        except (InvalidTag, ValueError) as exc:  # pragma: no cover - encrypt cannot fail
            raise KeyBackendError("secret payload failed to wrap") from exc
        wrapped_dek = self._encrypt_dek(dek)
        return {
            "v": _V2,
            "backend": "vault",
            "key_id": _vault_version(wrapped_dek),
            "wrapped_dek": wrapped_dek,
            "nonce": _b64encode(nonce),
            "ciphertext": _b64encode(ciphertext),
        }

    def wrap_dek(self, dek: bytes, *, nonce: str, ciphertext: str) -> dict[str, Any]:
        if len(dek) != 32 or len(_b64decode(nonce)) != _NONCE or not _b64decode(ciphertext):
            raise KeyBackendError("secret payload is malformed")
        wrapped_dek = self._encrypt_dek(dek)
        return {
            "v": _V2,
            "backend": "vault",
            "key_id": _vault_version(wrapped_dek),
            "wrapped_dek": wrapped_dek,
            "nonce": nonce,
            "ciphertext": ciphertext,
        }

    def unwrap_dek(self, wrapped: Mapping[str, Any], aad: bytes) -> bytes:
        wrapped_dek, _nonce, _ciphertext = self._payload(wrapped)
        return self._decrypt_dek(wrapped_dek)

    def unwrap(self, wrapped: Mapping[str, Any], aad: bytes) -> bytes:
        wrapped_dek, nonce, ciphertext = self._payload(wrapped)
        dek = self._decrypt_dek(wrapped_dek)
        try:
            return AESGCM(dek).decrypt(_b64decode(nonce), _b64decode(ciphertext), aad)
        except (InvalidTag, ValueError) as exc:
            raise KeyBackendError("secret payload failed to unwrap") from exc

    def rewrap(self, wrapped: Mapping[str, Any], aad: bytes) -> dict[str, Any]:
        wrapped_dek, nonce, ciphertext = self._payload(wrapped)
        new_wrapped = self._rewrap_dek(wrapped_dek)
        return {
            "v": _V2,
            "backend": "vault",
            "key_id": _vault_version(new_wrapped),
            "wrapped_dek": new_wrapped,
            "nonce": nonce,
            "ciphertext": ciphertext,
        }


def _read_secret_file(path: str, label: str) -> str:
    file = Path(path)
    try:
        if os.name != "nt":
            mode = file.stat().st_mode
            if mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise KeyBackendError(f"{label} must not be group or world readable")
        text = file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise KeyBackendError(f"cannot read {label}") from exc
    except UnicodeDecodeError as exc:
        raise KeyBackendError(f"{label} is not valid UTF-8") from exc
    if not text:
        raise KeyBackendError(f"{label} is empty")
    return text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the Vault token is never forwarded elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate_token(token: str, label: str) -> str:
    token = token.strip()
    if not token:
        raise KeyBackendError(f"{label} is empty")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in token):
        raise KeyBackendError(f"{label} must be a single line without spaces")
    return token


def _vault_transport(
    addr: str,
    token: str,
    *,
    namespace: str | None,
    timeout: float,
    cacert: str | None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    context = ssl.create_default_context(cafile=cacert)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _NoRedirect()
    )

    def send(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Vault-Token": token, "Content-Type": "application/json"}
        if namespace is not None:
            headers["X-Vault-Namespace"] = namespace
        request = urllib.request.Request(
            f"{addr}/v1/{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(65537)
            if len(body) > 65536:
                raise KeyBackendError("vault returned an invalid response")
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code == 403:
                raise KeyBackendError("vault denied the request") from None
            raise KeyBackendError(f"vault returned HTTP {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise KeyBackendError("vault is unreachable") from None
        except ValueError:
            raise KeyBackendError("vault request is invalid") from None
        try:
            parsed = json.loads(body)
        except ValueError:
            raise KeyBackendError("vault returned an invalid response") from None
        if not isinstance(parsed, dict):
            raise KeyBackendError("vault returned an invalid response")
        return parsed

    return send


def _load_vault_backend(
    variable: str, file_variable: str, *, allow_local: bool = False
) -> VaultKeyBackend:
    if not allow_local and (
        os.environ.get(variable) is not None or os.environ.get(file_variable) is not None
    ):
        raise KeyBackendError(f"vault mode cannot be combined with {variable} or {file_variable}")
    addr = (os.environ.get("ADK_VAULT_ADDR") or "").strip().rstrip("/")
    if not addr:
        raise KeyBackendError("ADK_VAULT_ADDR is required")
    try:
        parts = urllib.parse.urlsplit(addr)
        _port = parts.port
    except ValueError:
        raise KeyBackendError("ADK_VAULT_ADDR is not a valid URL") from None
    if parts.scheme == "http":
        if parts.hostname not in _LOOPBACK:
            raise KeyBackendError("ADK_VAULT_ADDR must use https unless it is loopback")
    elif parts.scheme != "https":
        raise KeyBackendError("ADK_VAULT_ADDR must be an https URL")
    if not parts.hostname:
        raise KeyBackendError("ADK_VAULT_ADDR must include a host")
    key = (os.environ.get("ADK_VAULT_KEY") or "").strip()
    if not key:
        raise KeyBackendError("ADK_VAULT_KEY is required")
    mount = (os.environ.get("ADK_VAULT_TRANSIT_MOUNT") or "transit").strip()
    token = os.environ.get("ADK_VAULT_TOKEN")
    token_file = os.environ.get("ADK_VAULT_TOKEN_FILE") or None
    if token is not None and token_file is not None:
        raise KeyBackendError("set only one of ADK_VAULT_TOKEN or ADK_VAULT_TOKEN_FILE")
    if token is None and token_file is None:
        raise KeyBackendError("set ADK_VAULT_TOKEN_FILE or ADK_VAULT_TOKEN")
    if token_file is not None:
        token = _validate_token(
            _read_secret_file(token_file, "ADK_VAULT_TOKEN_FILE"), "ADK_VAULT_TOKEN_FILE"
        )
    else:
        if token is None:
            raise KeyBackendError("ADK_VAULT_TOKEN is empty")
        token = _validate_token(token, "ADK_VAULT_TOKEN")
    raw_timeout = os.environ.get("ADK_VAULT_TIMEOUT") or "5"
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise KeyBackendError("ADK_VAULT_TIMEOUT must be a number") from None
    if not 0 < timeout < 3600:
        raise KeyBackendError("ADK_VAULT_TIMEOUT must be between 0 and 3600 seconds")
    namespace = os.environ.get("ADK_VAULT_NAMESPACE") or None
    cacert = os.environ.get("ADK_VAULT_CACERT") or None
    try:
        transport = _vault_transport(
            addr, token, namespace=namespace, timeout=timeout, cacert=cacert
        )
    except (OSError, ValueError):
        raise KeyBackendError("ADK_VAULT_CACERT cannot be read") from None
    return VaultKeyBackend(transport, key, mount=mount)


def load_local_backend(
    *, variable: str = "ADK_SECRET_KEKS", file_variable: str = "ADK_SECRET_KEKS_FILE"
) -> LocalKeyBackend:
    """Load the local keyring, requiring exactly one source."""
    value = os.environ.get(variable)
    path = os.environ.get(file_variable) or None
    if value is not None and path is not None:
        raise KeyBackendError(f"set only one of {variable} or {file_variable}")
    if path:
        return LocalKeyBackend.from_file(path)
    if value is None:
        raise KeyBackendError(f"set {variable} or {file_variable}")
    return LocalKeyBackend.from_json(value)


def load_key_backend(
    *,
    variable: str = "ADK_SECRET_KEKS",
    file_variable: str = "ADK_SECRET_KEKS_FILE",
    allow_local: bool = False,
) -> KeyBackend | None:
    """Pick the local keyring or the Vault backend from the environment."""
    selected = os.environ.get("ADK_SECRET_BACKEND") or "local"
    if selected == "vault":
        return _load_vault_backend(variable, file_variable, allow_local=allow_local)
    if selected != "local":
        raise KeyBackendError("ADK_SECRET_BACKEND must be local or vault")
    value = os.environ.get(variable)
    path = os.environ.get(file_variable) or None
    if value is not None and path is not None:
        raise KeyBackendError(f"set only one of {variable} or {file_variable}")
    if path:
        return LocalKeyBackend.from_file(path)
    return None if value is None else LocalKeyBackend.from_json(value)


__all__ = [
    "KeyBackend",
    "KeyBackendError",
    "LocalKeyBackend",
    "VaultKeyBackend",
    "load_key_backend",
    "load_local_backend",
]
