"""SLICE-296: model provider records through the console API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.console import build_console_app
from adk_agent.core import ModelProviderRecord
from adk_agent.registry.model_providers import FileModelProviderStore

AUTH = {"Authorization": "Bearer secret"}
OPERATOR = {"Authorization": "Bearer operator"}


class _Provider:
    async def resolve(self, credential: str):
        from adk_agent.core import Principal

        if credential == "secret":
            return Principal(tenant="local", subject="root", kind="human", roles=["admin"])
        if credential == "operator":
            return Principal(tenant="local", subject="ops", kind="human", roles=["operator"])
        raise ValueError("bad token")


def _record(provider_id: str = "deepseek-prod") -> ModelProviderRecord:
    return ModelProviderRecord(
        provider_id=provider_id,
        kind="litellm",
        model="litellm:deepseek/deepseek-v4-pro",
        secret_ref="secret://local/deepseek",  # pragma: allowlist secret
        updated_at=datetime(2026, 11, 25, tzinfo=timezone.utc),
        updated_by="root",
    )


def _app(tmp_path, *, store: bool = True):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token=None,
        oidc=_Provider(),
        model_providers=FileModelProviderStore(tmp_path / "providers") if store else None,
    )


def test_provider_store_roundtrip(tmp_path):
    store = FileModelProviderStore(tmp_path / "providers")
    asyncio.run(store.put(_record()))

    stored = asyncio.run(store.get("deepseek-prod"))
    listed = asyncio.run(store.list())

    assert stored is not None
    assert stored.secret_ref == "secret://local/deepseek"  # pragma: allowlist secret
    assert [item.provider_id for item in listed] == ["deepseek-prod"]


def test_provider_api_lists_records(tmp_path):
    store = FileModelProviderStore(tmp_path / "providers")
    asyncio.run(store.put(_record()))
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/model-providers", headers=AUTH)

    assert response.status_code == 200
    assert [item["provider_id"] for item in response.json()["providers"]] == ["deepseek-prod"]


def test_provider_api_requires_model_write(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            "/api/model-providers/ops",
            headers=OPERATOR,
            json={"kind": "litellm", "model": "litellm:deepseek/deepseek-v4-pro"},
        )

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_provider_api_rejects_unsafe_id(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            "/api/model-providers/-escape",
            headers=AUTH,
            json={"kind": "litellm", "model": "litellm:deepseek/deepseek-v4-pro"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_provider"}


def test_provider_api_accepts_max_length_id(tmp_path):
    provider_id = "p" * 64
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            f"/api/model-providers/{provider_id}",
            headers=AUTH,
            json={"kind": "litellm", "model": "litellm:deepseek/deepseek-v4-pro"},
        )
        listed = client.get("/api/model-providers", headers=AUTH).json()["providers"]

    assert response.status_code == 200
    assert [item["provider_id"] for item in listed] == [provider_id]
    assert (tmp_path / "providers" / f"{provider_id}.json").is_file()


def test_provider_api_rejects_overlong_id(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            f"/api/model-providers/{'p' * 65}",
            headers=AUTH,
            json={"kind": "litellm", "model": "litellm:deepseek/deepseek-v4-pro"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_provider"}


def test_provider_api_rejects_bad_secret_ref(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            "/api/model-providers/deepseek",
            headers=AUTH,
            json={
                "kind": "litellm",
                "model": "litellm:deepseek/deepseek-v4-pro",
                "secret_ref": "https://example.com/key",  # pragma: allowlist secret
            },
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_provider"}


def test_provider_api_audits_without_key_material(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.put(
            "/api/model-providers/deepseek",
            headers=AUTH,
            json={
                "kind": "litellm",
                "model": "litellm:deepseek/deepseek-v4-pro",
                "secret_ref": "secret://local/deepseek",  # pragma: allowlist secret
            },
        )
        events = client.get("/api/audit?limit=20", headers=AUTH).json()

    assert response.status_code == 200
    assert response.json()["secret_ref"] == "secret://local/deepseek"  # pragma: allowlist secret
    configure = [event for event in events if event["action"] == "model.configure"]
    assert configure
    latest = configure[-1]
    assert latest["provider_kind"] == "litellm"
    assert latest["secret_ref"] == "secret://local/deepseek"  # pragma: allowlist secret
    dumped = str(latest)
    assert "sk-" not in dumped
    assert "deepseek" in dumped


def test_provider_api_404_when_store_missing(tmp_path):
    with TestClient(_app(tmp_path, store=False)) as client:
        response = client.get("/api/model-providers", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "model_providers_not_configured"}
