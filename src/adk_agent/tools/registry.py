"""Function tool registration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core import DataClass


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    handler: Callable[..., Any]
    data_classes: tuple[DataClass, ...] = ()
    requires_approval: bool = False


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
