"""SLICE-071: the registry control plane binds tenants and verifies content."""

from __future__ import annotations

import asyncio
import builtins
import importlib.util

import pytest
from fastapi.testclient import TestClient

from adk_agent.core import (
    AgentArtifact,
    AgentManifest,
    AgentRef,
    Principal,
    PublishedAgent,
)
from adk_agent.core.artifact import MEDIA_TYPE
from adk_agent.registry import (
    RegistryConflict,
    TrustStore,
    artifact_digest,
    published_from,
    sign_digest,
)
from adk_agent.registry.service import build_registry_service_app

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None
needs_crypto = pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography is not installed")

AUTH = {"Authorization": "Bearer secret"}
TOKEN = "alice-token"
OIDC_AUTH = {"Authorization": f"Bearer {TOKEN}"}


class MemoryRegistry:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], PublishedAgent] = {}

    async def publish(self, agent: PublishedAgent) -> PublishedAgent:
        key = (agent.manifest.tenant, agent.manifest.id, agent.manifest.version)
        existing = self.records.get(key)
        if existing is not None:
            if existing.digest != agent.digest:
                raise RegistryConflict("digest mismatch")
            return existing
        self.records[key] = agent
        return agent

    async def get(self, ref: AgentRef, tenant: str) -> PublishedAgent | None:
        return self.records.get((tenant, ref.id, ref.version))

    async def list(self, tenant: str) -> builtins.list[PublishedAgent]:
        return sorted(
            (record for key, record in self.records.items() if key[0] == tenant),
            key=lambda record: (record.manifest.id, record.manifest.version),
        )

    async def tenants(self) -> builtins.list[str]:
        return sorted({key[0] for key in self.records})


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def put(self, artifact: AgentArtifact, data: bytes) -> None:
        self.data[artifact.digest] = data

    async def get(self, digest: str) -> bytes | None:
        return self.data.get(digest)

    async def has(self, digest: str) -> bool:
        return digest in self.data


class FakeProvider:
    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self._principal


def _manifest(tenant: str = "t1", version: str = "1.0.0", description: str = "bot"):
    return AgentManifest(
        id="bot",
        version=version,
        tenant=tenant,
        owner=tenant,
        description=description,
        model_policy={"provider_allowlist": ["litellm"]},
        execution_tier="in_process",
    )


def _key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


