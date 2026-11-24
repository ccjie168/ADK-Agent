"""SLICE-269: approvals and tool grants can be decided from the page."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_approvals_view_decides():
    src = _read("src", "views", "ApprovalsView.vue")

    assert "approvals.decide" in src
    assert "POST" in src
    assert "approved" in src


def test_grants_view_decides():
    src = _read("src", "views", "GrantsView.vue")

    assert "grants.decide" in src
    assert "/decide" in src
    assert "approved" in src
