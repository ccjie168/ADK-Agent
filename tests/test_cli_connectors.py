"""SLICE-087: the connectors CLI over the file store."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _register(tmp_path, **overrides):
    args = [
        "connectors",
        "register",
        "--connectors-dir",
        str(tmp_path / "connectors"),
        "--id",
        "crm",
        "--kind",
        "http",
        "--base-url",
        "https://crm.example.com",
        "--auth-ref",
        "secret://crm/token",
        "--methods",
        "GET",
        "--path-prefixes",
        "/v1/crm/",
        "--data-classes",
        "internal",
        "--tenant",
        "acme",
    ]
    for flag, value in overrides.items():
        index = args.index(flag)
        args[index + 1] = value
    return args


def test_cli_file_flow(tmp_path, capsys):
    cli.main(_register(tmp_path))
    created = json.loads(capsys.readouterr().out)
    assert created["connector_id"] == "crm"
    assert created["enabled"] is True

    cli.main(
        [
            "connectors",
            "list",
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--tenant",
            "acme",
        ]
    )
    listed = json.loads(capsys.readouterr().out)
    assert [item["connector_id"] for item in listed] == ["crm"]

    cli.main(
        [
            "connectors",
            "disable",
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--id",
            "crm",
        ]
    )
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["enabled"] is False


def test_cli_conflict_exits(tmp_path, capsys):
    cli.main(_register(tmp_path))
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        cli.main(_register(tmp_path, **{"--base-url": "https://other.example.com"}))

    assert exc.value.code == 1
    assert "connector" in capsys.readouterr().err


def test_cli_disable_missing_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "connectors",
                "disable",
                "--connectors-dir",
                str(tmp_path / "connectors"),
                "--id",
                "crm",
            ]
        )

    assert exc.value.code == 1
    assert "connector" in capsys.readouterr().err
