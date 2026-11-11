"""Tool call shapes shared by the gateway and tool providers."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .policy import DataClass


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: Any
    data_classes: list[DataClass] = Field(default_factory=list)
