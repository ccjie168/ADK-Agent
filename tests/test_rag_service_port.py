"""SLICE-182: RagService port, Citation type, and the ACL contract (ADR-0032 slice 1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from adk_agent.rag import Citation, RagService

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "contracts" / "rag_service.md"


def test_citation_fields():
    citation = Citation(source_id="s1", snippet="text", acl_checked=True, confidence=0.9)
    assert citation.source_id == "s1"
    assert citation.snippet == "text"
    assert citation.acl_checked is True
    assert citation.confidence == 0.9


def test_citation_confidence_bounds():
    with pytest.raises(ValidationError):
        Citation(source_id="s1", snippet="t", confidence=1.5)
    with pytest.raises(ValidationError):
        Citation(source_id="s1", snippet="t", confidence=-0.1)


def test_citation_requires_source_and_snippet():
    with pytest.raises(ValidationError):
        Citation(source_id="", snippet="t")
    with pytest.raises(ValidationError):
        Citation(source_id="s1", snippet="")


def test_rag_service_importable():
    assert hasattr(RagService, "retrieve")


def test_rag_acl_contract_doc():
    assert CONTRACT.is_file()
    text = CONTRACT.read_text(encoding="utf-8")
    assert "acl_checked" in text
    assert "过滤" in text
    assert "无权" in text
