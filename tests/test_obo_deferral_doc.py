"""SLICE-181: the OBO deferral doc states the deferral and its re-entry conditions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "guides" / "obo-deferral.md"


def test_obo_doc_exists():
    assert DOC.is_file()


def test_obo_doc_states_deferral():
    text = DOC.read_text(encoding="utf-8")
    assert "OBO" in text
    assert "P2" in text
    assert "delegation" in text


def test_obo_doc_requires_new_adr():
    text = DOC.read_text(encoding="utf-8")
    assert "新立 ADR" in text


def test_obo_doc_names_reentry_conditions():
    text = DOC.read_text(encoding="utf-8")
    assert "吞吐瓶颈" in text
    assert "无接触自动化" in text
