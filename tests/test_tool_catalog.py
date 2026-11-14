"""SLICE-075: the tool catalog file is validated before the console uses it."""

from __future__ import annotations

import json

import pytest

from adk_agent.core import ConnectorSpec
from adk_agent.tools import (
    ToolCatalog,
    ToolCatalogError,
    connector_tool_entries,
    load_tool_catalog,
)


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


def _connector(**overrides):
    spec = {
        "connector_id": "crm.http",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "methods": ["GET"],
        "data_classes": ["internal"],
    }
    spec.update(overrides)
    return ConnectorSpec.model_validate(spec)


def test_connector_entry():
    [entry] = connector_tool_entries([_connector()])

    assert entry.tool_id == "crm.http"
    assert entry.description == "http connector to https://crm.example.com"
    assert entry.source == "connector"
    assert entry.data_classes == ["internal"]
    assert entry.requires_approval is False
    assert entry.tenant is None


def test_connector_entry_skips_disabled():
    specs = [
        _connector(connector_id="crm.on"),
        _connector(connector_id="crm.off", enabled=False),
    ]

    assert [entry.tool_id for entry in connector_tool_entries(specs)] == ["crm.on"]
