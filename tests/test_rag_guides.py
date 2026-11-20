"""SLICE-200: the operations and install guides document RAG (ADR-0036)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "docs" / "guides" / "operations.md"
INSTALL = ROOT / "docs" / "guides" / "install-and-use.md"
CLI_CONTRACT = ROOT / "docs" / "contracts" / "cli.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_operations_guide_documents_rag_runtime():
    text = _read(OPERATIONS)
    for marker in (
        "--rag-db",
        "--rag-dimensions",
        "--rag-model",
        "rag.retrieve",
        "degrade",
        "deny",
    ):
        assert marker in text


def test_install_guide_documents_rag_setup():
    text = _read(INSTALL)
    for marker in (
        '"rag"',
        "rag ingest",
        "rag search",
        "retrieved_context",
        "--rag-db",
    ):
        assert marker in text


def test_guides_record_rag_wiring_gaps():
    operations = _read(OPERATIONS)
    install = _read(INSTALL)
    assert "sandboxed" in operations
    for name in ("MCP", "A2A"):
        assert name in operations
    assert "MCP" in install or "A2A" in install


def test_guides_match_cli_contract():
    contract = _read(CLI_CONTRACT)
    operations = _read(OPERATIONS)
    for flag in ("--rag-db", "--rag-dimensions", "--rag-model", "--rag-provider"):
        assert flag in contract
        assert flag in operations
