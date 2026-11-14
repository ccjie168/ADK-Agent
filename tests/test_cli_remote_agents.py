"""SLICE-093: the remote-agents CLI reads and writes the same stores as the console."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _digest(char: str = "a") -> str:
    return "sha256:" + char * 64


def _stdout(capsys) -> str:
    return capsys.readouterr().out


def _register_peer(root: str) -> None:
    cli.main(
        [
            "peers",
            "register",
            "--peer-dir",
            root,
            "--id",
            "crm",
            "--tenant",
            "acme",
            "--subject",
            "sub-crm",
        ]
    )


def test_cli_file_flow(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    _register_peer(root)
    capsys.readouterr()

    monkeypatch.setenv("ADK_SECRET_CRM_TOKEN", "tok")
    seen = {}

    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        seen["credential"] = credential
        return _digest("a"), {"name": "crm-bot"}

    monkeypatch.setattr("adk_agent.registry.fetch_agent_card", fake)

    cli.main(
        [
            "remote-agents",
            "register",
            "--peer-dir",
            root,
            "--id",
            "crm-bot",
            "--tenant",
            "acme",
            "--peer",
            "crm",
            "--card-url",
            "https://crm.example.com/card.json",
            "--credential-ref",
            "secret://crm/token",
            "--label",
            "CRM bot",
        ]
    )
    record = json.loads(_stdout(capsys))
    assert record["remote_id"] == "crm-bot"
    assert record["status"] == "pinned"
    assert record["card_digest"] == _digest("a")
    assert record["enabled"] is True
    assert seen["credential"] == "tok"

    cli.main(["remote-agents", "list", "--peer-dir", root, "--tenant", "acme"])
    assert [row["remote_id"] for row in json.loads(_stdout(capsys))] == ["crm-bot"]

    async def fake_changed(url, credential=None, *, client=None, max_bytes=1048576):
        return _digest("b"), {"name": "crm-bot"}

    monkeypatch.setattr("adk_agent.registry.fetch_agent_card", fake_changed)
    cli.main(["remote-agents", "refresh", "--peer-dir", root, "--id", "crm-bot"])
    refreshed = json.loads(_stdout(capsys))
    assert refreshed["status"] == "changed"
    assert refreshed["card_digest"] == _digest("a")
    assert refreshed["observed_digest"] == _digest("b")

    cli.main(["remote-agents", "disable", "--peer-dir", root, "--id", "crm-bot"])
    disabled = json.loads(_stdout(capsys))
    assert disabled["enabled"] is False


def test_cli_missing_exits(tmp_path, capsys):
    root = str(tmp_path / "peer-state")

    with pytest.raises(SystemExit) as exc:
        cli.main(["remote-agents", "disable", "--peer-dir", root, "--id", "missing"])

    assert exc.value.code == 1
    assert "unknown remote agent" in capsys.readouterr().err
