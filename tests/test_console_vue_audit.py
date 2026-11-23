"""SLICE-243: the Vue SPA migrates the Audit panel."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return (_WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_audit_view_fetches_audit():
    src = _read("src", "views", "AuditView.vue")

    assert "/api/audit" in src
    assert "audit.read" in src


def test_audit_route_uses_audit_view():
    src = _read("src", "router", "index.ts")

    assert "AuditView" in src
    assert 'path: "/audit"' in src


def test_audit_view_renders_fields():
    src = _read("src", "views", "AuditView.vue")

    assert "trace_id" in src
    assert "latency_ms" in src
