"""SLICE-121: tenant credential reference bindings and tenant-scoped resolution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    credential_env_name,
    parse_credential_ref,
)
from adk_agent.registry import FileCredentialStore
from adk_agent.secretstore import (
    PrefixedEnvSecretProvider,
    SecretNotFound,
    TenantScopedSecretProvider,
    TenantSecretProvider,
)


def _binding(ref: str = "secret://acme/crm-token", **overrides) -> CredentialBinding:
    data = {
        "credential_id": "crm",
        "tenant": "acme",
        "description": "CRM outbound token",
        "created_by": "admin",
        "created_at": datetime(2026, 11, 16, 8, 0, tzinfo=timezone.utc),
    }
    data["secret_ref"] = ref
    data.update(overrides)
    return CredentialBinding(**data)


def test_binding_rejects_foreign_tenant_ref():
    with pytest.raises(ValidationError):
        _binding(ref="secret://other/token")


def test_file_store_roundtrip_and_tenant_isolation(tmp_path):
    store = FileCredentialStore(tmp_path)
    acme = _binding()
    other = _binding(tenant="other", ref="secret://other/token")

    assert asyncio.run(store.add(acme)) == acme
    assert asyncio.run(store.add(other)) == other
    assert asyncio.run(store.get("acme", "crm")) == acme
    assert asyncio.run(store.get("other", "crm")) == other

    listed = asyncio.run(store.list("acme"))

    assert [binding.tenant for binding in listed] == ["acme"]
    assert [binding.credential_id for binding in listed] == ["crm"]


def test_file_store_conflict_and_disable(tmp_path):
    store = FileCredentialStore(tmp_path)
    binding = _binding()

    assert asyncio.run(store.add(binding)) == binding
    assert asyncio.run(store.add(binding)) == binding
    with pytest.raises(CredentialConflict):
        asyncio.run(store.add(_binding(description="different")))

    disabled = asyncio.run(store.disable("acme", "crm", by="alice"))
    again = asyncio.run(store.disable("acme", "crm", by="bob"))

    assert disabled.enabled is False
    assert again.enabled is False
    with pytest.raises(CredentialNotFound):
        asyncio.run(store.disable("acme", "missing", by="alice"))


def test_tenant_provider_maps_prefixed_env(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_ACME_CRM_TOKEN", "token-value")

    assert asyncio.run(TenantSecretProvider().resolve("secret://acme/crm-token")) == "token-value"


def test_tenant_provider_rejects_single_segment_ref(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_TOKEN", "token-value")

    with pytest.raises(SecretNotFound):
        asyncio.run(TenantSecretProvider().resolve("secret://token"))


def test_tenant_scoped_provider_rejects_cross_tenant_ref(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_OTHER_TOKEN", "token-value")
    provider = TenantScopedSecretProvider(TenantSecretProvider(), "acme")

    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("secret://other/token"))


def test_tenant_scoped_provider_allows_global_ref(monkeypatch):
    monkeypatch.setenv("ADK_SECRET_TOKEN", "token-value")
    provider = TenantScopedSecretProvider(PrefixedEnvSecretProvider(), "acme")

    assert asyncio.run(provider.resolve("secret://token")) == "token-value"


def test_credential_env_name():
    assert credential_env_name("secret://acme/crm-token") == "ADK_SECRET_ACME_CRM_TOKEN"
    assert (
        credential_env_name("secret://Acme.Prod/crm.token-v1")
        == "ADK_SECRET_ACME_PROD_CRM_TOKEN_V1"
    )
    assert parse_credential_ref("secret://acme/token") == ("acme", "token")

    for reference in ("secret://token", "secret://acme", "secret://a/b/c"):
        with pytest.raises(ValueError):
            parse_credential_ref(reference)
        with pytest.raises(ValueError):
            credential_env_name(reference)


def test_file_store_replace_requires_an_existing_binding(tmp_path):
    store = FileCredentialStore(tmp_path)
    binding = _binding()
    asyncio.run(store.add(binding))
    changed = binding.model_copy(update={"description": "rotated"})

    assert asyncio.run(store.replace(changed)) == changed
    assert asyncio.run(store.get("acme", "crm")) == changed
    with pytest.raises(CredentialNotFound):
        asyncio.run(store.replace(_binding(tenant="other", ref="secret://other/token")))
