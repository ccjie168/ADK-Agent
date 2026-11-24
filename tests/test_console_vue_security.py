"""SLICE-273: the security panel and its fixed error-code mapping."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_security_view_requires_ops_read():
    src = _read("src", "views", "SecurityView.vue")

    assert 'hasCapability("ops.read")' in src
    assert "无访问权限" in src


def test_security_view_verifies_the_audit_chain():
    src = _read("src", "views", "SecurityView.vue")

    assert "校验审计链" in src
    assert "?verify=1" in src


def test_security_view_maps_fixed_error_codes():
    src = _read("src", "views", "SecurityView.vue")

    for code in (
        "audit_unavailable",
        "credential_store_unavailable",
        "verify_timeout",
        "chain_broken",
        "backend_unsupported",
        "verify_failed",
        "invalid_keyring",
    ):
        assert code in src


def test_security_view_shows_missing_scan_report():
    src = _read("src", "views", "SecurityView.vue")

    assert "未提供扫描报告" in src


def test_security_view_has_no_raw_html():
    src = _read("src", "views", "SecurityView.vue")

    assert "v-html" not in src


def test_security_route_is_registered():
    router = _read("src", "router", "index.ts")
    shell = _read("src", "App.vue")

    assert "SecurityView" in router
    assert 'path: "/security"' in router
    assert 'to="/security"' in shell
