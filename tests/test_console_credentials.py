"""SLICE-121: console credential routes and connector/credential binding checks."""

from __future__ import annotations

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.registry import FileConnectorStore, FileCredentialStore

AUTH = {"Authorization": "Bearer secret"}


def _credential(ref: str = "secret://local/token", **overrides):
    body = {
        "credential_id": "crm",
        "tenant": "local",
        "description": "CRM token",
        "created_by": "client",
        "created_at": "2026-11-16T08:00:00Z",
    }
    body["secret_ref"] = ref
    body.update(overrides)
    return body


def _connector(**overrides):
    body = {
        "connector_id": "crm",
        "tenant": "local",
        "kind": "http",
        "base_url": "https://crm.example.com",
        "auth_ref": "secret://local/token",
        "methods": ["GET"],
        "path_prefixes": ["/v1/crm/"],
        "data_classes": ["internal"],
    }
    body.update(overrides)
    return body


def _app(tmp_path, *, roles=None, connectors=True, credentials=True, audit=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        connectors=FileConnectorStore(tmp_path / "connectors") if connectors else None,
        credentials=FileCredentialStore(tmp_path / "credentials") if credentials else None,
        audit_sink=audit,
    )


def test_panel_is_rendered(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert 'id="tab-credentials"' in page.text
    assert 'id="credentials"' in page.text
    assert 'id="credential-ref"' in page.text
    assert "secret://tenant/name" in page.text


def test_register_lists_and_audits(tmp_path):
    sink = ListAuditSink()
    with TestClient(_app(tmp_path, audit=sink)) as client:
        created = client.post("/api/credentials", json=_credential(), headers=AUTH)
        listed = client.get("/api/credentials?tenant=local", headers=AUTH)

    assert created.status_code == 201
    assert created.json()["credential_id"] == "crm"
    assert created.json()["created_by"] == "console_user"
    assert created.json()["enabled"] is True
    assert [item["credential_id"] for item in listed.json()] == ["crm"]
    [event] = [item for item in sink.recent() if item.action == "credential.register"]
    assert event.target == "local/crm"
    assert event.tenant == "local"


def test_list_filters_by_tenant(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/credentials", json=_credential(), headers=AUTH).status_code == 201
        assert (
            client.post(
                "/api/credentials",
                json=_credential(tenant="acme", ref="secret://acme/token"),
                headers=AUTH,
            ).status_code
            == 201
        )
        local = client.get("/api/credentials?tenant=local", headers=AUTH)
        acme = client.get("/api/credentials?tenant=acme", headers=AUTH)
        disabled = client.post("/api/credentials/crm/disable?tenant=acme", headers=AUTH)

    assert [item["tenant"] for item in local.json()] == ["local"]
    assert [item["tenant"] for item in acme.json()] == ["acme"]
    assert disabled.status_code == 200
    assert disabled.json()["tenant"] == "acme"
    assert disabled.json()["enabled"] is False


def test_disable_idempotent_and_missing(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/credentials", json=_credential(), headers=AUTH).status_code == 201
        first = client.post("/api/credentials/crm/disable", headers=AUTH)
        second = client.post("/api/credentials/crm/disable", headers=AUTH)
        missing = client.post("/api/credentials/missing/disable", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert second.json()["enabled"] is False
    assert missing.status_code == 404
    assert missing.json() == {"error": "credential_not_found"}


def test_invalid_credential_and_forbidden(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        forbidden = client.post("/api/credentials", json=_credential(), headers=AUTH)

    assert forbidden.status_code == 403
    assert forbidden.json() == {"error": "forbidden"}

    with TestClient(_app(tmp_path)) as client:
        invalid = client.post(
            "/api/credentials",
            json=_credential(tenant="acme", ref="secret://other/token"),
            headers=AUTH,
        )
        not_object = client.post("/api/credentials", json=[], headers=AUTH)

    assert invalid.status_code == 400
    assert invalid.json() == {"error": "invalid_credential"}
    assert not_object.status_code == 400
    assert not_object.json() == {"error": "invalid_request"}


def test_register_rejects_body_supplied_ciphertext(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/credentials",
            json=_credential(
                wrapped_secret={"kek": "k1", "nonce": "a" * 12, "ciphertext": "a" * 64},
                secret_key_id="k1",
                secret_version=1,
            ),
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_credential"}


def test_not_configured(tmp_path):
    with TestClient(_app(tmp_path, credentials=False)) as client:
        listed = client.get("/api/credentials?tenant=local", headers=AUTH)
        created = client.post("/api/credentials", json=_credential(), headers=AUTH)

    assert listed.status_code == 404
    assert listed.json() == {"error": "credentials_not_configured"}
    assert created.status_code == 404


def test_connector_registration_requires_enabled_binding(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/credentials", json=_credential(), headers=AUTH).status_code == 201
        bound = client.post("/api/connectors", json=_connector(), headers=AUTH)
    assert bound.status_code == 201

    with TestClient(_app(tmp_path)) as client:
        assert client.post("/api/credentials/crm/disable", headers=AUTH).status_code == 200
        disabled = client.post(
            "/api/connectors", json=_connector(connector_id="disabled"), headers=AUTH
        )
        missing = client.post(
            "/api/connectors",
            json=_connector(connector_id="missing", auth_ref="secret://local/other"),
            headers=AUTH,
        )
        global_ref = client.post(
            "/api/connectors",
            json={**_connector(connector_id="global"), "tenant": None},
            headers=AUTH,
        )
        mismatch = client.post(
            "/api/connectors",
            json=_connector(connector_id="mismatch", tenant="acme"),
            headers=AUTH,
        )

    for response in (disabled, missing, global_ref, mismatch):
        assert response.status_code == 400
        assert response.json() == {"error": "credential_unbound"}


def test_read_requires_capability(tmp_path):
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = client.get("/api/credentials", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_operator_can_read_credentials(tmp_path):
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        response = client.get("/api/credentials", headers=AUTH)

    assert response.status_code == 200


def test_list_does_not_expose_ciphertext(tmp_path):
    import asyncio
    import os

    from adk_agent.core import CredentialBinding
    from adk_agent.secretstore import LocalKeyBackend, credential_aad

    backend = LocalKeyBackend({"k1": os.urandom(32)}, "k1")
    reference = "secret://" + "local/token"
    binding = CredentialBinding(
        credential_id="crm",
        tenant="local",
        secret_ref=reference,
        created_by="ops",
        created_at="2026-11-18T00:00:00Z",
        wrapped_secret=backend.wrap(b"value", credential_aad("local", "crm")),
        secret_key_id="k1",
        secret_version=1,
    )
    asyncio.run(FileCredentialStore(tmp_path / "credentials").add(binding))
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/credentials", headers=AUTH)

    assert response.status_code == 200
    [row] = response.json()
    assert "wrapped_secret" not in row
