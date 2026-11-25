"""SLICE-297: write-only model provider keys (ADR-0045 option B)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent import cli
from adk_agent.console import build_console_app
from adk_agent.core import ModelProviderRecord
from adk_agent.registry.model_provider_keys import FileModelProviderKeyStore
from adk_agent.registry.model_providers import FileModelProviderStore
from adk_agent.secretstore.keys import LocalKeyBackend
from adk_agent.secretstore.model_keys import ModelKeyResolver, ModelKeyUnavailable

AUTH = {"Authorization": "Bearer secret"}
OPERATOR = {"Authorization": "Bearer operator"}
KEY = "sk-test-1234abcd"  # pragma: allowlist secret


class _Provider:
    async def resolve(self, credential: str):
        from adk_agent.core import Principal

        if credential == "secret":
            return Principal(tenant="local", subject="root", kind="human", roles=["admin"])
        if credential == "operator":
            return Principal(tenant="local", subject="ops", kind="human", roles=["operator"])
        raise ValueError("bad token")


class _Sink:
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)


def _backend(marker: bytes = b"a") -> LocalKeyBackend:
    return LocalKeyBackend({"k1": marker * 32}, "k1")


def _record(provider_id: str = "deepseek-prod", secret_ref: str | None = None):
    return ModelProviderRecord(
        provider_id=provider_id,
        kind="litellm",
        model="litellm:deepseek/deepseek-v4-pro",
        secret_ref=secret_ref,
        updated_at=datetime(2026, 11, 26, tzinfo=timezone.utc),
        updated_by="root",
    )


def _seed(tmp_path, provider_id: str = "deepseek-prod") -> None:
    asyncio.run(FileModelProviderStore(tmp_path / "providers").put(_record(provider_id)))


def _app(tmp_path, *, entry: bool = True, backend=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token=None,
        oidc=_Provider(),
        model_providers=FileModelProviderStore(tmp_path / "providers"),
        model_keys=FileModelProviderKeyStore(tmp_path / "providers"),
        model_key_entry=entry,
        model_key_backend=backend,
    )


def test_key_entry_lists_masked_hint(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        stored = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY}
        )
        listed = client.get("/api/model-providers", headers=AUTH)

    assert stored.status_code == 200
    assert stored.json()["key_configured"] is True
    assert stored.json()["key_hint"].endswith("abcd")
    provider = listed.json()["providers"][0]
    assert provider["key_configured"] is True
    assert provider["key_hint"].endswith("abcd")


def test_key_entry_writes_ciphertext_only(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        response = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY}
        )
        listed = client.get("/api/model-providers", headers=AUTH).text

    body = response.text
    on_disk = (tmp_path / "providers" / "keys" / "deepseek-prod.json").read_text(encoding="utf-8")
    assert KEY not in body
    assert KEY not in listed
    assert KEY not in on_disk
    assert "wrapped_dek" in on_disk
    assert KEY not in str(json.loads(on_disk))


def test_key_entry_masks_short_keys_fully(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        short = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": "abcd"}
        )
        seven = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": "abcdefg"}
        )
        exact = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": "abcdefgh"}
        )

    assert short.json()["key_hint"] == "…"
    assert "abcd" not in short.text
    assert seven.json()["key_hint"] == "…"
    assert exact.json()["key_hint"] == "abc…efgh"


def test_key_entry_requires_flag(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, entry=False, backend=_backend())) as client:
        response = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY}
        )

    assert response.status_code == 503
    assert response.json() == {"error": "model_key_entry_disabled"}


def test_key_entry_requires_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    monkeypatch.delenv("ADK_SECRET_KEKS_FILE", raising=False)
    monkeypatch.delenv("ADK_SECRET_BACKEND", raising=False)
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=None)) as client:
        response = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY}
        )
        revoked = client.delete("/api/model-providers/deepseek-prod/key", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"error": "model_key_entry_unavailable"}
    assert revoked.status_code == 200
    assert revoked.json()["key_configured"] is False


def test_key_entry_backend_failure_is_unavailable(tmp_path):
    from adk_agent.secretstore import KeyBackendError

    class _Broken:
        def wrap(self, plaintext, aad):
            raise KeyBackendError("backend down")

        def current_key_id(self) -> str:
            return "k1"

    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_Broken())) as client:
        response = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY}
        )

    assert response.status_code == 503
    assert response.json() == {"error": "model_key_entry_unavailable"}


def test_key_entry_unknown_provider(tmp_path):
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        response = client.put(
            "/api/model-providers/missing/key", headers=AUTH, json={"api_key": KEY}
        )

    assert response.status_code == 404
    assert response.json() == {"error": "provider_not_found"}


def test_key_entry_rejects_invalid_key(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        empty = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": ""}
        )
        long = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": "x" * 513}
        )
        wrong = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": 7}
        )
        exact = client.put(
            "/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": "x" * 512}
        )

    assert empty.status_code == 400
    assert long.status_code == 400
    assert wrong.status_code == 400
    assert empty.json() == {"error": "invalid_key"}
    assert exact.status_code == 200


def test_key_entry_revoke(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, backend=_backend())) as client:
        client.put("/api/model-providers/deepseek-prod/key", headers=AUTH, json={"api_key": KEY})
        first = client.delete("/api/model-providers/deepseek-prod/key", headers=AUTH)
        second = client.delete("/api/model-providers/deepseek-prod/key", headers=AUTH)
        events = client.get("/api/audit?limit=20", headers=AUTH).json()

    assert first.status_code == 200
    assert first.json() == {"provider_id": "deepseek-prod", "key_configured": False}
    assert second.status_code == 200
    assert not (tmp_path / "providers" / "keys" / "deepseek-prod.json").exists()
    assert [event["action"] for event in events].count("model.key.revoke") == 2
    assert [event["action"] for event in events].count("model.key.set") == 1


def test_key_resolver_audits_decrypt_failure(tmp_path):
    store = FileModelProviderKeyStore(tmp_path / "providers")
    wrapped = _backend(b"a").wrap(KEY.encode("utf-8"), b"adk-model-provider:deepseek-prod")
    asyncio.run(store.put("deepseek-prod", wrapped, key_id="k1", hint="sk-…abcd"))
    sink = _Sink()
    resolver = ModelKeyResolver(store=store, backend=_backend(b"b"), audit=sink)

    with pytest.raises(ModelKeyUnavailable):
        asyncio.run(resolver.resolve("deepseek-prod"))

    failed = [event for event in sink.events if event.action == "model.key_failed"]
    assert failed
    dumped = " ".join(event.model_dump_json() for event in sink.events)
    assert "sk-test" not in dumped
    assert failed[0].error_code == "decrypt_failed"


def test_key_resolver_audits_unreadable_record(tmp_path):
    root = tmp_path / "providers" / "keys"
    root.mkdir(parents=True)
    (root / "deepseek-prod.json").write_text("{not json", encoding="utf-8")
    sink = _Sink()
    resolver = ModelKeyResolver(
        store=FileModelProviderKeyStore(tmp_path / "providers"),
        backend=_backend(),
        audit=sink,
    )

    with pytest.raises(ModelKeyUnavailable):
        asyncio.run(resolver.resolve("deepseek-prod"))

    failed = [event for event in sink.events if event.action == "model.key_failed"]
    assert failed
    assert failed[0].error_code == "key_unreadable"


def test_key_entry_rejects_repo_directory(monkeypatch):
    monkeypatch.delenv("ADK_SECRET_KEKS", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            [
                "console",
                "--agents",
                "examples/multi_agent/agent.py",
                "--model-key-entry",
                "--model-providers-dir",
                "data/model-providers",
            ]
        )

    assert excinfo.value.code == 1
