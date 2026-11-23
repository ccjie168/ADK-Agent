"""SLICE-249: the Vue SPA migrates the Credentials panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_credentials_view_fetches_credentials():
    src = _read("src", "views", "CredentialsView.vue")

    assert "/api/credentials" in src
    assert "connectors.read" in src


def test_credentials_route_uses_credentials_view():
    src = _read("src", "router", "index.ts")

    assert "CredentialsView" in src
    assert 'path: "/credentials"' in src


def test_credentials_view_renders_fields():
    src = _read("src", "views", "CredentialsView.vue")

    assert "credential_id" in src
    assert "secret_ref" in src
