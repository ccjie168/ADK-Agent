"""SLICE-277: every view renders the shared page header."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"

VIEWS = (
    "AgentHubView.vue",
    "AgentWizardView.vue",
    "ApprovalsView.vue",
    "AskAiView.vue",
    "AuditView.vue",
    "ChatView.vue",
    "ConnectorsView.vue",
    "CredentialsView.vue",
    "EcosystemView.vue",
    "GrantsView.vue",
    "ImportView.vue",
    "ModelView.vue",
    "OverviewView.vue",
    "PeersView.vue",
    "PlaceholderView.vue",
    "PlansView.vue",
    "PolicyView.vue",
    "QuotaView.vue",
    "RagView.vue",
    "RegistryView.vue",
    "RolesView.vue",
    "RunsView.vue",
    "SecurityView.vue",
    "SemanticsView.vue",
    "SessionsView.vue",
    "ToolsView.vue",
    "UsersView.vue",
)

DESCRIBED = tuple(name for name in VIEWS if name != "PlaceholderView.vue")


def _read(name: str) -> str:
    return _WEB.joinpath("src", "views", name).read_text(encoding="utf-8")


def test_every_view_uses_the_shared_header():
    for name in VIEWS:
        src = _read(name)
        assert "PageHeader" in src, name
        assert "<h1" not in src, name


def test_views_describe_themselves():
    for name in DESCRIBED:
        assert 'description="' in _read(name), name


def test_pages_keep_their_primary_actions():
    registry = _read("RegistryView.vue")
    hub = _read("AgentHubView.vue")
    approvals = _read("ApprovalsView.vue")

    assert "加载" in registry
    assert "切换租户" in hub
    assert "批准" in approvals
