"""SLICE-155: credential configuration errors exit cleanly at every CLI site."""

from __future__ import annotations

import asyncio
import os

import pytest

from adk_agent import cli
from adk_agent.core import ConnectorSpec
from adk_agent.registry import FileConnectorStore

AUTH = ["--allow-unauthenticated"]


def _agents_file(tmp_path):
    path = tmp_path / "agents.py"
    path.write_text(
        "from google.adk.agents import LlmAgent\n"
        "agents = {'probe': LlmAgent(name='probe', model='gemini-2.5-pro', instruction='x')}\n",
        encoding="utf-8",
    )
    return path


def _connector(tmp_path) -> None:
    asyncio.run(
        FileConnectorStore(tmp_path / "connectors").add(
            ConnectorSpec(
                connector_id="crm",
                tenant="local",
                kind="http",
                base_url="https://crm.example.com",
                auth_ref="secret://" + "local/token",
                methods=["GET"],
                path_prefixes=["/v1/crm/"],
                data_classes=["internal"],
            )
        )
    )


def test_tool_gateway_rejects_credentials_without_connectors(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)
    monkeypatch.delenv("CREDENTIAL_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-tool-gateway",
                "--tools",
                str(tmp_path / "tools.py"),
                "--credentials-dir",
                str(tmp_path / "credentials"),
                *AUTH,
            ]
        )

    assert exc.value.code == 1
    assert "require --connectors-dir or CONNECTOR_URL" in capsys.readouterr().err


def test_tool_gateway_rejection_precedes_store_construction(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)
    monkeypatch.delenv("CREDENTIAL_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-tool-gateway",
                "--tools",
                str(tmp_path / "tools.py"),
                "--credential-db",
                "sqlite:///x.db",
                *AUTH,
            ]
        )

    assert exc.value.code == 1
    assert "require --connectors-dir or CONNECTOR_URL" in capsys.readouterr().err


def test_tool_gateway_exits_on_an_invalid_keyring(tmp_path, monkeypatch, capsys):
    _connector(tmp_path)
    monkeypatch.setenv("ADK_SECRET_KEKS", "not-json")
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "serve-tool-gateway",
                "--connectors-dir",
                str(tmp_path / "connectors"),
                "--credentials-dir",
                str(tmp_path / "credentials"),
                *AUTH,
            ]
        )

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "ADK_SECRET_KEKS" in err
    assert "ADK_SECRET_KEKS_FILE" in err


def test_remote_agents_exit_on_an_invalid_keyring(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ADK_SECRET_KEKS", "not-json")
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "remote-agents",
                "register",
                "--peer-dir",
                str(tmp_path / "peers"),
                "--id",
                "crm-bot",
                "--tenant",
                "acme",
                "--peer",
                "crm",
                "--card-url",
                "https://crm.example.com/card.json",
                "--credentials-dir",
                str(tmp_path / "credentials"),
            ]
        )

    assert exc.value.code == 1
    assert "ADK_SECRET_KEKS" in capsys.readouterr().err


def test_console_exits_on_an_invalid_keyring(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ADK_SECRET_KEKS", "not-json")
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                str(_agents_file(tmp_path)),
                "--credentials-dir",
                str(tmp_path / "credentials"),
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "ADK_SECRET_KEKS" in capsys.readouterr().err


def test_vault_mode_reports_vault_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ADK_SECRET_BACKEND", "vault")
    monkeypatch.delenv("ADK_VAULT_ADDR", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "console",
                "--agents",
                str(_agents_file(tmp_path)),
                "--credentials-dir",
                str(tmp_path / "credentials"),
                "--allow-unauthenticated",
            ]
        )

    assert exc.value.code == 1
    assert "invalid Vault key backend configuration" in capsys.readouterr().err


def test_vault_token_file_with_newlines_does_not_leak(tmp_path, monkeypatch, capsys):
    token_file = tmp_path / "vault-token"
    token_file.write_text("REAL-TOKEN-VALUE\nstray-second-line\n", encoding="utf-8")
    if os.name != "nt":
        token_file.chmod(0o600)
    monkeypatch.setenv("ADK_SECRET_BACKEND", "vault")
    monkeypatch.setenv("ADK_VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("ADK_VAULT_KEY", "credential")
    monkeypatch.setenv("ADK_VAULT_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("ADK_VAULT_TOKEN", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "credentials",
                "rewrap",
                "--tenant",
                "acme",
                "--credentials-dir",
                str(tmp_path / "credentials"),
            ]
        )

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "REAL-TOKEN-VALUE" not in err
    assert "single line" in err


def test_credential_db_conflicts_with_the_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CREDENTIAL_DATABASE_URL", "postgresql://localhost/adk")

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "credentials",
                "list",
                "--tenant",
                "acme",
                "--credential-db",
                "postgresql://localhost/other",
            ]
        )

    assert exc.value.code == 2
    assert "conflicts with CREDENTIAL_DATABASE_URL" in capsys.readouterr().err
