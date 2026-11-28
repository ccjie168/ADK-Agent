"""ADK tool sources the platform builds from configuration."""

from __future__ import annotations

from typing import Any

__all__ = ["openapi_toolset"]


def openapi_toolset(**kwargs: Any) -> Any:
    from google.adk.tools.openapi_tool import OpenAPIToolset

    return OpenAPIToolset(**kwargs)
