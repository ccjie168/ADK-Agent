"""SLICE-135: serve-a2a starts from a registry reference."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from adk_agent import cli


def _stub_common(monkeypatch, *, agent=None, peer=None):
    captured: dict = {}
    monkeypatch.setattr(cli, "_install_agent_sandbox", lambda args: None)
    monkeypatch.setattr(cli, "_registry_agents", lambda args: {"bot": agent or object()})
    monkeypatch.setattr(cli, "_peer_a2a", lambda args: peer)
    monkeypatch.setattr("adk_agent.a2a.serve_a2a", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(cli, "_audit_sink", lambda args: None)
    monkeypatch.setattr(cli, "_quota_settings", lambda args: (None, None))
    monkeypatch.setattr(cli, "_rate_limit", lambda args: None)
    monkeypatch.setattr(cli, "_auth_token", lambda args: None)
    return captured


def test_serve_a2a_starts_from_ref(monkeypatch):
    marker = object()
    captured = _stub_common(monkeypatch, agent=marker)

    cli.main(["serve-a2a", "--agent-ref", "acme/bot@1.0.0", "--allow-unauthenticated"])

    assert captured["agent"] is marker


def test_agent_and_ref_conflict(monkeypatch):
    _stub_common(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent",
                "x.py",
                "--agent-ref",
                "acme/bot@1.0.0",
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1


def test_single_ref_only(monkeypatch):
    _stub_common(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-a2a",
                "--agent-ref",
                "acme/bot@1.0.0",
                "--agent-ref",
                "acme/other@1.0.0",
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1


def test_peer_ref_name_mismatch(monkeypatch):
    marker = SimpleNamespace(name="bot")
    peer = {
        "manifest": SimpleNamespace(id="other"),
        "oidc": None,
        "peers": object(),
        "peer_grants": object(),
        "peer_tokens": {},
    }
    _stub_common(monkeypatch, agent=marker, peer=peer)

    with pytest.raises(SystemExit) as exc:
        cli.main(["serve-a2a", "--agent-ref", "acme/bot@1.0.0"])

    assert exc.value.code == 1


def test_sandboxed_ref_uses_proxy(monkeypatch):
    from adk_agent.core import AgentArtifact, AgentManifest
    from adk_agent.sandbox.proxy import build_sandbox_agent

    class _Backend:
        async def run(self, artifact, data, input_text):
            raise AssertionError("not run at startup")

    manifest = AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="acme",
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="sandboxed",
    )
    proxy = build_sandbox_agent(
        manifest,
        AgentArtifact(digest="sha256:" + "a" * 64, size=1),
        b"zip!",
        _Backend(),
    )
    captured = _stub_common(monkeypatch, agent=proxy)
    guards: list[object] = []
    monkeypatch.setattr(
        "adk_agent.tools.install_declared_guards", lambda agent, audit, **kw: guards.append(agent)
    )

    cli.main(["serve-a2a", "--agent-ref", "acme/bot@1.0.0", "--allow-unauthenticated"])

    assert captured["agent"] is proxy
    assert guards == []
