"""SLICE-320: OpenAPI documents become governed connectors (ADR-0047 1)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from adk_agent.core import ConnectorSpec
from adk_agent.tools import (
    ToolCatalog,
    ToolCatalogConflict,
    ToolEntry,
    build_connector_tools,
    import_openapi,
    load_tool_catalog,
    merge_tool_entries,
)
from adk_agent.tools.connectors import ConnectorDenied
from adk_agent.tools.openapi_import import OpenApiImportError

SOURCE = Path(__file__).resolve().parents[1] / "src" / "adk_agent"


def _document() -> dict:
    return {
        "openapi": "3.0.0",
        "info": {"title": "ITSM", "version": "1"},
        "servers": [{"url": "http://127.0.0.1:8055"}],
        "x-data-classes": ["internal"],
        "paths": {
            "/tickets": {
                "get": {"operationId": "list", "summary": "List tickets"},
                "post": {
                    "operationId": "create",
                    "summary": "Create ticket",
                    "x-risk-level": "L3",
                    "x-data-classes": ["confidential"],
                },
            },
            "/tickets/{id}": {
                "get": {"operationId": "get"},
                "put": {"summary": "no id here"},
            },
        },
    }


def test_import_builds_connector_and_operations():
    imported = import_openapi(_document(), "itsm", tenant="acme")

    connector = imported.connector
    assert connector.kind == "openapi"
    assert connector.tenant == "acme"
    assert connector.base_url == "http://127.0.0.1:8055"
    assert connector.methods == ["GET", "POST"]
    assert connector.path_prefixes == ["/tickets", "/tickets/"]
    assert [(op.tool_id, op.path, op.method) for op in connector.operations] == [
        ("itsm.list", "/tickets", "GET"),
        ("itsm.create", "/tickets", "POST"),
        ("itsm.get", "/tickets/{id}", "GET"),
    ]
    create = connector.operations[1]
    assert create.risk_level == "L3"
    assert create.data_classes == ["confidential"]
    assert create.write is True
    assert create.requires_approval is True

    by_id = {tool.tool_id: tool for tool in imported.tools}
    assert by_id["itsm.create"].risk_level == "L3"
    assert by_id["itsm.create"].requires_approval is True
    assert by_id["itsm.create"].data_classes == ["internal", "confidential"]
    assert by_id["itsm.list"].requires_approval is False
    assert by_id["itsm.list"].write is False
    assert by_id["itsm.create"].write is True
    assert all(tool.source == "openapi" for tool in imported.tools)


def test_import_skips_operations_without_id():
    imported = import_openapi(_document(), "itsm")

    assert imported.skipped == ["PUT /tickets/{id}"]
    assert "itsm.create" in {tool.tool_id for tool in imported.tools}


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"paths": {"/a": {"get": {"operationId": "a"}}}}, "missing_server"),
        (
            {"servers": [{"url": "/v1"}], "paths": {"/a": {"get": {"operationId": "a"}}}},
            "missing_server",
        ),
        ({"servers": [{"url": "https://x.example"}]}, "spec_invalid"),
        ("not a document", "spec_invalid"),
        (
            {
                "servers": [{"url": "https://x.example"}],
                "paths": {"/a": {"get": {"x-data-classes": ["secret"]}}},
            },
            "no_operations",
        ),
        (
            {
                "servers": [{"url": "https://x.example"}],
                "paths": {"/a": {"get": {"operationId": "a", "x-data-classes": ["secret"]}}},
            },
            "invalid_data_class",
        ),
    ],
)
def test_import_rejects_bad_document(document, code):
    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(document, "probe")

    assert exc.value.code == code


def test_import_caps_tool_count():
    paths = {f"/p{i}": {"get": {"operationId": f"op{i}"}} for i in range(201)}
    document = {"servers": [{"url": "https://x.example"}], "paths": paths}

    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(document, "probe")

    assert exc.value.code == "too_many_operations"


def _tool_for(document: dict, tool_id: str):
    imported = import_openapi(document, "itsm")
    tools = build_connector_tools([imported.connector], secrets=None)  # type: ignore[arg-type]
    return next(tool for tool in tools if tool.tool_id == tool_id)


class _RecordingAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request(self, **kwargs):
        self.calls.append(kwargs)

        class _Response:
            status = 200
            content_type = "application/json"
            headers = {"content-type": "application/json"}
            body = b'{"ok": true}'

        return _Response()


def test_operation_tool_calls_fixed_path():
    document = {
        "servers": [{"url": "https://itsm.example"}],
        "paths": {"/tickets/{id}": {"get": {"operationId": "get"}}},
    }
    tool = _tool_for(document, "itsm.get")
    adapter = _RecordingAdapter()

    async def call():
        spec = import_openapi(document, "itsm").connector
        [built] = build_connector_tools([spec], secrets=None, adapter=adapter)  # type: ignore[arg-type]
        return await built.handler(path_params={"id": "a b/c"})

    with pytest.raises(ConnectorDenied):
        asyncio.run(call())

    async def ok_call():
        spec = import_openapi(document, "itsm").connector
        [built] = build_connector_tools([spec], secrets=None, adapter=adapter)  # type: ignore[arg-type]
        return await built.handler(path_params={"id": "T-1"})

    result = asyncio.run(ok_call())
    assert result["status"] == 200
    assert adapter.calls[-1]["method"] == "GET"
    assert adapter.calls[-1]["url"] == "https://itsm.example/tickets/T-1"
    assert tool.tool_id == "itsm.get"


def test_operation_tool_rejects_traversal():
    document = {
        "servers": [{"url": "https://itsm.example"}],
        "paths": {"/tickets/{id}": {"get": {"operationId": "get"}}},
    }
    spec = import_openapi(document, "itsm").connector
    [built] = build_connector_tools([spec], secrets=None, adapter=_RecordingAdapter())  # type: ignore[arg-type]

    for value in ("../admin", "a/b", "a\\b"):
        with pytest.raises(ConnectorDenied) as exc:
            asyncio.run(built.handler(path_params={"id": value}))
        assert exc.value.error_code == "path_param_invalid"

    with pytest.raises(ConnectorDenied):
        asyncio.run(built.handler(path_params={}))


def test_catalog_merge_rejects_conflict():
    entry = ToolEntry(tool_id="itsm.list", description="List", source="openapi")
    catalog = ToolCatalog(version=1, tools=[entry])

    assert merge_tool_entries(catalog, [entry]).tools == [entry]

    changed = ToolEntry(tool_id="itsm.list", description="Different", source="openapi")
    with pytest.raises(ToolCatalogConflict):
        merge_tool_entries(catalog, [changed])


def test_cli_import_openapi_writes_connector_and_catalog(tmp_path, capsys):
    from adk_agent.cli import main

    spec_path = tmp_path / "itsm.json"
    spec_path.write_text(json.dumps(_document()), encoding="utf-8")
    connectors_dir = tmp_path / "connectors"
    catalog_path = tmp_path / "catalog.json"

    code = main(
        [
            "connectors",
            "import-openapi",
            "--spec",
            str(spec_path),
            "--connector-id",
            "itsm",
            "--tenant",
            "acme",
            "--connectors-dir",
            str(connectors_dir),
            "--tool-catalog",
            str(catalog_path),
        ]
    )
    assert code in (0, None)
    payload = json.loads(capsys.readouterr().out)
    assert payload["connector"]["connector_id"] == "itsm"
    assert len(payload["tools"]) == 3
    assert payload["skipped"] == ["PUT /tickets/{id}"]

    catalog = load_tool_catalog(catalog_path)
    assert {tool.tool_id for tool in catalog.tools} == {"itsm.list", "itsm.create", "itsm.get"}

    import adk_agent.registry.connectors as connectors_module

    store = connectors_module.FileConnectorStore(str(connectors_dir))
    stored = asyncio.run(store.get("itsm"))
    assert isinstance(stored, ConnectorSpec)
    assert stored.kind == "openapi"


def test_source_has_no_helpers_outside_the_tools_package():
    # Keep the import path free of ADK and of console code: it is a CLI-only feature.
    text = (SOURCE / "tools" / "openapi_import.py").read_text(encoding="utf-8")
    assert "google.adk" not in text


def test_gateway_tool_carries_operation_governance():
    imported = import_openapi(_document(), "itsm")
    tools = build_connector_tools([imported.connector], secrets=None)  # type: ignore[arg-type]
    by_id = {tool.tool_id: tool for tool in tools}

    create = by_id["itsm.create"]
    assert create.risk_level == "L3"
    assert create.requires_approval is True
    assert create.needs_approval is True
    assert create.requires_idempotency is True
    assert create.data_classes == ("internal", "confidential")
    assert create.write is True

    listing = by_id["itsm.list"]
    assert listing.risk_level == "L2"
    assert listing.needs_approval is False
    assert listing.requires_idempotency is False


def test_import_rejects_duplicate_operation_ids():
    document = {
        "servers": [{"url": "https://x.example"}],
        "paths": {
            "/a": {"get": {"operationId": "dup"}},
            "/b": {"post": {"operationId": "dup"}},
        },
    }

    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(document, "probe")

    assert exc.value.code == "duplicate_operation_id"


def test_connector_tool_entries_mirror_operations():
    from adk_agent.tools import connector_tool_entries

    imported = import_openapi(_document(), "itsm")
    entries = connector_tool_entries([imported.connector])

    assert {entry.tool_id for entry in entries} == {"itsm.list", "itsm.create", "itsm.get"}
    assert "itsm" not in {entry.tool_id for entry in entries}


def test_prefix_stops_before_the_first_placeholder():
    document = {
        "servers": [{"url": "https://x.example"}],
        "paths": {"/tickets{id}/history": {"get": {"operationId": "history"}}},
    }
    imported = import_openapi(document, "probe")

    assert imported.connector.path_prefixes == ["/tickets"]


def test_operation_tool_encodes_path_params():
    document = {
        "servers": [{"url": "https://itsm.example"}],
        "paths": {"/tickets/{id}": {"get": {"operationId": "get"}}},
    }
    adapter = _RecordingAdapter()
    spec = import_openapi(document, "itsm").connector
    [built] = build_connector_tools([spec], secrets=None, adapter=adapter)  # type: ignore[arg-type]

    asyncio.run(built.handler(path_params={"id": "T 1"}))

    assert adapter.calls[-1]["url"] == "https://itsm.example/tickets/T%201"


def test_import_rejects_bad_risk_level_and_host():
    bad_risk = {
        "servers": [{"url": "https://x.example"}],
        "paths": {"/a": {"get": {"operationId": "a", "x-risk-level": "L9"}}},
    }
    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(bad_risk, "probe")
    assert exc.value.code == "invalid_risk_level"

    bad_host = {
        "servers": [{"url": "http://api.example"}],
        "paths": {"/a": {"get": {"operationId": "a"}}},
    }
    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(bad_host, "probe")
    assert exc.value.code == "spec_invalid"


def test_connector_risk_floor_raises_operation_tools():
    spec = ConnectorSpec(
        connector_id="pay",
        kind="openapi",
        base_url="https://pay.example",
        methods=["POST"],
        risk_level="L4",
        data_classes=["restricted"],
        operations=[{"tool_id": "pay.refund", "path": "/r", "method": "POST"}],
    )

    [tool] = build_connector_tools([spec], secrets=None)  # type: ignore[arg-type]
    assert tool.risk_level == "L4"
    assert tool.needs_approval is True
    assert tool.requires_idempotency is True
    assert tool.data_classes == ("internal", "restricted")


def test_model_rejects_duplicate_operation_tool_ids():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConnectorSpec(
            connector_id="pay",
            kind="openapi",
            base_url="https://pay.example",
            methods=["POST"],
            operations=[
                {"tool_id": "pay.refund", "path": "/r", "method": "POST"},
                {"tool_id": "pay.refund", "path": "/s", "method": "POST"},
            ],
        )


def test_path_item_risk_level_is_honoured():
    document = {
        "servers": [{"url": "https://x.example"}],
        "x-risk-level": "L3",
        "paths": {"/refund": {"x-risk-level": "L3", "post": {"operationId": "refund"}}},
    }
    imported = import_openapi(document, "pay")

    tool = imported.tools[0]
    assert tool.tool_id == "pay.refund"
    assert tool.risk_level == "L3"
    assert tool.requires_approval is True


def test_cli_reports_catalog_unreadable_and_catalog_conflict(tmp_path, capsys):
    from adk_agent.cli import main

    spec_path = tmp_path / "itsm.json"
    spec_path.write_text(json.dumps(_document()), encoding="utf-8")
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("{not json", encoding="utf-8")
    connectors_dir = tmp_path / "connectors"

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "connectors",
                "import-openapi",
                "--spec",
                str(spec_path),
                "--connector-id",
                "itsm",
                "--connectors-dir",
                str(connectors_dir),
                "--tool-catalog",
                str(catalog_path),
            ]
        )
    assert exc.value.code == 1
    assert "catalog_unreadable" in capsys.readouterr().err
    assert not (connectors_dir / "itsm.json").exists()

    catalog_path.write_text(
        json.dumps(
            {
                "version": 1,
                "tools": [
                    {
                        "tool_id": "itsm.list",
                        "description": "different",
                        "source": "openapi",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "connectors",
                "import-openapi",
                "--spec",
                str(spec_path),
                "--connector-id",
                "itsm",
                "--connectors-dir",
                str(connectors_dir),
                "--tool-catalog",
                str(catalog_path),
            ]
        )
    assert exc.value.code == 1
    assert "catalog_conflict" in capsys.readouterr().err
    assert not (connectors_dir / "itsm.json").exists()


def test_cli_rejects_a_tool_id_owned_by_another_connector(tmp_path, capsys):
    from adk_agent.cli import main

    connectors_dir = tmp_path / "connectors"
    first = tmp_path / "first.json"
    first.write_text(
        json.dumps(
            {
                "servers": [{"url": "https://a.example"}],
                "paths": {"/b": {"get": {"operationId": "b"}}},
            }
        ),
        encoding="utf-8",
    )
    assert main(
        [
            "connectors",
            "import-openapi",
            "--spec",
            str(first),
            "--connector-id",
            "a",
            "--connectors-dir",
            str(connectors_dir),
        ]
    ) in (0, None)
    capsys.readouterr()

    # A connector literally named "a.b" would collide with the tool "a.b".
    second = tmp_path / "second.json"
    second.write_text(
        json.dumps(
            {
                "servers": [{"url": "https://c.example"}],
                "paths": {"/x": {"get": {"operationId": "x"}}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "connectors",
                "import-openapi",
                "--spec",
                str(second),
                "--connector-id",
                "a.b",
                "--connectors-dir",
                str(connectors_dir),
            ]
        )
    assert exc.value.code == 1
    assert "tool_id_conflict" in capsys.readouterr().err
    assert not (connectors_dir / "a.b.json").exists()


def test_operation_annotation_null_falls_back_to_path_item():
    document = {
        "servers": [{"url": "https://x.example"}],
        "paths": {
            "/refund": {
                "x-risk-level": "L3",
                "x-data-classes": ["restricted"],
                "post": {"operationId": "refund", "x-risk-level": None, "x-data-classes": None},
            }
        },
    }
    imported = import_openapi(document, "pay")

    tool = imported.tools[0]
    assert tool.risk_level == "L3"
    assert "restricted" in tool.data_classes
    tool_specs = build_connector_tools([imported.connector], secrets=None)  # type: ignore[arg-type]
    assert tool_specs[0].needs_approval is True


def test_import_catalog_matches_the_gateway(tmp_path):
    imported = import_openapi(_document(), "itsm")
    catalog = {entry.tool_id: entry for entry in imported.tools}
    gateway = {
        tool.tool_id: tool
        for tool in build_connector_tools([imported.connector], secrets=None)  # type: ignore[arg-type]
    }

    assert set(catalog) == set(gateway)
    for tool_id, entry in catalog.items():
        assert entry.risk_level == gateway[tool_id].risk_level
        assert entry.requires_approval == gateway[tool_id].needs_approval
        assert tuple(entry.data_classes) == gateway[tool_id].data_classes


def test_bad_extension_types_get_fixed_codes():
    bad_classes = {
        "servers": [{"url": "https://x.example"}],
        "paths": {"/a": {"get": {"operationId": "a", "x-data-classes": [{"a": 1}]}}},
    }
    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(bad_classes, "probe")
    assert exc.value.code == "invalid_data_class"

    bad_risk = {
        "servers": [{"url": "https://x.example"}],
        "paths": {"/a": {"get": {"operationId": "a", "x-risk-level": ["L3"]}}},
    }
    with pytest.raises(OpenApiImportError) as exc:
        import_openapi(bad_risk, "probe")
    assert exc.value.code == "invalid_risk_level"


def test_store_rejects_cross_connector_tool_id(tmp_path):
    from adk_agent.core import ConnectorToolIdConflict
    from adk_agent.registry.connectors import FileConnectorStore

    store = FileConnectorStore(str(tmp_path))
    imported = import_openapi(_document(), "itsm")
    asyncio.run(store.add(imported.connector))

    clash = ConnectorSpec(
        connector_id="itsm.list",
        kind="http",
        base_url="https://other.example",
        methods=["GET"],
    )
    with pytest.raises(ConnectorToolIdConflict) as exc:
        asyncio.run(store.add(clash))
    assert exc.value.tool_id == "itsm.list"

    # The reverse order is rejected too: a connector whose operation equals an
    # existing connector id.
    other = ConnectorSpec(
        connector_id="pay",
        kind="openapi",
        base_url="https://pay.example",
        methods=["GET"],
        operations=[{"tool_id": "pay.itsm", "path": "/x", "method": "GET"}],
    )
    asyncio.run(store.add(other))
    with pytest.raises(ConnectorToolIdConflict):
        asyncio.run(
            store.add(
                ConnectorSpec(
                    connector_id="pay.itsm",
                    kind="http",
                    base_url="https://other.example",
                    methods=["GET"],
                )
            )
        )


def test_registry_maps_tool_id_conflict_to_409():
    from adk_agent.core import ConnectorToolIdConflict
    from adk_agent.registry.service import _connector_spec_error

    response = _connector_spec_error(ConnectorToolIdConflict("a.b", "a"))

    assert response.status_code == 409
    assert b"tool_id_conflict" in response.body


def test_console_register_reports_tool_id_conflict(tmp_path):
    from fastapi.testclient import TestClient
    from google.adk.agents import LlmAgent

    from adk_agent.console import build_console_app
    from adk_agent.registry import FileConnectorStore

    store = FileConnectorStore(str(tmp_path / "connectors"))
    asyncio.run(store.add(import_openapi(_document(), "itsm").connector))
    app = build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=("admin",),
        connectors=store,
    )
    auth = {"Authorization": "Bearer secret"}
    body = {
        "connector_id": "itsm.list",
        "tenant": "local",
        "kind": "http",
        "base_url": "https://other.example",
        "methods": ["GET"],
        "path_prefixes": ["/"],
    }

    with TestClient(app) as client:
        response = client.post("/api/connectors", json=body, headers=auth)

    assert response.status_code == 409
    assert response.json()["error"] == "tool_id_conflict"
    assert not (tmp_path / "connectors" / "itsm.list.json").exists()
