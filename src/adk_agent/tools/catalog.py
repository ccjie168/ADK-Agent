"""Read-only tool catalog for the console (UI-4)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"

ToolSource = Literal["function", "openapi", "mcp", "connector"]


class ToolCatalogError(Exception):
    """The tool catalog file is missing, malformed, or has duplicate ids."""


class ToolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1, pattern=_SAFE_NAME)
    description: str = ""
    source: ToolSource
    data_classes: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    tenant: str | None = Field(default=None, pattern=_SAFE_NAME)


class ToolCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    tools: list[ToolEntry] = Field(default_factory=list)


def load_tool_catalog(path: str | Path) -> ToolCatalog:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolCatalogError("tool catalog is not readable JSON") from exc
    try:
        catalog = ToolCatalog.model_validate(payload)
    except ValidationError as exc:
        raise ToolCatalogError("tool catalog is invalid") from exc
    ids = [tool.tool_id for tool in catalog.tools]
    if len(set(ids)) != len(ids):
        raise ToolCatalogError("tool catalog has a duplicate tool_id")
    return catalog


__all__ = ["ToolCatalog", "ToolCatalogError", "ToolEntry", "ToolSource", "load_tool_catalog"]
