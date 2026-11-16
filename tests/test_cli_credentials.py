"""SLICE-121: the credentials CLI and the connector registration binding check."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def test_cli_file_flow(tmp_path, capsys):
    cli.main(
        [
            "credentials",
            "register",
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--tenant",
            "acme",
            "--id",
            "crm",
            "--secret-ref",
            "secret://acme/token",
            "--description",
            "CRM token",
        ]
    )
    created = json.loads(capsys.readouterr().out)
    assert created["credential_id"] == "crm"
    assert created["tenant"] == "acme"
    assert created["enabled"] is True

    cli.main(
        [
            "credentials",
            "list",
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--tenant",
            "acme",
        ]
    )
    listed = json.loads(capsys.readouterr().out)
    assert [item["credential_id"] for item in listed] == ["crm"]

    cli.main(
        [
            "credentials",
            "disable",
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--tenant",
            "acme",
            "--id",
            "crm",
        ]
    )
    disabled = json.loads(capsys.readouterr().out)
    assert disabled["enabled"] is False


def test_cli_foreign_tenant_ref_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "credentials",
                "register",
                "--credentials-dir",
                str(tmp_path / "credentials"),
                "--tenant",
                "acme",
                "--id",
                "crm",
                "--secret-ref",
                "secret://other/token",
            ]
        )

    assert exc.value.code == 1
    assert "credential" in capsys.readouterr().err


def test_cli_disable_missing_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "credentials",
                "disable",
                "--credentials-dir",
                str(tmp_path / "credentials"),
                "--tenant",
                "acme",
                "--id",
                "crm",
            ]
        )

    assert exc.value.code == 1
    assert "credential" in capsys.readouterr().err


def test_cli_connector_register_requires_binding(tmp_path, capsys):
    args = [
        "connectors",
        "register",
        "--connectors-dir",
        str(tmp_path / "connectors"),
        "--credentials-dir",
        str(tmp_path / "credentials"),
        "--tenant",
        "acme",
        "--id",
        "crm",
        "--kind",
        "http",
        "--base-url",
        "https://crm.example.com",
        "--auth-ref",
        "secret://acme/token",
    ]
    with pytest.raises(SystemExit) as exc:
        cli.main(args)

    assert exc.value.code == 1
    assert "credential_unbound" in capsys.readouterr().err

    cli.main(
        [
            "credentials",
            "register",
            "--credentials-dir",
            str(tmp_path / "credentials"),
            "--tenant",
            "acme",
            "--id",
            "crm",
            "--secret-ref",
            "secret://acme/token",
        ]
    )
    capsys.readouterr()

    cli.main(args)
    created = json.loads(capsys.readouterr().out)
    assert created["connector_id"] == "crm"
