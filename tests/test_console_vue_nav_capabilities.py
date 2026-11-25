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
    ("/agents/new", "registry.publish"),
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


def test_nav_hides_empty_groups():
    source = _app()
    for group in ("概览", "运行", "治理", "开发"):
        label = f'<div class="nav-group-label">{group}</div>'
        index = source.index(label)
        window = source[index - 400 : index]
        assert "v-if=" in window, group


def test_ecosystem_needs_any_of_its_three_sources():
    source = _app()
    window = source[source.index('to="/ecosystem"') - 260 : source.index('to="/ecosystem"')]
    for capability in ("tools.read", "connectors.read", "peers.read"):
        assert capability in window, capability
