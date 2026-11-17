"""SLICE-021: secret providers resolve references and reject unsafe values."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.secretstore import (
    EnvSecretProvider,
    MappingSecretProvider,
    SecretNotFound,
    secret_header_provider,
)


def test_env_provider_resolves(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "s3cret")
    assert asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN")) == "s3cret"


def test_env_provider_missing(monkeypatch):
    monkeypatch.delenv("DEMO_TOKEN", raising=False)
    with pytest.raises(SecretNotFound) as raised:
        asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN"))
    assert "DEMO_TOKEN" in str(raised.value)
    assert "s3cret" not in str(raised.value)


def test_env_provider_rejects_invalid_reference():
    with pytest.raises(SecretNotFound):
        asyncio.run(EnvSecretProvider().resolve("../etc/passwd"))


def test_env_provider_rejects_newline(monkeypatch):
    monkeypatch.setenv("DEMO_TOKEN", "abc\r\nX-Evil: 1")
    with pytest.raises(SecretNotFound):
        asyncio.run(EnvSecretProvider().resolve("DEMO_TOKEN"))


def test_mapping_provider():
    provider = MappingSecretProvider({"DEMO_TOKEN": "value"})
    assert asyncio.run(provider.resolve("DEMO_TOKEN")) == "value"
    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("MISSING"))


def test_mapping_provider_rejects_empty():
    provider = MappingSecretProvider({"DEMO_TOKEN": ""})
    with pytest.raises(SecretNotFound):
        asyncio.run(provider.resolve("DEMO_TOKEN"))


def test_secret_header_provider():
    provider = secret_header_provider(
        MappingSecretProvider({"DEMO_TOKEN": "value"}),
        {"Authorization": "DEMO_TOKEN"},
    )
    assert asyncio.run(provider(None)) == {"Authorization": "value"}


def test_secret_header_provider_rejects_bad_name():
    with pytest.raises(ValueError):
        secret_header_provider(MappingSecretProvider({}), {"Bad Header": "DEMO_TOKEN"})


class _StoredCredential:
    def __init__(self, binding) -> None:
        self.binding = binding

    async def list(self, tenant):
        return [self.binding] if tenant == self.binding.tenant else []


def test_tenant_provider_prefers_stored_ciphertext(monkeypatch):
    import os

    from adk_agent.core import CredentialBinding
    from adk_agent.secretstore import LocalKeyBackend, TenantSecretProvider, credential_aad

    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    aad = credential_aad("acme", "crm")
    binding = CredentialBinding(
        credential_id="crm",
        tenant="acme",
        secret_ref="secret://acme/token",
        created_by="ops",
        created_at="2026-11-18T00:00:00Z",
        wrapped_secret=backend.wrap(b"from-store", aad),
        secret_key_id="k1",
        secret_version=1,
    )
    provider = TenantSecretProvider(backend=backend, credentials=_StoredCredential(binding))
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")

    assert asyncio.run(provider.resolve("secret://acme/token")) == "from-store"


def test_tenant_provider_falls_back_to_the_environment(monkeypatch):
    from adk_agent.secretstore import TenantSecretProvider

    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")
    provider = TenantSecretProvider()

    assert asyncio.run(provider.resolve("secret://acme/token")) == "from-env"
