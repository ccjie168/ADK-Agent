"""SLICE-053: serve-audit rotation and signing flags."""

from __future__ import annotations

import pytest

from adk_agent import cli


def _patch(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(
        "adk_agent.audit.AuditPipeline",
        lambda path, **kwargs: captured.update({"path": path, **kwargs}) or object(),
    )
    monkeypatch.setattr(
        "adk_agent.audit.service.build_audit_pipeline_app",
        lambda pipeline, **kwargs: object(),
    )
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    return captured


def test_serve_audit_forwards_rotation_and_key(tmp_path, monkeypatch):
    captured = _patch(monkeypatch)
    monkeypatch.setenv("ADK_AUDIT_SIGNING_KEY", "k1")

    cli.main(
        [
            "serve-audit",
            "--out",
            str(tmp_path / "audit.jsonl"),
            "--audit-max-records",
            "2",
            "--allow-unauthenticated",
        ]
    )

    assert captured["max_records"] == 2
    assert captured["signing_key"] == "k1"


def test_serve_audit_reads_key_from_env_only(tmp_path, monkeypatch):
    captured = _patch(monkeypatch)
    monkeypatch.delenv("ADK_AUDIT_SIGNING_KEY", raising=False)

    cli.main(
        [
            "serve-audit",
            "--out",
            str(tmp_path / "audit.jsonl"),
            "--allow-unauthenticated",
        ]
    )

    assert captured["signing_key"] is None
    assert captured["max_records"] is None


def test_serve_audit_rejects_nonpositive_rotation(tmp_path, monkeypatch, capsys):
    _patch(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-audit",
                "--out",
                str(tmp_path / "audit.jsonl"),
                "--audit-max-records",
                "0",
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "audit-max-records" in capsys.readouterr().err
