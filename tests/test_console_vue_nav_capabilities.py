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


def test_nav_groups_cover_every_child_capability():
    source = _app()
    labels = [match.start() for match in re.finditer(r'<div class="nav-group-label">', source)]
    starts = []
    for label in labels:
        gated = source.rfind("<div v-if=", 0, label)
        plain = source.rfind('<div class="nav-group">', 0, label)
        starts.append(max(gated, plain))
    ends = starts[1:] + [source.index("</nav>")]
    for label, start, end in zip(labels, starts, ends, strict=True):
        segment = source[start:end]
        child_caps = set(re.findall(r"auth\.hasCapability\('([a-z.]+)'\)", segment))
        group_expr = source[start:label]
        for capability in child_caps:
            assert f"auth.hasCapability('{capability}')" in group_expr, (label, capability)


def test_wizard_entry_accepts_publish_or_compose():
    source = _app()
    index = source.index('to="/agents/new"')
    window = source[index - 220 : index]
    assert "auth.hasCapability('registry.publish')" in window
    assert "auth.hasCapability('registry.compose')" in window


def test_ecosystem_needs_any_of_its_three_sources():
    source = _app()
    index = source.index('to="/ecosystem"')
    window = source[index - 260 : index]
    for capability in ("tools.read", "connectors.read", "peers.read"):
        assert capability in window, capability


def test_hub_create_button_accepts_publish_or_compose():
    hub = _WEB.joinpath("src", "views", "AgentHubView.vue").read_text(encoding="utf-8")
    assert 'auth.hasCapability("registry.publish")' in hub
    assert 'auth.hasCapability("registry.compose")' in hub
