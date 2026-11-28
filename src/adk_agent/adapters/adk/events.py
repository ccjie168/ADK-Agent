"""ADK ``Event`` to platform ``RunEvent`` conversion (ADR-0046 decision 4)."""

from __future__ import annotations

from typing import Any

from ...core.run_event import RunEvent, RunPart

__all__ = ["to_run_event"]


def _final(event: Any) -> bool:
    is_final = getattr(event, "is_final_response", None)
    if callable(is_final):
        return bool(is_final())
    return bool(getattr(event, "final", False))


def to_run_event(event: Any) -> RunEvent:
    """Convert one ADK event, or return a platform event unchanged."""
    if isinstance(event, RunEvent):
        return event

    parts: list[RunPart] = []
    content = getattr(event, "content", None)
    for part in getattr(content, "parts", None) or ():
        if getattr(part, "thought", False):
            continue
        call = getattr(part, "function_call", None)
        if call is not None and getattr(call, "name", None):
            parts.append(RunPart(kind="tool_call", name=call.name))
        response = getattr(part, "function_response", None)
        if response is not None and getattr(response, "name", None):
            parts.append(RunPart(kind="tool_result", name=response.name))
        text = getattr(part, "text", None)
        if text:
            parts.append(RunPart(kind="text", text=text))
    return RunEvent(author=getattr(event, "author", None), final=_final(event), parts=tuple(parts))
