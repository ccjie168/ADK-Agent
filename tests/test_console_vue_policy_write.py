"""SLICE-266: the policy panel saves policy edits."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_policy_view_writes_policy():
    src = _read("src", "views", "PolicyView.vue")

    assert 'method: "PUT"' in src
    assert "policy.write" in src
    assert "/api/policy" in src


def test_policy_view_parses_json():
    src = _read("src", "views", "PolicyView.vue")

    assert "JSON.parse" in src
