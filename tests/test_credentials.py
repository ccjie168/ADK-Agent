"""SLICE-121: tenant credential reference bindings and tenant-scoped resolution."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStoreError,
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


def test_store_reads_fail_closed_on_an_invalid_record(tmp_path):
    store = FileCredentialStore(tmp_path)
    directory = tmp_path / "acme"
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text(
        json.dumps(
            {
                "credential_id": "a" * 200,
                "tenant": "acme",
                "secret_ref": "secret://acme/token",
                "created_by": "admin",
                "created_at": "2026-11-16T08:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CredentialStoreError):
        asyncio.run(store.list("acme"))


def test_file_lock_gives_up_after_bounded_attempts():
    from adk_agent.registry.credentials import _acquire_lock

    def always_busy(handle: int) -> None:
        raise OSError("busy")

    with pytest.raises(CredentialStoreError):
        _acquire_lock(0, always_busy, attempts=3, delay=0)


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


def test_file_store_replace_wrapped_merges_only_the_ciphertext(tmp_path):
    store = FileCredentialStore(tmp_path)
    binding = _binding()
    asyncio.run(store.add(binding))
    wrapped = {"v": 1, "key_id": "k2"}

    updated = asyncio.run(store.replace_wrapped("acme", "crm", wrapped, "k2"))

    assert updated.wrapped_secret == wrapped
    assert updated.secret_key_id == "k2"
    assert updated.description == binding.description
    assert updated.created_by == binding.created_by
    with pytest.raises(CredentialNotFound):
        asyncio.run(store.replace_wrapped("other", "crm", wrapped, "k2"))


def test_file_store_replace_wrapped_keeps_a_concurrent_disable(tmp_path):
    store = FileCredentialStore(tmp_path)
    asyncio.run(store.add(_binding()))
    asyncio.run(store.disable("acme", "crm", by="alice"))

    updated = asyncio.run(store.replace_wrapped("acme", "crm", {"v": 1, "key_id": "k2"}, "k2"))

    assert updated.enabled is False
    assert asyncio.run(store.get("acme", "crm")).enabled is False


def test_store_lock_blocks_another_writer(tmp_path):
    import threading

    from adk_agent.registry.credentials import _store_lock

    path = tmp_path / "acme" / "crm.json"
    held = threading.Event()
    release = threading.Event()
    waited = threading.Event()

    def holder() -> None:
        with _store_lock(path):
            held.set()
            release.wait(5)

    def waiter() -> None:
        with _store_lock(path):
            waited.set()

    first = threading.Thread(target=holder)
    second = threading.Thread(target=waiter)
    first.start()
    assert held.wait(5)
    second.start()
    try:
        assert not waited.wait(0.3)
    finally:
        release.set()
    second.join(5)
    first.join(5)

    assert waited.is_set()


def test_replace_wrapped_reads_after_taking_the_lock(tmp_path):
    import threading

    from adk_agent.registry.credentials import _store_lock

    store = FileCredentialStore(tmp_path)
    asyncio.run(store.add(_binding()))
    path = store._path("acme", "crm")
    wrapped = {"v": 1, "key_id": "k2"}
    done = threading.Event()

    def rewrap() -> None:
        asyncio.run(store.replace_wrapped("acme", "crm", wrapped, "k2"))
        done.set()

    with _store_lock(path):
        worker = threading.Thread(target=rewrap)
        worker.start()
        assert not done.wait(0.3)
        disabled = _binding(enabled=False)
        path.write_text(disabled.model_dump_json(), encoding="utf-8")

    worker.join(5)
    assert done.is_set()
    final = asyncio.run(store.get("acme", "crm"))
    assert final.enabled is False
    assert final.secret_key_id == "k2"


def test_file_store_accepts_a_128_character_id(tmp_path):
    long_id = "a" * 128
    binding = _binding(credential_id=long_id)
    store = FileCredentialStore(tmp_path)

    asyncio.run(store.add(binding))

    assert asyncio.run(store.get("acme", long_id)) == binding
    assert [item.credential_id for item in asyncio.run(store.list("acme"))] == [long_id]


def test_credential_version_is_always_schema_safe():
    from adk_agent.core import credential_version

    assert credential_version(None) == "credential"
    assert credential_version("") == "credential"
    assert credential_version("k1") == "credential.k1"
    assert credential_version("a.b+c-d_e") == "credential.a.b+c-d_e"
    unsafe = credential_version("prod/key")
    assert unsafe.startswith("credential.")
    assert "prod/key" not in unsafe
