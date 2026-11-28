"""Platform run events, the boundary type the agent runtime consumes (ADR-0046).

ADK's ``Event`` is converted once in ``adk_agent.adapters.adk.events``; nothing
above the adapter reads ADK event fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

RunPartKind = Literal["text", "tool_call", "tool_result"]


class RunPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: RunPartKind
    text: str | None = None
    name: str | None = None


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    author: str | None = None
    final: bool = False
    parts: tuple[RunPart, ...] = ()

    @property
    def text(self) -> str:
        """The concatenated text parts, in stream order."""
        return "".join(part.text or "" for part in self.parts if part.kind == "text")
