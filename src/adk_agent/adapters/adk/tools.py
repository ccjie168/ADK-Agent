"""ADK tool types and tool sources the platform builds."""

from __future__ import annotations

from typing import Any

from google.adk.tools import BaseTool
from google.adk.tools.base_toolset import BaseToolset

__all__ = ["BaseTool", "BaseToolset", "openapi_toolset"]


def openapi_toolset(**kwargs: Any) -> Any:
    from google.adk.tools.openapi_tool import OpenAPIToolset

    return OpenAPIToolset(**kwargs)
