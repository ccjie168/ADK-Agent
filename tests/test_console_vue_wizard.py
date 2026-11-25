"""SLICE-281: the console composes and publishes agents from a guided wizard."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def _wizard() -> str:
    return _read("src", "views", "AgentWizardView.vue")


def test_agent_wizard_route_and_nav():
    router = _read("src", "router", "index.ts")
    assert 'path: "/agents/new"' in router
    assert "AgentWizardView" in router

    app = _read("src", "App.vue")
    assert 'to="/agents/new"' in app

    hub = _read("src", "views", "AgentHubView.vue")
    assert 'to="/agents/new"' in hub
    assert "registry.publish" in hub


def test_agent_wizard_reads_templates():
    src = _wizard()
    assert "/api/compose/templates" in src
    assert 'hasCapability("registry.publish")' in src
    for field in ("name", "version", "tenant", "owner", "description", "instruction"):
        assert f'v-model="form.{field}"' in src, field
    assert "data_classes" in src
    assert "tools" in src


def test_agent_wizard_previews_the_bundle():
    src = _wizard()
    assert "/api/compose/preview" in src
    assert "agent_py" in src
    assert "artifact_digest" in src
    assert "<pre" in src


def test_agent_wizard_publish_requires_compose():
    src = _wizard()
    assert 'hasCapability("registry.compose")' in src
    assert '"/api/compose"' in src
    assert "canPublish" in src


def test_agent_wizard_maps_error_codes():
    src = _wizard()
    for code in (
        "compose_invalid",
        "tenant_forbidden",
        "compose_not_configured",
        "registry_not_configured",
        "registry_conflict",
        "artifact_store_unavailable",
        "registry_unavailable",
        "forbidden",
    ):
        assert code in src, code


def test_agent_wizard_shows_the_cli_hint():
    src = _wizard()
    assert "configured" in src
    assert "未启用一键发布" in src
    assert "adk-agent compose" in src


def test_agent_wizard_validates_limits():
    src = _wizard()
    assert "const LIMITS" in src
    for limit in ("64", "256", "2000", "4000", "16"):
        assert limit in src, limit
    assert "validation" in src


def test_agent_wizard_uses_no_raw_html():
    src = _wizard()
    assert "v-html" not in src
    assert "innerHTML" not in src
