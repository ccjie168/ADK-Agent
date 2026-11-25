"""SLICE-293: governance entries are grouped and empty states carry guidance."""

from __future__ import annotations

from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _read(*parts: str) -> str:
    return _WEB.joinpath(*parts).read_text(encoding="utf-8")


GOVERNANCE_PATHS = (
    "/audit",
    "/security",
    "/policy",
    "/roles",
    "/users",
    "/tools",
    "/grants",
    "/connectors",
    "/credentials",
    "/peers",
    "/semantics",
    "/rag",
    "/quota",
)


def test_governance_nav_is_grouped():
    app = _read("src", "App.vue")
    for label in ("访问控制", "审计与合规", "集成与配额"):
        assert label in app, label
    for path in GOVERNANCE_PATHS:
        assert app.count(f'to="{path}"') == 1, path


def test_empty_state_accepts_guidance():
    component = _read("src", "components", "EmptyState.vue")
    for prop in ("title", "description", "actionLabel", "actionTo"):
        assert prop in component, prop
    assert "<slot" in component


def test_empty_state_keeps_legacy_slot():
    component = _read("src", "components", "EmptyState.vue")
    assert "<slot />" in component or "<slot></slot>" in component


GUIDED_VIEWS = (
    "ApprovalsView.vue",
    "AuditView.vue",
    "ConnectorsView.vue",
    "CredentialsView.vue",
    "GrantsView.vue",
    "PeersView.vue",
    "PolicyView.vue",
    "QuotaView.vue",
    "RolesView.vue",
    "SemanticsView.vue",
    "ToolsView.vue",
)


def test_governance_views_use_guided_empty_states():
    for name in GUIDED_VIEWS:
        view = _read("src", "views", name)
        assert 'import EmptyState from "../components/EmptyState.vue";' in view, name
        assert "<EmptyState" in view, name
        assert "description=" in view, name


ACTIONABLE_ERRORS = {
    "ApprovalsView.vue": "审批存储未配置",
    "ConnectorsView.vue": "连接器存储不可用",
    "CredentialsView.vue": "凭据存储不可用",
    "GrantsView.vue": "授权存储不可用",
    "PeersView.vue": "对端存储不可用",
    "RolesView.vue": "角色存储未配置",
    "ToolsView.vue": "工具目录不可用",
    "PolicyView.vue": "策略存储不可用",
    "SemanticsView.vue": "术语表存储不可用",
    "QuotaView.vue": "配额数据不可用",
}


def test_governance_errors_are_actionable():
    for name, message in ACTIONABLE_ERRORS.items():
        view = _read("src", "views", name)
        assert message in view, name
