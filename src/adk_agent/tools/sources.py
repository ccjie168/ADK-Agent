"""External tool sources: OpenAPI documents and the tools they declare."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..adapters.adk import tools as adk_tools
from ..config import OpenApiConfig
from ..core import SecretProvider
from ..secretstore import secret_header_provider


def load_openapi_spec(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("OpenAPI spec must be a JSON object")
    return data


def openapi_toolset_from_config(cfg: OpenApiConfig, secrets: SecretProvider) -> Any:
    kwargs: dict[str, Any] = {"spec_dict": load_openapi_spec(cfg.spec_path)}
    if cfg.tool_filter:
        kwargs["tool_filter"] = cfg.tool_filter
    if cfg.tool_name_prefix:
        kwargs["tool_name_prefix"] = cfg.tool_name_prefix
    if cfg.header_secrets:
        kwargs["header_provider"] = secret_header_provider(secrets, cfg.header_secrets)
    return adk_tools.openapi_toolset(**kwargs)


def toolset_tool_ids(toolset: Any) -> set[str]:
    """Return the tool names a toolset will expose, with its prefix applied."""
    declared = getattr(toolset, "declared_tool_ids", None)
    if declared is not None:
        names = set(declared)
    else:
        tools = getattr(toolset, "_tools", None)
        if tools is not None:
            names = {tool.name for tool in tools}
        else:
            tool_filter = getattr(toolset, "tool_filter", None)
            names = (
                set(tool_filter)
                if isinstance(tool_filter, (list, tuple, set, frozenset))
                else set()
            )

    tool_filter = getattr(toolset, "tool_filter", None)
    if isinstance(tool_filter, (list, tuple, set, frozenset)):
        names &= set(tool_filter)

    prefix = getattr(toolset, "tool_name_prefix", None)
    if prefix:
        names = {f"{prefix}_{name}" for name in names}
    return names
