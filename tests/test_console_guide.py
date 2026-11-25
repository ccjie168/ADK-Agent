"""SLICE-294: the console serves a self-contained HTML usage guide."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import console
from adk_agent.console import build_console_app

AUTH = {"Authorization": "Bearer secret"}
ROUTES = (
    "/",
    "/agents",
    "/agents/new",
    "/approvals",
    "/ask-ai",
    "/chat",
    "/connectors",
    "/ecosystem",
    "/credentials",
    "/grants",
    "/import",
    "/peers",
    "/plans",
    "/policy",
    "/registry",
    "/audit",
    "/model",
    "/roles",
    "/quota",
    "/rag",
    "/runs",
    "/security",
    "/semantics",
    "/sessions",
    "/tools",
    "/settings",
    "/users",
)


def _guide() -> str:
    return Path(console._GUIDE_HTML).read_text(encoding="utf-8")


def _app():
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        ui="vue",
    )


def test_guide_route_serves_the_html():
    with TestClient(_app()) as client:
        response = client.get("/guide", headers=AUTH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "控制台使用手册" in response.text


def test_guide_route_is_open_without_a_token():
    with TestClient(_app()) as client:
        response = client.get("/guide")

    assert response.status_code == 200
    assert "控制台使用手册" in response.text


def test_guide_route_404_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(console, "_GUIDE_HTML", tmp_path / "missing.html")

    with TestClient(_app()) as client:
        response = client.get("/guide", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "guide_not_found"}


def test_guide_documents_every_route():
    guide = _guide()
    for path in ROUTES:
        assert f'data-route="{path}"' in guide, path


def test_guide_is_self_contained():
    guide = _guide()
    assert "<script" not in guide
    assert 'src="http' not in guide
    assert 'href="http' not in guide
    assert '<meta name="viewport"' in guide


def test_guide_covers_common_errors():
    guide = _guide()
    for text in (
        "连接器存储不可用",
        "审批存储未配置",
        "角色存储未配置",
        "缺少能力",
    ):
        assert text in guide, text


def test_sidebar_links_the_guide():
    app = Path(console._GUIDE_HTML).parents[2].joinpath("web", "src", "App.vue")
    source = app.read_text(encoding="utf-8")
    assert 'href="/guide"' in source
