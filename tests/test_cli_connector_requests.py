"""SLICE-122: the connector-requests CLI over the file stores."""

from __future__ import annotations

import json

import pytest

from adk_agent import cli


def _register_credential(tmp_path) -> None:
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


def _request_args(tmp_path, **overrides) -> list[str]:
    args = [
        "connector-requests",
        "request",
        "--dir",
        str(tmp_path / "requests"),
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
        "--methods",
        "GET",
        "--path-prefixes",
        "/v1/crm/",
        "--data-classes",
        "internal",
        "--reason",
        "Need CRM read access",
    ]
    for flag, value in overrides.items():
        index = args.index(flag)
        args[index + 1] = value
    return args


def test_cli_request_list_approve(tmp_path, capsys):
    _register_credential(tmp_path)
    capsys.readouterr()

    cli.main(_request_args(tmp_path))
    requested = json.loads(capsys.readouterr().out)
    request_id = requested["request_id"]
    assert requested["status"] == "pending"
    assert requested["requested_by"] == "cli"
    assert requested["tenant"] == "acme"

    cli.main(
        [
            "connector-requests",
            "list",
            "--dir",
            str(tmp_path / "requests"),
            "--tenant",
            "acme",
        ]
    )
    listed = json.loads(capsys.readouterr().out)
    assert [item["request_id"] for item in listed] == [request_id]

    cli.main(
        [
            "connector-requests",
            "decide",
            request_id,
            "--approve",
            "--reason",
            "ok",
            "--dir",
            str(tmp_path / "requests"),
            "--connectors-dir",
            str(tmp_path / "connectors"),
            "--credentials-dir",
            str(tmp_path / "credentials"),
        ]
    )
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "approved"
    assert decided["registered_connector"] == "crm"

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
    assert [item["connector_id"] for item in json.loads(capsys.readouterr().out)] == ["crm"]


def test_cli_deny_does_not_register(tmp_path, capsys):
    cli.main(_request_args(tmp_path))
    request_id = json.loads(capsys.readouterr().out)["request_id"]

    cli.main(
        [
            "connector-requests",
            "decide",
            request_id,
            "--deny",
            "--reason",
            "not needed",
            "--dir",
            str(tmp_path / "requests"),
            "--connectors-dir",
            str(tmp_path / "connectors"),
        ]
    )
    decided = json.loads(capsys.readouterr().out)
    assert decided["status"] == "denied"
    assert decided["registered_connector"] is None

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
    assert json.loads(capsys.readouterr().out) == []


def test_cli_foreign_tenant_spec_exits(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(_request_args(tmp_path, **{"--auth-ref": "secret://other/token"}))

    assert exc.value.code == 1
    assert "connector request" in capsys.readouterr().err
