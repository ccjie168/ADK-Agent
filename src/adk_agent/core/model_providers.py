"""Model provider records (ADR-0045).

Records hold metadata and a ``secret://`` reference only; secret values never
enter this model.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .credentials import parse_credential_ref

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
KINDS = ("litellm", "gemini", "claude", "vertex")


class ModelProviderRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: str = Field(pattern=_SAFE_ID)
    kind: str
    model: str = Field(min_length=1, max_length=256)
    base_url: str | None = Field(default=None, max_length=512)
    secret_ref: str | None = None
    enabled: bool = True
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=256)

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, value: str) -> str:
        if value not in KINDS:
            raise ValueError("unsupported provider kind")
        return value

    @field_validator("secret_ref")
    @classmethod
    def _check_secret_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parse_credential_ref(value)
        return value


__all__ = ["KINDS", "ModelProviderRecord"]
