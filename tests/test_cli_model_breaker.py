"""SLICE-054: serve-model-gateway breaker flags."""

from __future__ import annotations

import pytest

from adk_agent import cli
from adk_agent.models.breaker import BreakerProvider


class FakeProvider:
    name = "fake"
    egress = "none"

    async def complete(self, request):
        raise AssertionError("not called")


def _patch(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(
        "adk_agent.models.service.build_providers",
        lambda names, *, vllm_url=None: {"fake": FakeProvider()},
    )

    def fake_build_app(gateway, **kwargs):
        captured["gateway"] = gateway
        return object()

    monkeypatch.setattr("adk_agent.models.service.build_model_gateway_app", fake_build_app)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    return captured


def _serve(monkeypatch, *args) -> dict:
    captured = _patch(monkeypatch)
    cli.main(
        [
            "serve-model-gateway",
            "--provider",
            "fake",
            "--allow-unauthenticated",
            *args,
        ]
    )
    return captured


def test_serve_forwards_breaker_settings(monkeypatch):
    captured = _serve(monkeypatch, "--breaker-failures", "3", "--breaker-reset", "7")

    provider = captured["gateway"].providers["fake"]
    assert isinstance(provider, BreakerProvider)
    assert provider._breaker.failure_threshold == 3
    assert provider._breaker.reset_seconds == 7.0


def test_breaker_defaults(monkeypatch):
    captured = _serve(monkeypatch)

    breaker = captured["gateway"].providers["fake"]._breaker
    assert breaker.failure_threshold == 5
    assert breaker.reset_seconds == 30.0


def test_rejects_nonpositive_settings(monkeypatch, capsys):
    _patch(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-model-gateway",
                "--provider",
                "fake",
                "--allow-unauthenticated",
                "--breaker-failures",
                "0",
            ]
        )

    assert exc.value.code == 1
    assert "breaker" in capsys.readouterr().err
