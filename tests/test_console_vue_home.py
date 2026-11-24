"""SLICE-276: the shared page chrome and the configurable home."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_overview_uses_shared_components():
    src = _read("src", "views", "OverviewView.vue")
    header = _read("src", "components", "PageHeader.vue")
    empty = _read("src", "components", "EmptyState.vue")

    assert "PageHeader" in src
    assert "EmptyState" in src
    assert "<slot" in header
    assert "<slot" in empty


def test_home_sections_persist_locally():
    src = _read("src", "views", "OverviewView.vue")

    assert "adk.home.sections" in src
    assert "localStorage.setItem" in src
    assert "JSON.parse" in src
    assert "JSON.stringify" in src


def test_home_sections_can_be_hidden():
    src = _read("src", "views", "OverviewView.vue")

    for flag in ("sections.quick", "sections.cards", "sections.activity"):
        assert f'v-if="{flag}' in src
    assert "恢复默认" in src


def test_home_quick_actions_are_gated():
    src = _read("src", "views", "OverviewView.vue")

    for capability in ("registry.publish", "registry.load", "approvals.read", "ops.read"):
        assert capability in src
    for route in ("/import", "/registry", "/approvals", "/security"):
        assert f'"{route}"' in src


def test_home_loads_recent_audit():
    src = _read("src", "views", "OverviewView.vue")

    assert '"/api/audit?limit=6"' in src
    assert "audit.read" in src
    assert "最近活动" in src


def test_home_has_no_raw_html():
    src = _read("src", "views", "OverviewView.vue")

    assert "v-html" not in src


def test_home_customization_handles_edges():
    src = _read("src", "views", "OverviewView.vue")
    reset = src[src.index("function resetSections") : src.index("function displayValue")]

    assert "saveSections()" in reset
    assert "catch" in src
    assert "Number.isNaN" in src
    assert 'v-if="!denied"' in src


def test_home_states_are_distinct():
    src = _read("src", "views", "OverviewView.vue")

    assert "overviewError" in src
    assert "概览数据不可用" in src
    assert "activityLoading" in src
    assert "审计事件不可用" in src
