"""SLICE-081: the tool-grants CLI over the file store."""

from __future__ import annotations

import asyncio
import json

import pytest

from adk_agent import cli
from adk_agent.registry import FileToolGrantStore

DIGEST = "sha256:" + "a" * 64


def _request(tmp_path, *, hours="4"):
    return [
        "tool-grants",
        "request",
        "--tool-grants-dir",
        str(tmp_path / "grants"),
        "--tenant",
        "acme",
        "--id",
        "bot",
        "--version",
        "1.0.0",
        "--digest",
        DIGEST,
        "--tool",
        "crm.read",
        "--reason",
        "temporary access",
        "--expires-hours",
        hours,
    ]


def test_cli_file_flow(tmp_path, capsys):
    cli.main(_request(tmp_path))
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "pending"

    cli.main(
        ["tool-grants", "list", "--tool-grants-dir", str(tmp_path / "grants"), "--tenant", "acme"]
    )
    listed = json.loads(capsys.readouterr().out)
    assert [item["request_id"] for item in listed] == [created["request_id"]]

    cli.main(
        [
            "tool-grants",
            "decide",
            "--tool-grants-dir",
            str(tmp_path / "grants"),
            created["request_id"],
            "--approve",
            "--reason",
            "ok",
        ]
    )
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "approved"

    stored = asyncio.run(FileToolGrantStore(tmp_path / "grants").get(created["request_id"]))
    assert stored.status == "approved"


def test_cli_rejects_bad_hours(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_request(tmp_path, hours="0"))

    assert exc.value.code == 1
    assert "expires" in capsys.readouterr().err.lower()
