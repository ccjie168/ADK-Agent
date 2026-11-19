"""SLICE-161: the install and operations guides cover the Vault key backend."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT_ENV = re.compile(r"ADK_VAULT_[A-Z_]+")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_install_guide_names_every_vault_variable():
    source = _read("src/adk_agent/secretstore/keys.py")
    guide = _read("docs/guides/install-and-use.md")

    names = set(VAULT_ENV.findall(source))
    assert names
    assert names <= set(VAULT_ENV.findall(guide))
    assert "ADK_SECRET_BACKEND=vault" in guide


def test_install_guide_has_the_transit_setup_and_policy():
    guide = _read("docs/guides/install-and-use.md")

    assert "vault secrets enable transit" in guide
    assert "vault write -f transit/keys/adk-credentials" in guide
    for operation in ("encrypt", "decrypt", "rewrap"):
        assert f"transit/{operation}/adk-credentials" in guide
    assert "transit/keys/adk-credentials/rotate" in guide
    assert "credentials rewrap" in guide
    assert "fail-closed" in guide


def test_operations_guide_covers_rotation_and_failure():
    guide = _read("docs/guides/operations.md")

    for name in (
        "ADK_SECRET_BACKEND",
        "ADK_VAULT_ADDR",
        "ADK_VAULT_KEY",
        "ADK_VAULT_TOKEN_FILE",
        "ADK_VAULT_TIMEOUT",
    ):
        assert name in guide
    assert "transit/keys/" in guide
    assert "credentials rewrap" in guide
    assert "Vault 不可达" in guide
    assert "secret_unavailable" in guide
