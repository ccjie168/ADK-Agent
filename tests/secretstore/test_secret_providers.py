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


def _stored_binding(backend, *, enabled=True):

    from adk_agent.core import CredentialBinding
    from adk_agent.secretstore import credential_aad

    aad = credential_aad("acme", "crm")
    return CredentialBinding(
        credential_id="crm",
        tenant="acme",
        secret_ref="secret://acme/token",
        created_by="ops",
        created_at="2026-11-18T00:00:00Z",
        enabled=enabled,
        wrapped_secret=backend.wrap(b"from-store", aad),
        secret_key_id="k1",
        secret_version=1,
    )


def test_ciphertext_without_backend_fails_closed(monkeypatch):
    import os

    from adk_agent.secretstore import LocalKeyBackend, TenantSecretProvider

    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    provider = TenantSecretProvider(credentials=_StoredCredential(_stored_binding(backend)))
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")

    with pytest.raises(Exception, match="key backend"):
        asyncio.run(provider.resolve("secret://acme/token"))


def test_disabled_ciphertext_does_not_fall_back(monkeypatch):
    import os

    from adk_agent.secretstore import LocalKeyBackend, TenantSecretProvider

    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    binding = _stored_binding(backend, enabled=False)
    provider = TenantSecretProvider(backend=backend, credentials=_StoredCredential(binding))
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")

    with pytest.raises(Exception, match="disabled"):
        asyncio.run(provider.resolve("secret://acme/token"))


def test_decryption_failure_does_not_fall_back(monkeypatch):
    import os

    from adk_agent.secretstore import LocalKeyBackend, TenantSecretProvider

    encrypting = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    binding = _stored_binding(encrypting)
    other = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    provider = TenantSecretProvider(backend=other, credentials=_StoredCredential(binding))
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")

    from adk_agent.secretstore import SecretNotFound

    with pytest.raises(SecretNotFound, match="cannot be decrypted"):
        asyncio.run(provider.resolve("secret://acme/token"))


def test_routing_provider_splits_two_segment_references(monkeypatch):
    import os

    from adk_agent.core import CredentialBinding
    from adk_agent.secretstore import (
        LocalKeyBackend,
        PrefixedEnvSecretProvider,
        RoutingSecretProvider,
        TenantSecretProvider,
        credential_aad,
    )

    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    reference = "secret://" + "acme/token"
    binding = CredentialBinding(
        credential_id="crm",
        tenant="acme",
        secret_ref=reference,
        created_by="ops",
        created_at="2026-11-18T00:00:00Z",
        wrapped_secret=backend.wrap(b"stored", credential_aad("acme", "crm")),
        secret_key_id="k1",
        secret_version=1,
    )
    tenant = TenantSecretProvider(backend=backend, credentials=_StoredCredential(binding))
    routing = RoutingSecretProvider(tenant, PrefixedEnvSecretProvider())
    monkeypatch.setenv("ADK_SECRET_GLOBAL", "global")

    assert asyncio.run(routing.resolve(reference)) == "stored"
    assert asyncio.run(routing.resolve("secret://global")) == "global"


def test_routing_provider_fails_closed_without_a_backend(monkeypatch):
    import os

    from adk_agent.secretstore import (
        LocalKeyBackend,
        PrefixedEnvSecretProvider,
        RoutingSecretProvider,
        SecretNotFound,
        TenantSecretProvider,
    )

    encrypting = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    binding = _stored_binding(encrypting)
    routing = RoutingSecretProvider(
        TenantSecretProvider(None, _StoredCredential(binding)), PrefixedEnvSecretProvider()
    )
    monkeypatch.setenv("ADK_SECRET_ACME_TOKEN", "from-env")

    with pytest.raises(SecretNotFound, match="no key backend"):
        asyncio.run(routing.resolve("secret://acme/token"))


def test_routing_provider_rejects_malformed_references():
    from adk_agent.secretstore import (
        PrefixedEnvSecretProvider,
        RoutingSecretProvider,
        SecretNotFound,
        TenantSecretProvider,
    )

    routing = RoutingSecretProvider(TenantSecretProvider(), PrefixedEnvSecretProvider())

    with pytest.raises(SecretNotFound):
        asyncio.run(routing.resolve("secret://a/b/c"))
