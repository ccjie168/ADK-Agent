"""SLICE-075: the console lists the tool catalog with registry grants."""

from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.console import build_console_app
from adk_agent.core import AgentManifest, ConnectorSpec, ConnectorStoreError
from adk_agent.registry import FileAgentRegistry, FileConnectorStore, published_from
from adk_agent.tools import ToolCatalog, ToolEntry, load_tool_catalog

AUTH = {"Authorization": "Bearer secret"}


def _entry(tool_id: str, *, tenant=None, source="function") -> ToolEntry:
    return ToolEntry(
        tool_id=tool_id,
        description=f"{tool_id} description",
        source=source,
        data_classes=["internal"],
        requires_approval=False,
        tenant=tenant,
    )


def _catalog() -> ToolCatalog:
    return ToolCatalog(
        version=1,
        tools=[
            _entry("crm.read"),
            _entry("crm.export", tenant="acme"),
            _entry("billing.read", tenant="other"),
        ],
    )


def _manifest(tenant: str = "acme", tool_ids=("crm.read",)) -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant=tenant,
        owner=tenant,
        description="bot",
        model_policy={"provider_allowlist": ["litellm"]},
        tool_grants=[{"tool_id": tool_id, "data_classes": ["internal"]} for tool_id in tool_ids],
    )


def _app(tmp_path, *, catalog=True, registry=None, roles=None, connectors=None):
    probe = LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")
    return build_console_app(
        {"probe": probe},
        auth_token="secret",
        roles=roles,
        registry=registry if registry is not None else FileAgentRegistry(tmp_path / "registry"),
        tool_catalog=_catalog() if catalog is True else catalog,
        connectors=connectors,
    )


def _tools(client, tenant="acme"):
    return client.get(f"/api/tools?tenant={tenant}", headers=AUTH)


def test_lists_global_and_tenant_tools(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = _tools(client)

    assert response.status_code == 200
    assert [entry["tool_id"] for entry in response.json()] == ["crm.export", "crm.read"]


def test_grants_from_registry(tmp_path):
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published_from(_manifest(tool_ids=("crm.read", "crm.write")))))
    with TestClient(_app(tmp_path, registry=registry)) as client:
        [entry] = [item for item in _tools(client).json() if item["tool_id"] == "crm.read"]

    assert entry["granted_agents"] == [{"id": "bot", "version": "1.0.0"}]


def test_cross_tenant_forbidden(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = _tools(client, tenant="acme")

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


def test_no_catalog(tmp_path):
    with TestClient(_app(tmp_path, catalog=None)) as client:
        response = _tools(client)

    assert response.status_code == 404
    assert response.json() == {"error": "tool_catalog_not_configured"}


def test_grants_empty_without_registry(tmp_path):
    probe = LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")
    app = build_console_app(
        {"probe": probe}, auth_token="secret", registry=None, tool_catalog=_catalog()
    )
    with TestClient(app) as client:
        response = _tools(client)

    assert response.status_code == 200
    assert all(entry["granted_agents"] == [] for entry in response.json())


def _connector(connector_id: str, *, tenant=None, enabled=True) -> ConnectorSpec:
    return ConnectorSpec(
        connector_id=connector_id,
        tenant=tenant,
        kind="http",
        base_url="https://example.com",
        methods=["GET"],
        data_classes=["internal"],
        enabled=enabled,
    )


def _connector_store(tmp_path, *specs) -> FileConnectorStore:
    store = FileConnectorStore(tmp_path / "connectors")
    for spec in specs:
        asyncio.run(store.add(spec))
    return store


class _BrokenConnectorStore:
    async def list(self, tenant: str):
        raise ConnectorStoreError("down")


def test_connector_tools_merged(tmp_path):
    store = _connector_store(
        tmp_path,
        _connector("crm.http"),
        _connector("acme.erp", tenant="acme"),
        _connector("other.feed", tenant="other"),
    )
    with TestClient(_app(tmp_path, catalog=None, connectors=store)) as client:
        response = _tools(client)

    assert response.status_code == 200
    assert [(entry["tool_id"], entry["tenant"], entry["source"]) for entry in response.json()] == [
        ("acme.erp", "acme", "connector"),
        ("crm.http", None, "connector"),
    ]


def test_static_entry_wins_over_connector(tmp_path):
    store = _connector_store(tmp_path, _connector("crm.read"), _connector("crm.other"))
    with TestClient(_app(tmp_path, connectors=store)) as client:
        entries = _tools(client).json()

    assert [entry["tool_id"] for entry in entries] == ["crm.export", "crm.other", "crm.read"]
    [entry] = [item for item in entries if item["tool_id"] == "crm.read"]
    assert entry["source"] == "function"
    assert entry["description"] == "crm.read description"


def test_connectors_without_catalog(tmp_path):
    store = _connector_store(tmp_path, _connector("crm.http"))
    with TestClient(_app(tmp_path, catalog=None, connectors=store)) as client:
        response = _tools(client)

    assert response.status_code == 200
    assert [entry["tool_id"] for entry in response.json()] == ["crm.http"]
    assert response.json()[0]["description"] == "http connector to https://example.com"


def test_connector_store_unavailable(tmp_path):
    with TestClient(_app(tmp_path, catalog=None, connectors=_BrokenConnectorStore())) as client:
        response = _tools(client)

    assert response.status_code == 503
    assert response.json() == {"error": "connector_store_unavailable"}


def test_connector_grants_from_registry(tmp_path):
    store = _connector_store(tmp_path, _connector("crm.http"))
    registry = FileAgentRegistry(tmp_path / "registry")
    asyncio.run(registry.publish(published_from(_manifest(tool_ids=("crm.http",)))))
    with TestClient(_app(tmp_path, catalog=None, registry=registry, connectors=store)) as client:
        [entry] = _tools(client).json()

    assert entry["tool_id"] == "crm.http"
    assert entry["granted_agents"] == [{"id": "bot", "version": "1.0.0"}]


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def _catalog_file(tmp_path) -> str:
    path = tmp_path / "tools.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "tools": [
                    {
                        "tool_id": "crm.read",
                        "description": "read",
                        "source": "function",
                        "data_classes": ["internal"],
                        "requires_approval": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_cli_loads_catalog(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))

    cli.main(
        ["console", "--agents", _agents_file(tmp_path), "--tool-catalog", _catalog_file(tmp_path)]
    )

    assert isinstance(captured["tool_catalog"], ToolCatalog)


def test_cli_rejects_bad_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: None)
    bad = tmp_path / "tools.json"
    bad.write_text("{", encoding="utf-8")

    try:
        cli.main(["console", "--agents", _agents_file(tmp_path), "--tool-catalog", str(bad)])
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("bad catalog did not exit")
    assert "tool catalog" in capsys.readouterr().err.lower()


def test_catalog_file_roundtrip(tmp_path):
    catalog = load_tool_catalog(_catalog_file(tmp_path))

    assert catalog.tools[0].tool_id == "crm.read"


def test_read_requires_capability(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = _tools(client, tenant="local")

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_publisher_can_read_tools(tmp_path):
    with TestClient(_app(tmp_path, roles=["publisher"])) as client:
        response = _tools(client, tenant="local")

    assert response.status_code == 200


def test_operator_lacks_tools_capability(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        response = _tools(client, tenant="local")

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
