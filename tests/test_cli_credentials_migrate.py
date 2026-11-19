"""SLICE-162: migrate local KEK credentials to Vault Transit."""

from __future__ import annotations

import asyncio
import base64
import json
import os

import pytest

from adk_agent import cli
from adk_agent.core import CredentialBinding
from adk_agent.registry import FileCredentialStore
from adk_agent.secretstore import (
    KeyBackendError,
    LocalKeyBackend,
    VaultKeyBackend,
    credential_aad,
)

AAD = credential_aad("acme", "crm")


class FakeVault:
    def __init__(self, fail: bool = False, fail_at: int | None = None) -> None:
        self.version = 1
        self.fail = fail
        self.fail_at = fail_at
        self.encrypts = 0
        self.blobs: dict[str, bytes] = {}

    def _store(self, data: bytes) -> str:
        if self.fail or (self.fail_at is not None and self.encrypts + 1 == self.fail_at):
            raise KeyBackendError("vault is unreachable")
        self.encrypts += 1
        token = f"{len(self.blobs):04d}"
        self.blobs[token] = data
        return f"vault:v{self.version}:{token}"

    def __call__(self, path: str, payload: dict) -> dict:
        if path == "transit/encrypt/credential":
            encoded = payload["plaintext"]
            data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_")
            return {"data": {"ciphertext": self._store(data)}}
        if path == "transit/decrypt/credential":
            token = str(payload["ciphertext"]).split(":")[2]
            return {"data": {"plaintext": base64.b64encode(self.blobs[token]).decode("ascii")}}
        if path == "transit/rewrap/credential":
            token = str(payload["ciphertext"]).split(":")[2]
            return {"data": {"ciphertext": self._store(self.blobs[token])}}
        raise AssertionError(f"unexpected path {path}")


def _env(monkeypatch, tmp_path, *, backend: str = "vault") -> LocalKeyBackend:
    raw = os.urandom(32)
    local = LocalKeyBackend({"k1": raw}, "k1")
    keyring = {
        "active": "k1",
        "keys": {"k1": base64.b64encode(raw).decode("ascii")},
    }
    monkeypatch.setenv("ADK_SECRET_KEKS", json.dumps(keyring))
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)
    monkeypatch.setenv("ADK_SECRET_BACKEND", backend)
    monkeypatch.setenv("ADK_VAULT_ADDR", "https://vault.example.com")
    monkeypatch.setenv("ADK_VAULT_KEY", "credential")
    monkeypatch.setenv("ADK_VAULT_TOKEN", "token")
    monkeypatch.delenv("ADK_VAULT_TOKEN_FILE", raising=False)
    monkeypatch.delenv("CREDENTIAL_DATABASE_URL", raising=False)
    return local


def _seed(store: FileCredentialStore, local: LocalKeyBackend) -> None:
    asyncio.run(
        store.add(
            CredentialBinding(
                credential_id="crm",
                tenant="acme",
                secret_ref="secret://acme/token",
                created_by="admin",
                created_at="2026-11-18T00:00:00Z",
                wrapped_secret=local.wrap(b"value", AAD),
                secret_key_id="k1",
                secret_version=1,
            )
        )
    )


def _migrate(tmp_path, capsys, *extra: str) -> dict:
    cli.main(
        [
            "credentials",
            "migrate",
            "--to",
            "vault",
            "--tenant",
            "acme",
            "--credentials-dir",
            str(tmp_path / "credentials"),
            *extra,
        ]
    )
    return json.loads(capsys.readouterr().out)


def test_migrate_rewrites_local_records(tmp_path, monkeypatch, capsys):
    local = _env(monkeypatch, tmp_path)
    fake = FakeVault()
    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", lambda *a, **k: fake)
    store = FileCredentialStore(tmp_path / "credentials")
    _seed(store, local)

    result = _migrate(tmp_path, capsys)

    assert result == {"tenant": "acme", "migrated": 1, "skipped": 0, "dry_run": False}
    migrated = asyncio.run(store.get("acme", "crm"))
    assert migrated is not None
    assert migrated.wrapped_secret is not None
    assert migrated.wrapped_secret["v"] == 2
    assert migrated.wrapped_secret["backend"] == "vault"
    assert migrated.secret_key_id == "vault:v1"
    vault = VaultKeyBackend(fake, "credential")
    assert vault.unwrap(migrated.wrapped_secret, AAD) == b"value"


