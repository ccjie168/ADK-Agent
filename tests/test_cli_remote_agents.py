"""SLICE-093/SLICE-141: the remote-agents CLI reads and writes the same stores as the console."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timezone

import pytest

from adk_agent import cli
from adk_agent.core import CredentialBinding, RemoteAgent
from adk_agent.registry import FileCredentialStore, FileRemoteAgentStore
from adk_agent.secretstore import LocalKeyBackend, credential_aad


@pytest.fixture(autouse=True)
def _clean_credential_env(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_DATABASE_URL", raising=False)


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


def _keyring(monkeypatch, raw: bytes) -> None:
    monkeypatch.setenv(
        "ADK_SECRET_KEKS",
        json.dumps({"active": "k1", "keys": {"k1": base64.b64encode(raw).decode("ascii")}}),
    )


def _seed_ciphertext(path, value: str, raw: bytes, *, tenant: str = "acme") -> str:
    reference = "secret://" + tenant + "/token"
    backend = LocalKeyBackend({"k1": raw}, "k1")
    asyncio.run(
        FileCredentialStore(path).add(
            CredentialBinding(
                credential_id="crm",
                tenant=tenant,
                secret_ref=reference,
                created_by="ops",
                created_at="2026-11-18T00:00:00Z",
                wrapped_secret=backend.wrap(value.encode(), credential_aad(tenant, "crm")),
                secret_key_id="k1",
                secret_version=1,
            )
        )
    )
    return reference


def _patch_fetch(monkeypatch, seen: dict) -> None:
    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        seen["credential"] = credential
        return _digest("a"), {"name": "crm-bot"}

    monkeypatch.setattr("adk_agent.registry.fetch_agent_card", fake)


def _register_args(root: str, reference: str, credentials_dir: str | None = None) -> list[str]:
    args = [
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
        reference,
        "--label",
        "CRM bot",
    ]
    if credentials_dir is not None:
        args.extend(["--credentials-dir", credentials_dir])
    return args


def test_cli_file_flow(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    _register_peer(root)
    capsys.readouterr()

    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "tok")
    seen: dict = {}
    _patch_fetch(monkeypatch, seen)

    cli.main(_register_args(root, "secret://acme/token"))
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


def test_remote_agents_register_uses_stored_ciphertext(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    credentials = tmp_path / "credentials"
    _register_peer(root)
    capsys.readouterr()
    raw = os.urandom(32)
    _keyring(monkeypatch, raw)
    reference = _seed_ciphertext(credentials, "stored", raw)
    seen: dict = {}
    _patch_fetch(monkeypatch, seen)

    cli.main(_register_args(root, reference, str(credentials)))

    assert json.loads(_stdout(capsys))["remote_id"] == "crm-bot"
    assert seen["credential"] == "stored"


def test_remote_agents_wires_routing_without_a_key_backend(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    credentials = tmp_path / "credentials"
    _register_peer(root)
    capsys.readouterr()
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")
    reference = _seed_ciphertext(credentials, "stored", os.urandom(32))
    seen: dict = {}
    _patch_fetch(monkeypatch, seen)

    with pytest.raises(SystemExit) as exc:
        cli.main(_register_args(root, reference, str(credentials)))

    assert exc.value.code == 1
    assert "no key backend" in capsys.readouterr().err
    assert "credential" not in seen


def test_remote_agents_rejects_cross_tenant_credential_ref(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    _register_peer(root)
    capsys.readouterr()
    monkeypatch.setenv("ADK_SECRET_OTHER_TOKEN", "tok")
    seen: dict = {}
    _patch_fetch(monkeypatch, seen)

    with pytest.raises(SystemExit) as exc:
        cli.main(_register_args(root, "secret://other/token"))

    assert exc.value.code == 1
    assert "another tenant" in capsys.readouterr().err
    assert "credential" not in seen


def test_remote_agents_refresh_scopes_to_the_record_tenant(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    _register_peer(root)
    capsys.readouterr()
    store = FileRemoteAgentStore(root)
    asyncio.run(
        store.put(
            RemoteAgent(
                remote_id="crm-bot",
                tenant="acme",
                peer_id="crm",
                agent_card_url="https://crm.example.com/card.json",
                credential_ref="secret://other/token",
                label="CRM bot",
                card_digest=_digest("a"),
                checked_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
                status="pinned",
            )
        )
    )
    monkeypatch.setenv("ADK_SECRET_OTHER_TOKEN", "tok")
    seen: dict = {}
    _patch_fetch(monkeypatch, seen)

    cli.main(["remote-agents", "refresh", "--peer-dir", root, "--id", "crm-bot"])

    refreshed = json.loads(_stdout(capsys))
    assert refreshed["status"] == "unreachable"
    assert refreshed["card_digest"] == _digest("a")
    assert "credential" not in seen


def test_remote_agents_refresh_uses_the_record_credential(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    credentials = tmp_path / "credentials"
    _register_peer(root)
    capsys.readouterr()
    raw = os.urandom(32)
    _keyring(monkeypatch, raw)
    reference = _seed_ciphertext(credentials, "stored", raw)
    asyncio.run(
        FileRemoteAgentStore(root).put(
            RemoteAgent(
                remote_id="crm-bot",
                tenant="acme",
                peer_id="crm",
                agent_card_url="https://crm.example.com/card.json",
                credential_ref=reference,
                label="CRM bot",
                card_digest=_digest("a"),
                checked_at=datetime(2026, 11, 18, tzinfo=timezone.utc),
                status="pinned",
            )
        )
    )
    seen: dict = {}

    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        seen["credential"] = credential
        return _digest("b"), {"name": "crm-bot"}

    monkeypatch.setattr("adk_agent.registry.fetch_agent_card", fake)

    cli.main(
        [
            "remote-agents",
            "refresh",
            "--peer-dir",
            root,
            "--id",
            "crm-bot",
            "--credentials-dir",
            str(credentials),
        ]
    )

    refreshed = json.loads(_stdout(capsys))
    assert refreshed["status"] == "changed"
    assert seen["credential"] == "stored"


def test_remote_agents_list_and_disable_ignore_the_credential_store(tmp_path, capsys, monkeypatch):
    root = str(tmp_path / "peer-state")
    _register_peer(root)
    capsys.readouterr()
    monkeypatch.setenv("CREDENTIAL_DATABASE_URL", "mysql://unreachable")

    cli.main(["remote-agents", "list", "--peer-dir", root])
    assert json.loads(_stdout(capsys)) == []

    with pytest.raises(SystemExit) as exc:
        cli.main(["remote-agents", "disable", "--peer-dir", root, "--id", "missing"])

    assert exc.value.code == 1
    assert "unknown remote agent" in capsys.readouterr().err
