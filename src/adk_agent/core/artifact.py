"""Agent artifact metadata (ADR-0008)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MEDIA_TYPE: Literal["application/vnd.adk.agent+zip"] = "application/vnd.adk.agent+zip"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class AgentArtifact(BaseModel):
    """A deterministic zip of agent code, addressed by its sha256."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    media_type: Literal["application/vnd.adk.agent+zip"] = MEDIA_TYPE
    size: int = Field(gt=0, le=MAX_ARTIFACT_BYTES)
    entrypoint: str = Field(default="agent.py", pattern=r"^[A-Za-z_][A-Za-z0-9_]*\.py$")
    signature: str | None = Field(default=None, pattern=r"^[0-9a-f]{128}$")
    key_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


__all__ = ["MAX_ARTIFACT_BYTES", "MEDIA_TYPE", "AgentArtifact"]
