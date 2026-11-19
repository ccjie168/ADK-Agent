"""Function tool registration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..core import DataClass, RiskLevel


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    handler: Callable[..., Any]
    data_classes: tuple[DataClass, ...] = ()
    requires_approval: bool = False
    egress: Literal["none", "third_party"] = "none"
    write: bool = False
    idempotency_required: bool | None = None
    risk_level: RiskLevel | None = None

    @property
    def requires_idempotency(self) -> bool:
        """L3/L4 force idempotency, otherwise default to write (ADR-0034)."""
        if self.risk_level in ("L3", "L4"):
            return True
        if self.idempotency_required is not None:
            return self.idempotency_required
        return self.write


class FunctionRegistry:
    def __init__(self, tools: list[ToolSpec]) -> None:
        if any(not tool.tool_id for tool in tools):
            raise ValueError("tool_id must be non-empty")
        self._tools = {tool.tool_id: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("duplicate tool_id")

    def get(self, tool_id: str) -> ToolSpec | None:
        return self._tools.get(tool_id)

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())
