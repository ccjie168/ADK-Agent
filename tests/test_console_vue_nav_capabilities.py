"""SLICE-288: sidebar entries are hidden unless the principal holds the capability."""

from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"


def _app() -> str:
    return _WEB.joinpath("src", "App.vue").read_text(encoding="utf-8")


ENTRIES = (
    ("/", "ops.read"),
    ("/agents", "registry.read"),
    ("/registry", "registry.read"),
    ("/runs", "runs.read"),
    ("/plans", "runs.read"),
    ("/sessions", "sessions.read"),
    ("/approvals", "approvals.read"),
    ("/chat", "chat.run"),
    ("/ask-ai", "runs.read"),
    ("/audit", "audit.read"),
    ("/security", "ops.read"),
    ("/policy", "policy.read"),
    ("/roles", "roles.read"),
    ("/users", "roles.read"),
    ("/tools", "tools.read"),
    ("/grants", "grants.read"),
    ("/connectors", "connectors.read"),
    ("/credentials", "connectors.read"),
    ("/peers", "peers.read"),
    ("/semantics", "ops.read"),
    ("/rag", "ops.read"),
    ("/quota", "ops.read"),
    ("/model", "model.read"),
    ("/import", "runs.read"),
)


def test_nav_gates_every_entry():
    source = _app()
    for path, capability in ENTRIES:
        gate = f"v-if=\"auth.hasCapability('{capability}')\""
        link = f'to="{path}"'
        assert gate in source, path
        assert link in source, path
        window = source[source.index(link) - 120 : source.index(link)]
        assert gate in window, path


def test_nav_has_no_ungated_entries():
    source = _app()
    links = re.findall(r"<router-link\b[^>]*>", source, re.S)
    for link in links:
        if 'class="nav-item"' not in link:
            continue
        if 'to="/settings"' in link:
            continue
        assert "auth.hasCapability" in link, link


GROUPS = {
    "概览": ("ops.read", "registry.read"),
    "运行": ("runs.read", "sessions.read", "approvals.read", "chat.run"),
    "治理": (
        "ops.read",
        "audit.read",
        "policy.read",
        "roles.read",
        "tools.read",
        "grants.read",
        "connectors.read",
        "peers.read",
    ),
    "开发": (
        "registry.publish",
        "model.read",
        "tools.read",
        "connectors.read",
        "peers.read",
        "runs.read",
    ),
}


def test_nav_groups_cover_every_child_capability():
    source = _app()
    for group, capabilities in GROUPS.items():
        label = f'<div class="nav-group-label">{group}</div>'
        index = source.index(label)
        window = source[index - 700 : index]
        assert "v-if=" in window, group
        for capability in capabilities:
            assert f"auth.hasCapability('{capability}')" in window, (group, capability)


def test_ecosystem_needs_any_of_its_three_sources():
    source = _app()
    window = source[source.index('to="/ecosystem"') - 260 : source.index('to="/ecosystem"')]
    for capability in ("tools.read", "connectors.read", "peers.read"):
        assert capability in window, capability


def test_wizard_entry_accepts_publish_or_compose():
    source = _app()
    index = source.index('to="/agents/new"')
    window = source[index - 220 : index]
    assert "auth.hasCapability('registry.publish')" in window
    assert "auth.hasCapability('registry.compose')" in window
