"""SLICE-268: the connector and credential panels register and disable entries."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_connectors_view_registers_connector():
    src = _read("src", "views", "ConnectorsView.vue")

    assert 'apiFetch("/api/connectors"' in src or '"/api/connectors"' in src
    assert "connectors.manage" in src
    assert "path_prefixes" in src
    assert "base_url" in src


def test_connectors_view_disables_connector():
    src = _read("src", "views", "ConnectorsView.vue")

    assert "/disable" in src


def test_credentials_view_registers_credential():
    src = _read("src", "views", "CredentialsView.vue")

    assert '"/api/credentials"' in src
    assert "connectors.manage" in src
    assert "secret_ref" in src
    assert "credential_id" in src


def test_credentials_view_never_sends_secret_material():
    src = _read("src", "views", "CredentialsView.vue")

    # The page registers references only; ciphertext fields are server-side.
    assert "wrapped_secret" not in src
