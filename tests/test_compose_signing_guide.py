"""SLICE-287: the compose signing runbook covers the operational steps."""

from __future__ import annotations

from pathlib import Path

_GUIDES = Path(__file__).resolve().parents[1] / "docs" / "guides"


def _read(name: str) -> str:
    return (_GUIDES / name).read_text(encoding="utf-8")


def test_guide_covers_generation_and_flags():
    text = _read("compose-signing.md")
    assert "openssl genpkey -algorithm ed25519" in text
    assert "chmod 600" in text
    for flag in (
        "--compose-key",
        "--compose-key-id",
        "--compose-builder-key",
        "--compose-builder-key-id",
    ):
        assert flag in text, flag
    assert "POST /api/compose" in text


def test_guide_covers_trust_rotation_and_revocation():
    text = _read("compose-signing.md")
    for token in (
        "--artifact-keys",
        "ADK_ARTIFACT_KEYS",
        "--builder-keys",
        "ADK_BUILDER_KEYS",
        "轮换",
        "撤销",
        "compose_not_configured",
        "agent.compose",
    ):
        assert token in text, token


def test_operations_links_the_guide():
    text = _read("operations.md")
    assert "compose-signing.md" in text


def test_guide_does_not_claim_compose_verifies_the_builder_signature():
    text = _read("compose-signing.md")
    assert "CLI `compose` 只负责签名" in text
    for line in text.splitlines():
        if "自查构建签名 |" in line:
            assert "compose" not in line, line
