"""SLICE-124: the triggers CLI (register, list, disable, token handling)."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli

_DIGEST = "sha256:" + "a" * 64


def test_cli_register_list_disable(tmp_path, monkeypatch, capsys):
    root = tmp_path / "triggers"
    token = "cli-webhook-token-0123456789"
    monkeypatch.setenv("ADK_TRIGGER_TOKEN", token)

    cli.main(
        [
            "triggers",
            "register",
            "--dir",
            str(root),
            "--tenant",
            "acme",
            "--id",
            "nightly",
            "--agent-id",
            "assistant",
            "--version",
            "1.0.0",
            "--digest",
            _DIGEST,
            "--every-seconds",
            "3600",
            "--input",
            "Summarize yesterday.",
        ]
    )
    scheduled = json.loads(capsys.readouterr().out)
    assert scheduled["trigger_id"] == "nightly"
    assert scheduled["kind"] == "schedule"
    assert scheduled["every_seconds"] == 3600
    assert scheduled["webhook_token_hash"] is None

    cli.main(
        [
            "triggers",
            "register",
            "--dir",
            str(root),
            "--tenant",
            "acme",
            "--id",
            "webhook",
            "--agent-id",
            "assistant",
            "--version",
            "1.0.0",
            "--digest",
            _DIGEST,
            "--webhook-token-env",
            "ADK_TRIGGER_TOKEN",
        ]
    )
    webhook = json.loads(capsys.readouterr().out)
    assert webhook["kind"] == "webhook"
    assert webhook["every_seconds"] is None
    assert len(webhook["webhook_token_hash"]) == 64
    assert token not in json.dumps(webhook)

    stored = (root / "acme" / "webhook.json").read_text(encoding="utf-8")
    assert token not in stored
    assert webhook["webhook_token_hash"] in stored

    cli.main(["triggers", "list", "--dir", str(root), "--tenant", "acme"])
    listed = json.loads(capsys.readouterr().out)
    assert [item["trigger_id"] for item in listed] == ["nightly", "webhook"]

    cli.main(["triggers", "disable", "--dir", str(root), "--tenant", "acme", "--id", "nightly"])
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["enabled"] is False


def test_cli_token_errors(tmp_path, monkeypatch, capsys):
    root = tmp_path / "triggers"
    monkeypatch.delenv("ADK_MISSING_TOKEN", raising=False)
    base = [
        "triggers",
        "register",
        "--dir",
        str(root),
        "--tenant",
        "acme",
        "--id",
        "hooked",
        "--agent-id",
        "assistant",
        "--version",
        "1.0.0",
        "--digest",
        _DIGEST,
    ]

    with pytest.raises(SystemExit) as exc:
        cli.main([*base, "--webhook-token-env", "ADK_MISSING_TOKEN"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "triggers failed" in captured.err
    assert not (root / "acme" / "hooked.json").exists()

    monkeypatch.setenv("ADK_SHORT_TOKEN", "short")
    with pytest.raises(SystemExit) as exc:
        cli.main([*base, "--webhook-token-env", "ADK_SHORT_TOKEN"])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "triggers failed" in captured.err
    assert "short" not in captured.err
    assert not (root / "acme" / "hooked.json").exists()