def test_migrate_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    local = _env(monkeypatch, tmp_path)
    fake = FakeVault()
    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", lambda *a, **k: fake)
    store = FileCredentialStore(tmp_path / "credentials")
    _seed(store, local)

    result = _migrate(tmp_path, capsys, "--dry-run")

    assert result["migrated"] == 1
    assert result["dry_run"] is True
    unchanged = asyncio.run(store.get("acme", "crm"))
    assert unchanged is not None
    assert unchanged.wrapped_secret is not None
    assert unchanged.wrapped_secret["v"] == 1


def test_migrate_skips_records_without_ciphertext(tmp_path, monkeypatch, capsys):
    local = _env(monkeypatch, tmp_path)
    fake = FakeVault()
    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", lambda *a, **k: fake)
    store = FileCredentialStore(tmp_path / "credentials")
    _seed(store, local)
    asyncio.run(
        store.add(
            CredentialBinding(
                credential_id="plain",
                tenant="acme",
                secret_ref="secret://acme/plain",
                created_by="admin",
                created_at="2026-11-18T00:00:00Z",
            )
        )
    )

    result = _migrate(tmp_path, capsys)

    assert result["migrated"] == 1
    assert result["skipped"] == 1


def test_migrate_stops_on_a_vault_failure(tmp_path, monkeypatch, capsys):
    local = _env(monkeypatch, tmp_path)
    fake = FakeVault(fail=True)
    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", lambda *a, **k: fake)
    store = FileCredentialStore(tmp_path / "credentials")
    _seed(store, local)

    with pytest.raises(SystemExit) as exc:
        _migrate(tmp_path, capsys)

    assert exc.value.code == 1
    unchanged = asyncio.run(store.get("acme", "crm"))
    assert unchanged is not None
    assert unchanged.wrapped_secret is not None
    assert unchanged.wrapped_secret["v"] == 1


def test_migrate_partial_failure_then_rerun(tmp_path, monkeypatch, capsys):
    local = _env(monkeypatch, tmp_path)
    fake = FakeVault(fail_at=2)
    monkeypatch.setattr("adk_agent.secretstore.keys._vault_transport", lambda *a, **k: fake)
    store = FileCredentialStore(tmp_path / "credentials")
    _seed(store, local)
    asyncio.run(
        store.add(
            CredentialBinding(
                credential_id="erp",
                tenant="acme",
                secret_ref="secret://acme/erp",
                created_by="admin",
                created_at="2026-11-18T00:00:00Z",
                wrapped_secret=local.wrap(b"erp-value", credential_aad("acme", "erp")),
                secret_key_id="k1",
                secret_version=1,
            )
        )
    )

    with pytest.raises(SystemExit):
        _migrate(tmp_path, capsys)
    err = capsys.readouterr().err
    assert "migration_failed" in err
    states = {
        binding.credential_id: binding.wrapped_secret["v"]
        for binding in asyncio.run(store.list("acme"))
    }
    assert sorted(states.values()) == [1, 2]

    fake.fail_at = None
    capsys.readouterr()
    result = _migrate(tmp_path, capsys)

    assert result["migrated"] == 1
    assert result["skipped"] == 1
    final = {
        binding.credential_id: binding.wrapped_secret["v"]
        for binding in asyncio.run(store.list("acme"))
    }
    assert final == {"crm": 2, "erp": 2}


def test_migrate_rejects_a_v2_record_from_another_backend(tmp_path, monkeypatch, capsys):
    _env(monkeypatch, tmp_path)
    store = FileCredentialStore(tmp_path / "credentials")
    asyncio.run(
        store.add(
            CredentialBinding(
                credential_id="crm",
                tenant="acme",
                secret_ref="secret://acme/token",
                created_by="admin",
                created_at="2026-11-18T00:00:00Z",
                wrapped_secret={"v": 2, "backend": "local"},
                secret_key_id="k1",
                secret_version=1,
            )
        )
    )

    with pytest.raises(SystemExit) as exc:
        _migrate(tmp_path, capsys)

    assert exc.value.code == 1
    unchanged = asyncio.run(store.get("acme", "crm"))
    assert unchanged is not None
    assert unchanged.wrapped_secret == {"v": 2, "backend": "local"}


def test_migrate_requires_the_local_keyring(tmp_path, monkeypatch, capsys):
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("ADK_SECRET_KEKS")
    store = FileCredentialStore(tmp_path / "credentials")
    store.root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(SystemExit) as exc:
        _migrate(tmp_path, capsys)

    assert exc.value.code == 1


def test_migrate_requires_vault_mode(tmp_path, monkeypatch, capsys):
    _env(monkeypatch, tmp_path, backend="local")

    with pytest.raises(SystemExit) as exc:
        _migrate(tmp_path, capsys)

    assert exc.value.code == 1
    assert "ADK_SECRET_BACKEND=vault" in capsys.readouterr().err
