"""SLICE-285: list tables keep a readable min width and scroll on narrow screens."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


TABLES = (
    "AgentHubView.vue",
    "ApprovalsView.vue",
    "ConnectorsView.vue",
    "CredentialsView.vue",
    "EcosystemView.vue",
    "GrantsView.vue",
    "OverviewView.vue",
    "PeersView.vue",
    "PlansView.vue",
    "RolesView.vue",
    "RunsView.vue",
    "SessionsView.vue",
    "ToolsView.vue",
    "UsersView.vue",
)


def test_table_wrapper_sets_a_min_width():
    css = _read("src", "style.css")
    assert ".table-wrap table {" in css
    block = css.split(".table-wrap table {", 1)[1].split("}", 1)[0]
    assert "min-width: 720px" in block


def test_list_views_wrap_tables():
    for name in TABLES:
        assert 'class="table-wrap"' in _read("src", "views", name), name


def test_every_view_table_is_wrapped():
    views = _WEB.joinpath("src", "views")
    for path in sorted(views.glob("*.vue")):
        source = path.read_text(encoding="utf-8")
        assert source.count('class="table-wrap"') >= source.count("<table"), path.name
