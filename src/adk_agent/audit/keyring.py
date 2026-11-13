"""Signing keyring for rotating audit keys without losing history (SLICE-060)."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

_KID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class KeyringError(Exception):
    """The ADK_AUDIT_KEYRING value cannot be used."""


class SigningKeyring(BaseModel):
    """Active key, retained keys, and the key for records without a kid."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active: str
    keys: dict[str, str]
    legacy: str | None = None

    @model_validator(mode="after")
    def _check_keys(self) -> SigningKeyring:
        if not self.keys:
            raise ValueError("keys must not be empty")
        for kid, secret in self.keys.items():
            if _KID.fullmatch(kid) is None:
                raise ValueError("key id is invalid")
            if not secret:
                raise ValueError("key must not be empty")
        if self.active not in self.keys:
            raise ValueError("active must exist in keys")
        if self.legacy is not None and self.legacy not in self.keys:
            raise ValueError("legacy must exist in keys")
        return self

    def key_for(self, kid: str | None) -> str | None:
        if kid is None:
            return None if self.legacy is None else self.keys.get(self.legacy)
        return self.keys.get(kid)

    @classmethod
    def from_env(cls, value: str | None) -> SigningKeyring | None:
        if value is None:
            return None
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            raise KeyringError("ADK_AUDIT_KEYRING must be a JSON object") from None
        if not isinstance(data, dict):
            raise KeyringError("ADK_AUDIT_KEYRING must be a JSON object")
        try:
            return cls.model_validate(data)
        except ValidationError:
            raise KeyringError("ADK_AUDIT_KEYRING is invalid") from None


__all__ = ["KeyringError", "SigningKeyring"]
