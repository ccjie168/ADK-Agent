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


def test_cli_stores_an_encrypted_secret(tmp_path, capsys, monkeypatch):
    import base64
    import io
    import os

    monkeypatch.setenv(
        "ADK_SECRET_KEKS",
        json.dumps(
            {"active": "k1", "keys": {"k1": base64.b64encode(os.urandom(32)).decode("ascii")}}
        ),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))

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
            "--secret-stdin",
        ]
    )
    created = json.loads(capsys.readouterr().out)

    assert created["secret_key_id"] == "k1"
    assert created["secret_version"] == 1
    assert "wrapped_secret" not in created
    assert "s3cret" not in json.dumps(created)


def test_cli_rejects_a_multi_line_secret(tmp_path, capsys, monkeypatch):
    import base64
    import io
    import os

    monkeypatch.setenv(
        "ADK_SECRET_KEKS",
        json.dumps(
            {"active": "k1", "keys": {"k1": base64.b64encode(os.urandom(32)).decode("ascii")}}
        ),
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("line1\nline2\n"))

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
                "secret://acme/token",
                "--secret-stdin",
            ]
        )

    assert exc.value.code == 1
    assert "single line" in capsys.readouterr().err


def test_cli_rewraps_to_the_active_key(tmp_path, capsys, monkeypatch):
    import asyncio
    import base64
    import io
    import os

    from adk_agent.registry import FileCredentialStore
    from adk_agent.secretstore import LocalKeyBackend, credential_aad

    directory = str(tmp_path / "credentials")
    k1 = os.urandom(32)
    k2 = os.urandom(32)

    def ring(active: str, keys: dict) -> str:
        return json.dumps(
            {
                "active": active,
                "keys": {kid: base64.b64encode(raw).decode("ascii") for kid, raw in keys.items()},
            }
        )

    monkeypatch.setenv("ADK_SECRET_KEKS", ring("k1", {"k1": k1}))
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret\n"))
    cli.main(
        [
            "credentials",
            "register",
            "--credentials-dir",
            directory,
            "--tenant",
            "acme",
            "--id",
            "crm",
            "--secret-ref",
            "secret://acme/token",
            "--secret-stdin",
        ]
    )
    capsys.readouterr()

    monkeypatch.setenv("ADK_SECRET_KEKS", ring("k2", {"k1": k1, "k2": k2}))
    rewrap = [
        "credentials",
        "rewrap",
        "--credentials-dir",
        directory,
        "--tenant",
        "acme",
    ]

    cli.main([*rewrap, "--dry-run"])
    assert json.loads(capsys.readouterr().out) == {
        "tenant": "acme",
        "rewrapped": 1,
        "skipped": 0,
        "dry_run": True,
    }
    assert asyncio.run(FileCredentialStore(directory).get("acme", "crm")).secret_key_id == "k1"

    cli.main(rewrap)
    assert json.loads(capsys.readouterr().out)["rewrapped"] == 1
    binding = asyncio.run(FileCredentialStore(directory).get("acme", "crm"))
    assert binding.secret_key_id == "k2"
    backend = LocalKeyBackend({"k1": k1, "k2": k2}, "k2")
    assert backend.unwrap(binding.wrapped_secret, credential_aad("acme", "crm")) == b"s3cret"

    cli.main(rewrap)
    assert json.loads(capsys.readouterr().out) == {
        "tenant": "acme",
        "rewrapped": 0,
        "skipped": 1,
        "dry_run": False,
    }
