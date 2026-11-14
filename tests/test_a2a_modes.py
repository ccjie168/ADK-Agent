"""SLICE-092: peer mode and legacy mode are mutually exclusive at the library boundary."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import adk_agent.a2a as a2a_module
from adk_agent.a2a import build_a2a_app
from adk_agent.core import AgentManifest, ModelPolicy


def _manifest(exposure: str = "a2a") -> AgentManifest:
    return AgentManifest(
        id="bot",
        version="1.0.0",
        tenant="acme",
        owner="alice",
        model_policy=ModelPolicy(provider_allowlist=["litellm"]),
        exposure=exposure,
    )


def _stores() -> tuple[object, object]:
    return object(), object()


def _tokens() -> dict[str, str]:
    return {"peer-a": "a" * 64}


@pytest.fixture
def fake_sdk(monkeypatch):
    async def ok(request):
        return PlainTextResponse("ok")

    def build(agent, **kwargs):
        return Starlette(routes=[Route("/", ok)])

    monkeypatch.setattr(a2a_module, "_to_a2a", lambda: build)
    return build


def test_peer_mode_requires_manifest():
    peers, grants = _stores()

    with pytest.raises(ValueError, match="exposure"):
        build_a2a_app(object(), peers=peers, peer_grants=grants, peer_tokens=_tokens())


def test_peer_mode_rejects_wrong_exposure():
    peers, grants = _stores()

    with pytest.raises(ValueError, match="exposure"):
        build_a2a_app(
            object(),
            manifest=_manifest("mcp"),
            peers=peers,
            peer_grants=grants,
            peer_tokens=_tokens(),
        )


def test_peer_mode_requires_exactly_one_identity():
    peers, grants = _stores()

    with pytest.raises(ValueError, match="exactly one"):
        build_a2a_app(
            object(),
            manifest=_manifest(),
            peers=peers,
            peer_grants=grants,
            peer_tokens=_tokens(),
            oidc=object(),
        )
    with pytest.raises(ValueError, match="exactly one"):
        build_a2a_app(object(), manifest=_manifest(), peers=peers, peer_grants=grants)


def test_peer_mode_requires_both_stores():
    peers, _ = _stores()

    with pytest.raises(ValueError, match="stores"):
        build_a2a_app(
            object(),
            manifest=_manifest(),
            peers=peers,
            peer_tokens=_tokens(),
        )


def test_peer_mode_builds(fake_sdk):
    peers, grants = _stores()

    app = build_a2a_app(
        object(),
        manifest=_manifest(),
        peers=peers,
        peer_grants=grants,
        peer_tokens=_tokens(),
    )

    assert app is not None


def test_legacy_mode_builds(fake_sdk):
    assert build_a2a_app(object(), auth_token="secret") is not None
