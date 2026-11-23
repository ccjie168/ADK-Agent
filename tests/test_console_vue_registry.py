"""SLICE-239: the Vue SPA migrates the Registry (marketplace) panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_registry_view_fetches_registry():
    src = _read("src", "views", "RegistryView.vue")

    assert "/api/registry" in src
    assert "registry.read" in src


def test_registry_route_uses_registry_view():
    src = _read("src", "router", "index.ts")

    assert "RegistryView" in src
    assert 'path: "/registry"' in src


def test_registry_view_renders_badges():
    src = _read("src", "views", "RegistryView.vue")

    assert "untrusted" in src
    assert "retired" in src
