"""Read-only tool catalog for the console (UI-4)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core import ConnectorSpec, DelegationMode, RiskLevel

_SAFE_NAME = r"^[A-Za-z0-9][A-Za-z0-9._+-]*$"

ToolSource = Literal["function", "openapi", "mcp", "connector"]


class ToolCatalogError(Exception):
    """The tool catalog file is missing, malformed, or has duplicate ids."""


class ToolCatalogConflict(ToolCatalogError):
    """An existing tool id would be replaced with a different definition."""

    def __init__(self, tool_id: str) -> None:
        super().__init__(f"tool id {tool_id!r} already exists with a different definition")
        self.tool_id = tool_id


class ToolEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1, pattern=_SAFE_NAME)
    description: str = ""
    source: ToolSource
    data_classes: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    risk_level: RiskLevel | None = None
    tenant: str | None = Field(default=None, pattern=_SAFE_NAME)
    write: bool = False
    idempotency_required: bool | None = None
    delegation: DelegationMode = "service"

    @property
    def requires_idempotency(self) -> bool:
        """L3/L4 force idempotency, otherwise default to write (ADR-0034)."""
        if self.risk_level in ("L3", "L4"):
            return True
        if self.idempotency_required is not None:
            return self.idempotency_required
        return self.write

    @property
    def needs_approval(self) -> bool:
        """True when the tool requires HITL, from the flag or L3/L4 risk (ADR-0031)."""
        return self.requires_approval or self.risk_level in ("L3", "L4")


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


def connector_tool_entries(specs: Iterable[ConnectorSpec]) -> list[ToolEntry]:
    return [
        ToolEntry(
            tool_id=spec.connector_id,
            description=f"{spec.kind} connector to {spec.base_url}",
            source="connector",
            data_classes=list(spec.data_classes),
            requires_approval=False,
            tenant=spec.tenant,
            risk_level=spec.risk_level,
            delegation=spec.delegation,
        )
        for spec in specs
        if spec.enabled
    ]


__all__ = [
    "ToolCatalog",
    "ToolCatalogError",
    "ToolEntry",
    "ToolSource",
    "connector_tool_entries",
    "load_tool_catalog",
]


def merge_tool_entries(catalog: ToolCatalog, entries: list[ToolEntry]) -> ToolCatalog:
    """Merge imported tools; identical duplicates are idempotent, others conflict."""
    by_id = {tool.tool_id: tool for tool in catalog.tools}
    for entry in entries:
        existing = by_id.get(entry.tool_id)
        if existing is None:
            by_id[entry.tool_id] = entry
        elif existing != entry:
            raise ToolCatalogConflict(entry.tool_id)
    return ToolCatalog(version=1, tools=sorted(by_id.values(), key=lambda tool: tool.tool_id))


def write_tool_catalog(path: str | Path, catalog: ToolCatalog) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    payload = json.dumps(catalog.model_dump(mode="json"), indent=2, ensure_ascii=False)
    tmp.write_text(payload + "\n", encoding="utf-8")
    tmp.replace(target)
