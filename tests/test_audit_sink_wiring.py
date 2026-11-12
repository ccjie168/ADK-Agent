"""SLICE-037: wire the audit sink choice into both gateway CLIs."""

from __future__ import annotations

import pytest

from adk_agent.audit import HttpAuditSink, JsonlAuditSink
from adk_agent.cli import main


class FakeProvider:
    name = "litellm"

    async def complete(self, request):
        raise AssertionError("wiring must not call the provider")


def _run_model_gateway(monkeypatch, *args):
    captured = {}

    def fake_build_providers(names, *, vllm_url=None):
        return {"litellm": FakeProvider()}

    def fake_build_app(gateway, **kwargs):
        captured["gateway"] = gateway
        return object()

    monkeypatch.setattr("adk_agent.models.service.build_providers", fake_build_providers)
    monkeypatch.setattr("adk_agent.models.service.build_model_gateway_app", fake_build_app)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    main(["serve-model-gateway", *args])
    return captured["gateway"]


def _run_tool_gateway(monkeypatch, *args):
    captured = {}

    def fake_build_app(gateway, **kwargs):
        captured["gateway"] = gateway
        return object()

    monkeypatch.setattr("adk_agent.cli._load_tools", lambda path: object())
    monkeypatch.setattr("adk_agent.tools.service.build_tool_gateway_app", fake_build_app)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    main(["serve-tool-gateway", "--tools", "ignored.py", *args])
    return captured["gateway"]


def test_model_gateway_wires_http_audit_sink(monkeypatch):
    gateway = _run_model_gateway(monkeypatch, "--audit-url", "http://127.0.0.1:9999")

    assert isinstance(gateway.audit, HttpAuditSink)
    assert gateway.audit.base_url == "http://127.0.0.1:9999"


def test_tool_gateway_wires_http_audit_sink(monkeypatch):
    gateway = _run_tool_gateway(monkeypatch, "--audit-url", "http://127.0.0.1:9999")

    assert isinstance(gateway.audit, HttpAuditSink)
    assert gateway.audit.base_url == "http://127.0.0.1:9999"


def test_gateway_keeps_jsonl_sink(monkeypatch, tmp_path):
    path = tmp_path / "a.jsonl"
    gateway = _run_model_gateway(monkeypatch, "--audit-file", str(path))

    assert isinstance(gateway.audit, JsonlAuditSink)
    assert gateway.audit.path == path


def test_gateway_without_audit_has_no_sink(monkeypatch):
    gateway = _run_model_gateway(monkeypatch)

    assert gateway.audit is None


def test_audit_url_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("ADK_AUDIT_AUTH_TOKEN", "env-secret")
    gateway = _run_model_gateway(monkeypatch, "--audit-url", "http://127.0.0.1:9999")

    assert isinstance(gateway.audit, HttpAuditSink)
    assert gateway.audit.auth_token == "env-secret"


def test_non_loopback_audit_url_with_token_is_allowed(monkeypatch):
    monkeypatch.setenv("ADK_AUDIT_AUTH_TOKEN", "env-secret")
    gateway = _run_model_gateway(monkeypatch, "--audit-url", "http://10.1.2.3:9999")

    assert isinstance(gateway.audit, HttpAuditSink)


def test_audit_flags_are_mutually_exclusive(monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "serve-model-gateway",
                "--audit-file",
                "a.jsonl",
                "--audit-url",
                "http://127.0.0.1:9999",
            ]
        )

    assert exc.value.code == 2


def test_non_loopback_audit_url_without_token_is_refused(monkeypatch):
    monkeypatch.delenv("ADK_AUDIT_AUTH_TOKEN", raising=False)

    with pytest.raises(SystemExit) as exc:
        main(["serve-model-gateway", "--audit-url", "http://10.1.2.3:9999"])

    assert "ADK_AUDIT_AUTH_TOKEN" in str(exc.value)
