"""SLICE-265: the model panel edits the default model from the page."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_model_view_reads_default_model():
    src = _read("src", "views", "ModelView.vue")

    assert "/api/model-config" in src
    assert "model.read" in src


def test_model_view_writes_default_model():
    src = _read("src", "views", "ModelView.vue")

    assert 'method: "PUT"' in src
    assert "model.write" in src
