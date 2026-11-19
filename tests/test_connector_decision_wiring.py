"""SLICE-179: connectors propagate risk_level/delegation to the tool surface."""

from __future__ import annotations

from adk_agent.core import ConnectorSpec
from adk_agent.secretstore import MappingSecretProvider
from adk_agent.tools import ToolSpec
from adk_agent.tools.catalog import ToolEntry, connector_tool_entries
from adk_agent.tools.connectors import build_connector_tools


def _connector(**overrides) -> ConnectorSpec:
    data = {
        "connector_id": "sap",
        "kind": "http",
        "base_url": "https://sap.example.com",
        "methods": ["POST"],
        "path_prefixes": ["/write/"],
        "risk_level": "L4",
        "delegation": "controlled-service",
    }
    data.update(overrides)
    return ConnectorSpec(**data)


def test_build_connector_tools_propagates_risk_and_delegation():
    tools = build_connector_tools([_connector()], secrets=MappingSecretProvider({}))
    spec = tools[0]
    assert spec.risk_level == "L4"
    assert spec.delegation == "controlled-service"


def test_connector_tool_entries_propagates_risk_and_delegation():
    entries = connector_tool_entries([_connector()])
    entry = entries[0]
    assert entry.risk_level == "L4"
    assert entry.delegation == "controlled-service"


def test_tool_spec_delegation_defaults_service():
    spec = ToolSpec(tool_id="x", handler=lambda: None)
    assert spec.delegation == "service"


def test_tool_entry_delegation_defaults_service():
    entry = ToolEntry(tool_id="x", source="function")
    assert entry.delegation == "service"
