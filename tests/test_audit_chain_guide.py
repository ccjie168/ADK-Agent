"""SLICE-203: the operations guide explains how audit chains are verified."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "docs" / "guides" / "operations.md"


def _text() -> str:
    return OPERATIONS.read_text(encoding="utf-8")


def test_operations_guide_explains_audit_chain_hashing():
    text = _text()
    assert "ADR-0037" in text
    assert "存储内容" in text
    assert "verify-audit" in text
    assert "规范形式复现" in text
    assert "不会因升级恢复" in text


def test_operations_guide_links_audit_chain_contract():
    assert "audit_chain.md" in _text()
