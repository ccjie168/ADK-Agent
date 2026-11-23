"""SLICE-237: the Vue SPA wires up router, pinia and the bearer-auth client."""

from __future__ import annotations

import json
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_package_declares_router_and_pinia():
    pkg = json.loads(_read("package.json"))
    deps = pkg.get("dependencies", {})

    assert "vue-router" in deps
    assert "pinia" in deps


def test_main_installs_router_and_pinia():
    src = _read("src", "main.ts")

    assert "router" in src
    assert "pinia" in src


def test_router_defines_routes():
    src = _read("src", "router", "index.ts")

    assert "createRouter" in src
    assert "createWebHashHistory" in src
    assert "path:" in src


def test_auth_store_uses_session_token():
    src = _read("src", "stores", "auth.ts")

    assert "/api/me" in src
    assert "/auth/config" in src
    assert "/auth/token" in src
    assert "sessionStorage" in src


def test_api_client_adds_bearer():
    src = _read("src", "api", "client.ts")

    assert "Authorization" in src
    assert "Bearer" in src
