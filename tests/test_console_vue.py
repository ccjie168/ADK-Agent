"""SLICE-236: the Vue SPA is served by the console, legacy shell stays default."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app


def _agents():
    return {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")}


def test_vue_shell_served():
    app = build_console_app(_agents(), auth_token="secret", ui="vue")
    with TestClient(app) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert "ADK Console · Vue" in page.text
    assert '<div id="app"></div>' in page.text


def test_legacy_shell_default():
    app = build_console_app(_agents(), auth_token="secret")
    with TestClient(app) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert "ADK Console" in page.text
    assert "ADK Console · Vue" not in page.text


def test_vue_assets_served():
    app = build_console_app(_agents(), auth_token="secret", ui="vue")
    with TestClient(app) as client:
        page = client.get("/")
        match = re.search(r'src="(/assets/[^"]+)"', page.text)
        assert match, page.text
        asset = client.get(match.group(1))

    assert asset.status_code == 200
