"""SLICE-004: private web console (auth + agent list)."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.registry import FileAgentRegistry
from adk_agent.registry.model_config import FileModelConfigStore
from adk_agent.registry.terminology import FileConceptSchemeStore
from adk_agent.semantics import Concept, ConceptScheme, Term
from adk_agent.tools import ToolCatalog, ToolEntry


def _agents() -> dict[str, LlmAgent]:
    return {
        "probe": LlmAgent(
            name="probe",
            model="gemini-2.5-pro",
            description="probe agent",
            instruction="x",
        )
    }


def _client(token: str = "secret") -> TestClient:
    app = build_console_app(_agents(), auth_token=token)
    return TestClient(app)


def test_healthz_and_index_open():
    with _client() as client:
        assert client.get("/healthz").status_code == 200
        page = client.get("/")
        assert page.status_code == 200
        assert "ADK Console" in page.text


def test_api_requires_token():
    with _client() as client:
        assert client.get("/api/agents").status_code == 401
        assert client.post("/api/chat", json={}).status_code == 401


def test_agents_with_token():
    with _client() as client:
        response = client.get("/api/agents", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    assert response.json() == [{"name": "probe", "description": "probe agent"}]


def test_chat_validates_input():
    headers = {"Authorization": "Bearer secret"}
    with _client() as client:
        assert client.post("/api/chat", json={}, headers=headers).status_code == 400
        unknown = client.post("/api/chat", json={"agent": "nope", "message": "hi"}, headers=headers)
        assert unknown.status_code == 400
        empty = client.post("/api/chat", json={"agent": "probe", "message": " "}, headers=headers)
        assert empty.status_code == 400


def test_index_has_management_panels():
    with _client() as client:
        page = client.get("/")

    for element in (
        "tabs",
        "tab-chat",
        "tab-registry",
        "tab-runs",
        "tab-sessions",
        "tab-policy",
        "tab-approvals",
        "tab-plans",
        "registry",
        "runs",
        "sessions",
        "approvals-body",
        "plans-body",
    ):
        assert f'id="{element}"' in page.text
    assert "Registry" in page.text
    assert "Runs" in page.text
    assert "Approvals" in page.text
    assert "Plans" in page.text


def test_audit_block_is_capability_gated():
    with _client() as client:
        page = client.get("/")

    assert 'data-capability="audit.read"' in page.text


def test_index_has_design_tokens():
    with _client() as client:
        page = client.get("/")

    for token in ("--radius-lg:", "--shadow-card:", "--space-1:"):
        assert token in page.text


def test_index_has_metric_card_system():
    with _client() as client:
        page = client.get("/")

    for cls in (".metric-grid", ".stat-card", ".stat-label", ".stat-value", ".stat-delta"):
        assert cls in page.text


def test_index_has_overview_panel():
    with _client() as client:
        page = client.get("/")

    assert 'id="overview"' in page.text
    assert "metric-grid" in page.text


def test_overview_endpoint_returns_cards():
    app = build_console_app(_agents(), auth_token="secret", roles=["admin"])
    with TestClient(app) as client:
        response = client.get("/api/overview", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert [card["key"] for card in cards] == ["approvals", "agents", "tools", "grants"]
    for card in cards:
        assert card["label"]
        assert card["panel"]
        assert card["value"] is None


def test_overview_null_for_forbidden_card():
    catalog = ToolCatalog(
        version=1,
        tools=[
            ToolEntry(
                tool_id="crm.read",
                description="crm read",
                source="function",
                data_classes=["internal"],
                requires_approval=False,
            )
        ],
    )
    app = build_console_app(
        _agents(), auth_token="secret", roles=["operator"], tool_catalog=catalog
    )
    with TestClient(app) as client:
        response = client.get("/api/overview", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    cards = {card["key"]: card for card in response.json()["cards"]}
    assert cards["tools"]["value"] is None


def test_index_has_audit_and_quota_panels():
    with _client() as client:
        page = client.get("/")

    assert 'id="audit-panel"' in page.text
    assert 'id="quota"' in page.text
    assert "tab-audit" in page.text
    assert "tab-quota" in page.text


def test_index_has_rag_and_model_panels():
    with _client() as client:
        page = client.get("/")

    assert 'id="rag"' in page.text
    assert 'id="model"' in page.text
    assert "tab-rag" in page.text
    assert "tab-model" in page.text


def test_rag_endpoint_returns_stats():
    app = build_console_app(_agents(), auth_token="secret", roles=["operator"])
    with TestClient(app) as client:
        response = client.get("/api/rag", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    data = response.json()
    assert data["recent_retrievals"] == 0
    assert "last_top_k" in data
    assert "last_returned" in data


def test_model_endpoint_returns_stats():
    app = build_console_app(_agents(), auth_token="secret", roles=["operator"])
    with TestClient(app) as client:
        response = client.get("/api/model", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    data = response.json()
    assert data["recent_calls"] == 0
    assert data["aliases"] == []
    assert data["fallbacks"] == 0


def _semantics_app(tmp_path):
    store = FileConceptSchemeStore(tmp_path / "terminology")
    scheme = ConceptScheme(
        scheme_id="products",
        concepts=[
            Concept(
                concept_id="order",
                pref_labels=[Term(value="Order", language="en")],
                alt_labels=[Term(value="Purchase", language="en")],
            ),
        ],
    )
    asyncio.run(store.put("local", scheme))
    return build_console_app(_agents(), auth_token="secret", roles=["admin"], terminology=store)


def test_index_has_semantics_panel():
    with _client() as client:
        page = client.get("/")

    assert 'id="semantics"' in page.text
    assert "tab-semantics" in page.text


def test_semantics_endpoint_lists_schemes(tmp_path):
    app = _semantics_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/semantics", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    schemes = response.json()
    assert len(schemes) == 1
    assert schemes[0]["scheme_id"] == "products"


def test_semantics_route_endpoint_replays(tmp_path):
    app = _semantics_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/semantics/route",
            json={
                "scheme_id": "products",
                "text": "show me the Order",
                "bindings": [
                    {
                        "capability_id": "order.lookup",
                        "concept_id": "order",
                        "tool_id": "lookup_order",
                    }
                ],
            },
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    routed = response.json()
    assert len(routed) == 1
    assert routed[0]["capability_id"] == "order.lookup"
    assert routed[0]["tool_id"] == "lookup_order"


def test_index_has_import_panel():
    with _client() as client:
        page = client.get("/")

    assert 'id="import"' in page.text
    assert "tab-import" in page.text


def test_import_terminology_endpoint(tmp_path):
    store = FileConceptSchemeStore(tmp_path / "terminology")
    app = build_console_app(_agents(), auth_token="secret", roles=["admin"], terminology=store)
    scheme = {
        "scheme_id": "products",
        "concepts": [
            {
                "concept_id": "order",
                "pref_labels": [{"value": "Order", "language": "en"}],
            }
        ],
    }
    with TestClient(app) as client:
        imported = client.post(
            "/api/import/terminology",
            json=scheme,
            headers={"Authorization": "Bearer secret"},
        )
        assert imported.status_code == 200
        listed = client.get("/api/semantics", headers={"Authorization": "Bearer secret"})

    assert len(listed.json()) == 1
    assert listed.json()[0]["scheme_id"] == "products"


def test_import_agent_endpoint(tmp_path):
    registry = FileAgentRegistry(tmp_path / "registry")
    app = build_console_app(_agents(), auth_token="secret", roles=["admin"], registry=registry)
    manifest = {
        "id": "bot",
        "version": "1.0.0",
        "tenant": "local",
        "owner": "local",
        "description": "bot",
        "model_policy": {"provider_allowlist": ["litellm"]},
    }
    with TestClient(app) as client:
        imported = client.post(
            "/api/import/agent",
            json=manifest,
            headers={"Authorization": "Bearer secret"},
        )
        assert imported.status_code == 200
        listed = client.get("/api/registry", headers={"Authorization": "Bearer secret"})

    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == "bot"


def test_index_has_ask_ai_panel():
    with _client() as client:
        page = client.get("/")

    assert 'id="ask-ai"' in page.text
    assert "tab-ask-ai" in page.text


def test_ask_ai_endpoint_returns_hits(tmp_path):
    app = _semantics_app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/ask-ai",
            json={
                "text": "show me the Order",
                "bindings": [
                    {
                        "capability_id": "order.lookup",
                        "concept_id": "order",
                        "tool_id": "lookup_order",
                    }
                ],
            },
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["hits"]) == 1
    assert data["hits"][0]["tool_id"] == "lookup_order"


def test_index_has_live_refresh():
    with _client() as client:
        page = client.get("/")

    assert 'fetch("/api/live"' in page.text
    assert "startLive" in page.text


def test_live_endpoint_streams_tick():
    with (
        _client() as client,
        client.stream("GET", "/api/live", headers={"Authorization": "Bearer secret"}) as response,
    ):
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        first = next(response.iter_text())
        assert "event: tick" in first


def _model_config_app(tmp_path, roles=None, audit_sink=None):
    store = FileModelConfigStore(tmp_path / "model")
    return build_console_app(
        _agents(),
        auth_token="secret",
        roles=roles or ["admin"],
        model_config_store=store,
        audit_sink=audit_sink,
    )


def test_index_has_model_config_controls():
    with _client() as client:
        page = client.get("/")

    assert "设置默认模型" in page.text
    assert 'id="model-config"' in page.text
    assert 'id="model-config-save"' in page.text


def test_model_config_get_requires_model_read():
    app = build_console_app(_agents(), auth_token="secret", roles=["requester"])
    with TestClient(app) as client:
        response = client.get("/api/model-config", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 403


def test_model_config_get_returns_stored(tmp_path):
    store = FileModelConfigStore(tmp_path / "model")
    asyncio.run(store.put("claude:claude-sonnet-5-5"))
    app = build_console_app(
        _agents(), auth_token="secret", roles=["admin"], model_config_store=store
    )
    with TestClient(app) as client:
        response = client.get("/api/model-config", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json() == {"model": "claude:claude-sonnet-5-5"}


def test_model_config_put_admin_only(tmp_path):
    app = _model_config_app(tmp_path, roles=["operator"])
    with TestClient(app) as client:
        response = client.put(
            "/api/model-config",
            json={"model": "gemini:gemini-2.5-pro"},
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 403


def test_model_config_put_validates_provider(tmp_path):
    app = _model_config_app(tmp_path)
    with TestClient(app) as client:
        response = client.put(
            "/api/model-config",
            json={"model": "bogus:foo"},
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_model"}


def test_model_config_put_persists_and_audits(tmp_path):
    from adk_agent import models

    store = FileModelConfigStore(tmp_path / "model")
    sink = ListAuditSink()
    app = build_console_app(
        _agents(), auth_token="secret", roles=["admin"], model_config_store=store, audit_sink=sink
    )
    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/model-config",
                json={"model": "gemini:gemini-2.5-pro"},
                headers={"Authorization": "Bearer secret"},
            )
            assert response.status_code == 200
            assert response.json() == {"model": "gemini:gemini-2.5-pro"}
            got = client.get("/api/model-config", headers={"Authorization": "Bearer secret"})
            assert got.json() == {"model": "gemini:gemini-2.5-pro"}
    finally:
        models.set_default_model(None)

    events = [event for event in sink.recent() if event.action == "model.configure"]
    assert len(events) == 1
    assert events[0].status == "ok"
    assert events[0].target == "gemini:gemini-2.5-pro"


def test_import_terminology_requires_semantics_write():
    with _client() as client:
        response = client.post(
            "/api/import/terminology",
            json={"scheme_id": "products", "concepts": []},
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_import_agent_requires_registry_publish():
    with _client() as client:
        response = client.post(
            "/api/import/agent",
            json={"id": "bot", "version": "1.0.0", "tenant": "local"},
            headers={"Authorization": "Bearer secret"},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}
