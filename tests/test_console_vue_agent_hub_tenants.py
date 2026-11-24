"""SLICE-271: the Agent hub can switch tenants (admin) and fetches eval reports."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_agent_hub_tenant_selector():
    src = _read("src", "views", "AgentHubView.vue")

    assert "?tenant=" in src
    assert "admin" in src


def test_agent_hub_fetches_eval_report():
    src = _read("src", "views", "AgentHubView.vue")

    assert "/eval" in src
    assert "has_eval_report" in src
