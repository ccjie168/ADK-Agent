"""SLICE-278: empty states, scrollable tables and tokenised badges."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"

LIST_VIEWS = (
    "RunsView.vue",
    "PlansView.vue",
    "SessionsView.vue",
    "ToolsView.vue",
    "PeersView.vue",
    "AuditView.vue",
)
TABLE_VIEWS = LIST_VIEWS[:-1]


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


def test_list_pages_use_empty_state():
    for name in LIST_VIEWS:
        src = _read("src", "views", name)
        assert "EmptyState" in src, name
        assert "暂无" in src, name


def test_tables_scroll_on_narrow_screens():
    style = _read("src", "style.css")
    assert ".table-wrap" in style
    assert "overflow-x: auto" in style
    for name in TABLE_VIEWS:
        assert 'class="table-wrap"' in _read("src", "views", name), name


def test_text_stat_values_scale_down():
    style = _read("src", "style.css")
    overview = _read("src", "views", "OverviewView.vue")

    assert ".stat-value-text" in style
    assert "stat-value-text" in overview
    assert "card.value === null" in overview


def test_badges_use_tokens():
    style = _read("src", "style.css")

    assert "var(--success-soft)" in style
    assert "var(--warning-soft)" in style
    assert "var(--danger-soft)" in style
    assert "#e6f5ea" not in style


def test_agent_hub_uses_a_toolbar():
    style = _read("src", "style.css")
    hub = _read("src", "views", "AgentHubView.vue")

    assert 'class="row toolbar"' in hub
    assert ".toolbar" in style
    assert "font: inherit" in style
