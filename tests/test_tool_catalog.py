"""SLICE-075: the tool catalog file is validated before the console uses it."""

from __future__ import annotations

import json

import pytest

from adk_agent.tools import ToolCatalog, ToolCatalogError, load_tool_catalog


def _write(tmp_path, payload):
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _entry(**overrides):
    entry = {
        "tool_id": "crm.read",
        "description": "read a CRM record",
        "source": "function",
        "data_classes": ["internal"],
        "requires_approval": False,
        "tenant": None,
    }
    entry.update(overrides)
    return entry


def test_load_catalog(tmp_path):
    path = _write(
        tmp_path,
        {"version": 1, "tools": [_entry(), _entry(tool_id="crm.write", source="mcp")]},
    )

    catalog = load_tool_catalog(path)

    assert isinstance(catalog, ToolCatalog)
    assert [tool.tool_id for tool in catalog.tools] == ["crm.read", "crm.write"]
    assert catalog.tools[1].source == "mcp"


def test_duplicate_tool_id(tmp_path):
    path = _write(tmp_path, {"version": 1, "tools": [_entry(), _entry()]})

    with pytest.raises(ToolCatalogError, match="duplicate"):
        load_tool_catalog(path)


def test_bad_source(tmp_path):
    path = _write(tmp_path, {"version": 1, "tools": [_entry(source="shell")]})

    with pytest.raises(ToolCatalogError):
        load_tool_catalog(path)


def test_bad_version(tmp_path):
    path = _write(tmp_path, {"version": 2, "tools": [_entry()]})

    with pytest.raises(ToolCatalogError):
        load_tool_catalog(path)


def test_unsafe_tool_id(tmp_path):
    path = _write(tmp_path, {"version": 1, "tools": [_entry(tool_id="../escape")]})

    with pytest.raises(ToolCatalogError):
        load_tool_catalog(path)
