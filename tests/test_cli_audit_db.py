"""SLICE-097: --audit-db and AUDIT_DATABASE_URL wire into audit sinks and serve-audit."""

from __future__ import annotations

import pytest

from adk_agent import cli
from adk_agent.audit import PostgresAuditQuery, PostgresAuditSink


def _agents_file(tmp_path) -> str:
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return str(path)


def _run_console(monkeypatch, tmp_path, *args) -> dict:
    captured: dict = {}
    monkeypatch.setattr("adk_agent.console.run_console", lambda *a, **k: captured.update(k))
    cli.main(["console", "--agents", _agents_file(tmp_path), *args])
    return captured


def _clear_signing(monkeypatch) -> None:
    monkeypatch.delenv("ADK_AUDIT_SIGNING_KEY", raising=False)
    monkeypatch.delenv("ADK_AUDIT_KEYRING", raising=False)


def test_sink_selects_database(monkeypatch, tmp_path):
    _clear_signing(monkeypatch)
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)

    captured = _run_console(monkeypatch, tmp_path, "--audit-db", "postgresql://x/x")

    assert isinstance(captured["audit_sink"], PostgresAuditSink)
    assert isinstance(captured["audit_query"], PostgresAuditQuery)


def test_audit_backend_exclusive(monkeypatch, capsys):
    cases = [
        ["serve-model-gateway", "--audit-file", "a.jsonl", "--audit-db", "postgresql://x/x"],
        [
            "serve-model-gateway",
            "--audit-url",
            "http://127.0.0.1:9",
            "--audit-db",
            "postgresql://x/x",
        ],
    ]
    for argv in cases:
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 2
        assert "not allowed" in capsys.readouterr().err


def test_audit_db_env_fallback(monkeypatch, tmp_path):
    _clear_signing(monkeypatch)
    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgresql://x/x")

    captured = _run_console(monkeypatch, tmp_path)

    assert isinstance(captured["audit_sink"], PostgresAuditSink)
    assert isinstance(captured["audit_query"], PostgresAuditQuery)


def test_audit_file_ignores_env(monkeypatch, tmp_path):
    _clear_signing(monkeypatch)
    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgresql://x/x")
    path = tmp_path / "audit.jsonl"

    captured = _run_console(monkeypatch, tmp_path, "--audit-file", str(path))

    assert not isinstance(captured["audit_sink"], PostgresAuditSink)
    assert not isinstance(captured["audit_query"], PostgresAuditQuery)


def test_serve_audit_requires_a_backend(monkeypatch, capsys):
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(["serve-audit", "--allow-unauthenticated"])

    assert exc.value.code == 2
    assert "requires --out or --audit-db" in capsys.readouterr().err


def test_serve_audit_db_rejects_rotation(monkeypatch, capsys):
    monkeypatch.delenv("AUDIT_DATABASE_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-audit",
                "--audit-db",
                "postgresql://x/x",
                "--audit-max-records",
                "2",
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 2
    assert "only applies" in capsys.readouterr().err


def test_serve_audit_out_ignores_env(monkeypatch, tmp_path):
    _clear_signing(monkeypatch)
    monkeypatch.setenv("AUDIT_DATABASE_URL", "postgresql://x/x")
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    captured: dict = {}

    def fake_build(pipeline, **kwargs):
        captured["pipeline"] = pipeline
        captured["query"] = kwargs.get("query")
        return object()

    monkeypatch.setattr("adk_agent.audit.service.build_audit_pipeline_app", fake_build)

    cli.main(
        [
            "serve-audit",
            "--out",
            str(tmp_path / "audit.jsonl"),
            "--allow-unauthenticated",
        ]
    )

    from adk_agent.audit import AuditPipeline

    assert isinstance(captured["pipeline"], AuditPipeline)
    assert captured["query"] is None
