"""SLICE-263: the Vue SPA gets role and user management panels."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_roles_view_fetches_roles():
    src = _read("src", "views", "RolesView.vue")

    assert "/api/roles" in src
    assert "roles.read" in src


def test_roles_view_writes_roles():
    src = _read("src", "views", "RolesView.vue")

    assert "roles.manage" in src
    assert 'method: "PUT"' in src
    assert 'method: "DELETE"' in src


def test_users_view_fetches_users():
    src = _read("src", "views", "UsersView.vue")

    assert "/api/users" in src
    assert "roles.read" in src


def test_users_view_writes_bindings():
    src = _read("src", "views", "UsersView.vue")

    assert 'method: "PUT"' in src
    assert 'method: "DELETE"' in src
    assert "roles.manage" in src


def test_router_has_roles_and_users():
    router = _read("src", "router", "index.ts")
    app = _read("src", "App.vue")

    assert 'path: "/roles"' in router
    assert 'path: "/users"' in router
    assert "RolesView" in router
    assert "UsersView" in router
    assert 'to="/roles"' in app
    assert 'to="/users"' in app


def test_capabilities_constant_matches_backend():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from adk_agent.core import CAPABILITIES_ALL

    src = _read("src", "api", "capabilities.ts")
    missing = [capability for capability in CAPABILITIES_ALL if f'"{capability}"' not in src]

    assert missing == []