def _raw(key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _artifact(key, data: bytes = b"zip-bytes"):
    digest = artifact_digest(data)
    return (
        AgentArtifact(
            digest=digest,
            size=len(data),
            signature=sign_digest(digest, key),
            key_id="k1",
        ),
        data,
    )


def _app(registry=None, *, store=None, trust=None, oidc=None, builder_keys=None):
    return build_registry_service_app(
        registry or MemoryRegistry(),
        artifact_store=store,
        trust=trust,
        builder_keys=builder_keys,
        auth_token=None if oidc is not None else "secret",
        oidc=oidc,
    )


def _post(client, record: PublishedAgent, headers=AUTH):
    return client.post("/v1/agents", json=record.model_dump(mode="json"), headers=headers)


def test_healthz_open_and_protected():
    with TestClient(_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/v1/tenants").status_code == 401


def test_publish_and_get():
    record = published_from(_manifest())
    with TestClient(_app()) as client:
        assert _post(client, record).status_code == 201
        response = client.get("/v1/agents/t1/bot/1.0.0", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["digest"] == record.digest


def test_publish_is_idempotent():
    record = published_from(_manifest())
    with TestClient(_app()) as client:
        assert _post(client, record).status_code == 201
        response = _post(client, record)

    assert response.status_code == 201
    assert response.json() == record.model_dump(mode="json")


def test_publish_conflict():
    with TestClient(_app()) as client:
        assert _post(client, published_from(_manifest())).status_code == 201
        response = _post(client, published_from(_manifest(description="other")))

    assert response.status_code == 409
    assert response.json() == {"error": "version_conflict"}


def test_publish_rejects_bad_digest():
    payload = published_from(_manifest()).model_dump(mode="json")
    payload["digest"] = "sha256:" + "0" * 64
    with TestClient(_app()) as client:
        response = client.post("/v1/agents", json=payload, headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_record"}


@needs_crypto
def test_publish_requires_trust_for_artifact():
    artifact, _ = _artifact(_key())
    record = published_from(_manifest(), artifact=artifact)
    with TestClient(_app()) as client:
        response = _post(client, record)

    assert response.status_code == 503
    assert response.json() == {"error": "artifact_trust_unavailable"}


@needs_crypto
def test_publish_rejects_untrusted_artifact():
    artifact, _ = _artifact(_key())
    trust = TrustStore({"k1": _raw(_key())})
    with TestClient(_app(trust=trust)) as client:
        response = _post(client, published_from(_manifest(), artifact=artifact))

    assert response.status_code == 400
    assert response.json() == {"error": "artifact_untrusted"}


def test_list_and_tenants():
    registry = MemoryRegistry()
    asyncio.run(registry.publish(published_from(_manifest(version="1.1.0"))))
    asyncio.run(registry.publish(published_from(_manifest(version="1.0.0"))))
    asyncio.run(registry.publish(published_from(_manifest(tenant="t2"))))

    with TestClient(_app(registry)) as client:
        listed = client.get("/v1/agents?tenant=t1", headers=AUTH)
        tenants = client.get("/v1/tenants", headers=AUTH)

    assert [record["manifest"]["version"] for record in listed.json()["agents"]] == [
        "1.0.0",
        "1.1.0",
    ]
    assert tenants.json() == {"tenants": ["t1", "t2"]}


def test_get_missing():
    with TestClient(_app()) as client:
        response = client.get("/v1/agents/t1/bot/9.9.9", headers=AUTH)

    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_oidc_cross_tenant_forbidden():
    provider = FakeProvider(Principal(tenant="t1", subject="alice", kind="human"))
    with TestClient(_app(oidc=provider)) as client:
        response = client.get("/v1/agents?tenant=t2", headers=OIDC_AUTH)
        own = client.get("/v1/agents", headers=OIDC_AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}
    assert own.status_code == 200


def test_oidc_publish_other_tenant():
    provider = FakeProvider(Principal(tenant="t1", subject="alice", kind="human"))
    with TestClient(_app(oidc=provider)) as client:
        response = _post(client, published_from(_manifest(tenant="t2")), OIDC_AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "tenant_forbidden"}


@needs_crypto
def test_upload_artifact():
    key = _key()
    artifact, data = _artifact(key)
    registry = MemoryRegistry()
    record = published_from(_manifest(), artifact=artifact)
    asyncio.run(registry.publish(record))
    store = MemoryStore()
    with TestClient(_app(registry, store=store, trust=TrustStore({"k1": _raw(key)}))) as client:
        response = client.put(
            f"/v1/artifacts/{artifact.digest}",
            content=data,
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )

    assert response.status_code == 201
    assert response.json() == {"digest": artifact.digest, "size": len(data)}
    assert store.data[artifact.digest] == data


@needs_crypto
def test_upload_without_record():
    key = _key()
    artifact, data = _artifact(key)
    with TestClient(_app(store=MemoryStore(), trust=TrustStore({"k1": _raw(key)}))) as client:
        response = client.put(
            f"/v1/artifacts/{artifact.digest}",
            content=data,
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )

    assert response.status_code == 409
    assert response.json() == {"error": "artifact_not_published"}


@needs_crypto
def test_upload_mismatch():
    key = _key()
    artifact, data = _artifact(key)
    registry = MemoryRegistry()
    record = published_from(_manifest(), artifact=artifact)
    asyncio.run(registry.publish(record))
    other_data = b"zip-bytes-2"
    other_digest = artifact_digest(other_data)
    wrong_size = AgentArtifact(
        digest=other_digest,
        size=len(other_data) + 1,
        signature=sign_digest(other_digest, key),
        key_id="k1",
    )
    asyncio.run(registry.publish(published_from(_manifest(version="2.0.0"), artifact=wrong_size)))
    with TestClient(
        _app(registry, store=MemoryStore(), trust=TrustStore({"k1": _raw(key)}))
    ) as client:
        digest_mismatch = client.put(
            f"/v1/artifacts/{artifact.digest}",
            content=b"other",
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )
        size_mismatch = client.put(
            f"/v1/artifacts/{other_digest}",
            content=other_data,
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )

    assert digest_mismatch.status_code == 400
    assert digest_mismatch.json() == {"error": "digest_mismatch"}
    assert size_mismatch.status_code == 400
    assert size_mismatch.json() == {"error": "size_mismatch"}


@needs_crypto
def test_upload_untrusted_record():
    artifact, data = _artifact(_key())
    registry = MemoryRegistry()
    asyncio.run(registry.publish(published_from(_manifest(), artifact=artifact)))
    with TestClient(
        _app(registry, store=MemoryStore(), trust=TrustStore({"k1": _raw(_key())}))
    ) as client:
        response = client.put(
            f"/v1/artifacts/{artifact.digest}",
            content=data,
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )

    assert response.status_code == 409
    assert response.json() == {"error": "artifact_untrusted"}


def test_upload_wrong_media_type():
    with TestClient(_app(store=MemoryStore())) as client:
        response = client.put(
            "/v1/artifacts/sha256:" + "a" * 64,
            content=b"zip-bytes",
            headers={**AUTH, "Content-Type": "application/zip"},
        )

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_upload_too_large():
    with TestClient(_app(store=MemoryStore())) as client:
        response = client.put(
            "/v1/artifacts/sha256:" + "a" * 64,
            content=b"x" * (8 * 1024 * 1024 + 1),
            headers={**AUTH, "Content-Type": MEDIA_TYPE},
        )

    assert response.status_code == 413
    assert response.json() == {"error": "too_large"}


@needs_crypto
def test_publish_in_process_requires_a_builder_signature():
    key = _key()
    artifact, _ = _artifact(key)
    record = published_from(_manifest(), artifact=artifact)

    with TestClient(_app(store=MemoryStore(), trust=TrustStore({"k1": _raw(key)}))) as client:
        response = _post(client, record)

    assert response.status_code == 503
    assert response.json() == {"error": "builder_key_unavailable"}


@needs_crypto
def test_publish_in_process_rejects_an_untrusted_builder():
    publisher, builder, other = _key(), _key(), _key()
    digest = artifact_digest(b"zip-bytes")
    artifact = AgentArtifact(
        digest=digest,
        size=len(b"zip-bytes"),
        signature=sign_digest(digest, publisher),
        key_id="k1",
        builder_signature=sign_digest(digest, builder),
        builder_key_id="builder-1",
    )
    record = published_from(_manifest(), artifact=artifact)

    with TestClient(
        _app(
            store=MemoryStore(),
            trust=TrustStore({"k1": _raw(publisher)}),
            builder_keys=TrustStore({"builder-1": _raw(other)}),
        )
    ) as client:
        response = _post(client, record)

    assert response.status_code == 400
    assert response.json() == {"error": "artifact_untrusted"}


@needs_crypto
def test_publish_in_process_rejects_a_missing_builder_signature():
    key = _key()
    artifact, _ = _artifact(key)
    record = published_from(_manifest(), artifact=artifact)

    with TestClient(
        _app(
            store=MemoryStore(),
            trust=TrustStore({"k1": _raw(key)}),
            builder_keys=TrustStore({"builder-1": _raw(key)}),
        )
    ) as client:
        response = _post(client, record)

    assert response.status_code == 400
    assert response.json() == {"error": "artifact_untrusted"}


@needs_crypto
def test_publish_in_process_accepts_a_trusted_builder():
    key = _key()
    artifact, _ = _artifact(key)
    signed = artifact.model_copy(
        update={
            "builder_signature": sign_digest(artifact.digest, key),
            "builder_key_id": "builder-1",
        }
    )
    record = published_from(_manifest(), artifact=signed)

    with TestClient(
        _app(
            store=MemoryStore(),
            trust=TrustStore({"k1": _raw(key)}),
            builder_keys=TrustStore({"builder-1": _raw(key)}),
        )
    ) as client:
        response = _post(client, record)

    assert response.status_code == 201
