"""SLICE-299: the model panel manages provider records and write-only keys."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WEB = _ROOT / "web"


def _view() -> str:
    return (_WEB / "src" / "views" / "ModelView.vue").read_text(encoding="utf-8")


def test_model_view_reads_providers():
    src = _view()

    assert "/api/model-providers" in src
    assert "key_entry" in src
    assert "key_hint" in src
    assert "model.read" in src


def test_model_view_saves_provider():
    src = _view()

    assert 'method: "PUT"' in src
    assert "invalid_provider" in src
    assert "provider_not_found" in src
    assert "model.write" in src


def test_model_view_manages_keys():
    src = _view()

    assert "keyEntry.value = body.key_entry" in src
    assert "/key" in src
    assert 'method: "DELETE"' in src
    assert 'type="password"' in src
    assert "model_key_entry_disabled" in src
    assert "model_key_entry_unavailable" in src
    assert "invalid_key" in src


def test_model_view_gates_on_capabilities():
    src = _view()

    assert 'hasCapability("model.write")' in src
    assert 'v-if="canWrite"' in src or "v-if='canWrite'" in src


def test_model_view_respects_key_entry():
    src = _view()

    assert "keyEntry" in src
    assert 'v-if="keyEntry' in src or 'v-if="keyEntry && canWrite"' in src


def test_model_provider_ui_is_built():
    assets = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (_WEB / "dist" / "assets").glob("*.js")
    )

    assert "/api/model-providers" in assets
    assert "model_key_entry_disabled" in assets


def test_guide_documents_model_providers():
    guide = (_ROOT / "docs" / "guides" / "console-ui.html").read_text(encoding="utf-8")
    section = guide.split('data-route="/model"', 1)[1].split("</section>", 1)[0]

    assert "提供方" in section
    assert "model-providers" in section
    assert "密钥" in section
    assert "sk-…" in section or "掩码" in section
