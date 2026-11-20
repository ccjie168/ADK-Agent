"""SLICE-193: operations guide covers the pgvector RAG store (ADR-0035 slice 5)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "guides" / "operations.md"


def _text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_operations_guide_covers_pgvector_install():
    text = _text()
    assert "pgvector" in text
    assert "CREATE EXTENSION IF NOT EXISTS vector" in text


def test_operations_guide_covers_dimensions():
    text = _text()
    assert "维度" in text
    assert "重建索引" in text


def test_operations_guide_covers_rag_failure_modes():
    text = _text()
    assert "RagStoreUnavailable" in text
    assert "fail-closed" in text


def test_operations_guide_covers_multi_replica():
    text = _text()
    assert "adk_rag_chunks" in text
    assert "多副本" in text
