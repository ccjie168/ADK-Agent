"""SLICE-267: the registry panel loads, unloads and registers agents."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_registry_view_loads_and_unloads():
    src = _read("src", "views", "RegistryView.vue")

    assert "/api/registry/load" in src
    assert "/api/registry/unload" in src
    assert "registry.load" in src


def test_registry_view_registers_manifest():
    src = _read("src", "views", "RegistryView.vue")

    assert "/api/import/agent" in src
    assert "registry.publish" in src
    assert "JSON.parse" in src
