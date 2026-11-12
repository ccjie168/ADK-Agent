"""SLICE-046: CLI flags for MCP audit and quota."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli
from adk_agent.audit import JsonlAuditSink
from adk_agent.runtime.quota import InMemoryQuotaManager


def _quota_file(tmp_path) -> str:
    path = tmp_path / "quota.json"
    path.write_text(json.dumps({"tenants": {"acme": {"max_runs": 1}}}), encoding="utf-8")
    return str(path)


def _patch_serve(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agent", lambda path: object())
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_agent", lambda agent, **kwargs: captured.update(kwargs)
    )
    return captured


def test_serve_forwards_audit_and_quota(tmp_path, monkeypatch):
    captured = _patch_serve(monkeypatch)
    monkeypatch.delenv("QUOTA_URL", raising=False)
    audit = str(tmp_path / "audit.jsonl")

    cli.main(
        [
            "serve",
            "--agent",
            "x.py",
            "--audit-file",
            audit,
            "--quota-config",
            _quota_file(tmp_path),
        ]
    )

    assert isinstance(captured["audit"], JsonlAuditSink)
    assert isinstance(captured["quota"], InMemoryQuotaManager)
    assert captured["quota_config"].tenants["acme"].max_runs == 1


def test_serve_many_forwards_audit_and_quota(tmp_path, monkeypatch):
    captured: dict = {}
    monkeypatch.setattr("adk_agent.cli._load_agents", lambda path: {})
    monkeypatch.setattr(
        "adk_agent.mcp.server.serve_many", lambda agents, **kwargs: captured.update(kwargs)
    )
    monkeypatch.delenv("QUOTA_URL", raising=False)
    audit = str(tmp_path / "audit.jsonl")

    cli.main(
        [
            "serve-many",
            "--agents",
            "x.py",
            "--audit-file",
            audit,
            "--quota-config",
            _quota_file(tmp_path),
        ]
    )

    assert isinstance(captured["audit"], JsonlAuditSink)
    assert isinstance(captured["quota"], InMemoryQuotaManager)
    assert captured["quota_config"].tenants["acme"].max_runs == 1


def test_bad_quota_config_exits_1(tmp_path, monkeypatch, capsys):
    _patch_serve(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        cli.main(["serve", "--agent", "x.py", "--quota-config", str(bad)])

    assert exc.value.code == 1
    assert "quota config" in capsys.readouterr().err


def test_audit_flags_are_exclusive(tmp_path, monkeypatch):
    _patch_serve(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve",
                "--agent",
                "x.py",
                "--audit-file",
                str(tmp_path / "audit.jsonl"),
                "--audit-url",
                "http://127.0.0.1:9/v1/events",
            ]
        )

    assert exc.value.code == 2


def test_runtime_flags_default_off(tmp_path, monkeypatch):
    captured = _patch_serve(monkeypatch)

    cli.main(["serve", "--agent", "x.py"])

    assert captured["audit"] is None
    assert captured["quota"] is None
    assert captured["quota_config"] is None
