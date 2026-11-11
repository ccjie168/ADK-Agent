"""Identity types. Every call carries one principal."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    kind: Literal["human", "service", "agent"]
    roles: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
