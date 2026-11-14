"""SLICE-093: console remote A2A agent catalog endpoints."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import PeerIdentity, RemoteAgent, RemoteAgentFetchError
from adk_agent.registry import FilePeerStore, FileRemoteAgentStore
from adk_agent.secretstore import MappingSecretProvider

AUTH = {"Authorization": "Bearer secret"}

CARD = {"name": "crm-bot", "description": "CRM"}


def _digest(char: str = "a") -> str:
    return "sha256:" + char * 64


def _peer(**overrides) -> PeerIdentity:
    data = {"peer_id": "crm", "tenant": "acme", "subject": "sub-crm"}
    data.update(overrides)
    return PeerIdentity(**data)


def _record(**overrides) -> RemoteAgent:
    data = {
        "remote_id": "crm-bot",
        "tenant": "acme",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/card.json",
        "label": "CRM bot",
        "card_digest": _digest(),
        "checked_at": datetime(2000, 1, 1, tzinfo=timezone.utc),
        "status": "pinned",
    }
    data.update(overrides)
    return RemoteAgent(**data)


def _app(tmp_path, *, roles=None, peers=True, remote_agents=True, audit=None, secrets=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        peers=FilePeerStore(tmp_path / "peer-state") if peers else None,
        remote_agents=FileRemoteAgentStore(tmp_path / "peer-state") if remote_agents else None,
        remote_secrets=secrets,
        audit_sink=audit,
    )


def _seed_peer(tmp_path, peer: PeerIdentity | None = None) -> None:
    asyncio.run(FilePeerStore(tmp_path / "peer-state").put(peer or _peer()))


def _seed_remote(tmp_path, record: RemoteAgent | None = None) -> None:
    asyncio.run(FileRemoteAgentStore(tmp_path / "peer-state").put(record or _record()))


def _patch_fetch(monkeypatch, *, digest: str | None = None, card: dict | None = None):
    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        return digest or _digest(), card if card is not None else CARD

    monkeypatch.setattr("adk_agent.console.fetch_agent_card", fake)


def _register_body(**overrides) -> dict:
    body = {
        "remote_id": "crm-bot",
        "tenant": "acme",
        "peer_id": "crm",
        "agent_card_url": "https://crm.example.com/card.json",
    }
    body.update(overrides)
    return body


def test_register_pins_card(tmp_path, monkeypatch):
    sink = ListAuditSink()
    _seed_peer(tmp_path)
    seen = {}

    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        seen["credential"] = credential
        return _digest(), CARD

    monkeypatch.setattr("adk_agent.console.fetch_agent_card", fake)
    secrets = MappingSecretProvider({"secret://crm/token": "tok"})

    with TestClient(_app(tmp_path, audit=sink, secrets=secrets)) as client:
        response = client.post(
            "/api/remote-agents",
            json=_register_body(credential_ref="secret://crm/token", label="CRM bot"),
            headers=AUTH,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pinned"
    assert body["card_digest"] == _digest()
    assert body["observed_digest"] is None
    assert body["enabled"] is True
    assert seen["credential"] == "tok"
    events = [event for event in sink.recent() if event.action == "remote_agent.register"]
    assert events
    assert events[0].target == "crm-bot"
    assert events[0].agent_ref.digest == _digest()
    assert events[0].agent_ref.version == "remote"


def test_register_name_mismatch(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    _patch_fetch(monkeypatch, card={"name": "other"})

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/remote-agents", json=_register_body(), headers=AUTH)

    assert response.status_code == 400
    assert response.json() == {"error": "card_name_mismatch"}


def test_register_requires_peer(tmp_path, monkeypatch):
    _seed_peer(tmp_path, _peer(peer_id="off", enabled=False))
    _patch_fetch(monkeypatch)

    with TestClient(_app(tmp_path)) as client:
        unknown = client.post(
            "/api/remote-agents",
            json=_register_body(peer_id="missing"),
            headers=AUTH,
        )
        disabled = client.post(
            "/api/remote-agents",
            json=_register_body(peer_id="off"),
            headers=AUTH,
        )

    for response in (unknown, disabled):
        assert response.status_code == 404
        assert response.json() == {"error": "peer_not_found"}


def test_register_tenant_mismatch(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    _patch_fetch(monkeypatch)

    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/remote-agents",
            json=_register_body(tenant="other"),
            headers=AUTH,
        )

    assert response.status_code == 400
    assert response.json() == {"error": "tenant_mismatch"}


def test_register_secret_unavailable(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    _patch_fetch(monkeypatch)

    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/remote-agents",
            json=_register_body(credential_ref="secret://crm/token"),
            headers=AUTH,
        )

    assert response.status_code == 503
    assert response.json() == {"error": "secret_unavailable"}


def test_register_fetch_error_codes(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    mapping = {
        "unreachable": "card_unreachable",
        "unauthorized": "card_unauthorized",
        "too_large": "card_too_large",
        "invalid_card": "card_invalid",
    }

    for reason, code in mapping.items():

        async def fake(url, credential=None, *, client=None, max_bytes=1048576, _reason=reason):
            raise RemoteAgentFetchError(_reason)

        monkeypatch.setattr("adk_agent.console.fetch_agent_card", fake)

        with TestClient(_app(tmp_path)) as client:
            response = client.post("/api/remote-agents", json=_register_body(), headers=AUTH)

        assert response.status_code == 502
        assert response.json() == {"error": code}


def test_refresh_changed(tmp_path, monkeypatch):
    _seed_remote(tmp_path, _record(card_digest=_digest("a")))
    _patch_fetch(monkeypatch, digest=_digest("b"))

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/remote-agents/crm-bot/refresh", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "changed"
    assert body["card_digest"] == _digest("a")
    assert body["observed_digest"] == _digest("b")


def test_refresh_unreachable(tmp_path, monkeypatch):
    _seed_remote(tmp_path, _record(card_digest=_digest("a")))

    async def fake(url, credential=None, *, client=None, max_bytes=1048576):
        raise RemoteAgentFetchError("unreachable")

    monkeypatch.setattr("adk_agent.console.fetch_agent_card", fake)

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/remote-agents/crm-bot/refresh", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unreachable"
    assert body["card_digest"] == _digest("a")
    assert body["observed_digest"] is None


def test_reregister_repins(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    _seed_remote(tmp_path, _record(card_digest=_digest("a"), enabled=False))
    _patch_fetch(monkeypatch, digest=_digest("b"))

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/remote-agents", json=_register_body(), headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pinned"
    assert body["card_digest"] == _digest("b")
    assert body["observed_digest"] is None
    assert body["enabled"] is False


def test_disable_idempotent(tmp_path):
    sink = ListAuditSink()
    _seed_remote(tmp_path)

    with TestClient(_app(tmp_path, audit=sink)) as client:
        first = client.post("/api/remote-agents/crm-bot/disable", headers=AUTH)
        second = client.post("/api/remote-agents/crm-bot/disable", headers=AUTH)
        missing = client.post("/api/remote-agents/missing/disable", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {"error": "remote_agent_not_found"}
    events = [event for event in sink.recent() if event.action == "remote_agent.disable"]
    assert len(events) == 1


def test_admin_only_and_tenant(tmp_path, monkeypatch):
    _seed_peer(tmp_path, _peer(peer_id="crm", tenant="acme"))
    _seed_peer(tmp_path, _peer(peer_id="local-p", tenant="local", subject="sub-l"))
    _seed_remote(tmp_path, _record(remote_id="crm-bot", tenant="acme", peer_id="crm"))
    _seed_remote(
        tmp_path,
        _record(remote_id="local-bot", tenant="local", peer_id="local-p"),
    )
    _patch_fetch(monkeypatch)

    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        registered = client.post(
            "/api/remote-agents",
            json=_register_body(tenant="local", peer_id="local-p"),
            headers=AUTH,
        )
        viewer_list = client.get("/api/remote-agents", headers=AUTH)
        cross_refresh = client.post("/api/remote-agents/crm-bot/refresh", headers=AUTH)

    assert registered.status_code == 403
    assert registered.json() == {"error": "forbidden"}
    assert [row["remote_id"] for row in viewer_list.json()] == ["local-bot"]
    assert cross_refresh.status_code == 403
    assert cross_refresh.json() == {"error": "tenant_forbidden"}

    with TestClient(_app(tmp_path)) as client:
        everything = client.get("/api/remote-agents", headers=AUTH)
        filtered = client.get("/api/remote-agents?tenant=acme", headers=AUTH)

    assert [row["remote_id"] for row in everything.json()] == ["crm-bot", "local-bot"]
    assert [row["remote_id"] for row in filtered.json()] == ["crm-bot"]


def test_not_configured(tmp_path):
    with TestClient(_app(tmp_path, peers=False, remote_agents=False)) as client:
        listed = client.get("/api/remote-agents", headers=AUTH)
        registered = client.post("/api/remote-agents", json=_register_body(), headers=AUTH)
        refreshed = client.post("/api/remote-agents/crm-bot/refresh", headers=AUTH)
        disabled = client.post("/api/remote-agents/crm-bot/disable", headers=AUTH)

    for response in (listed, registered, refreshed, disabled):
        assert response.status_code == 404
        assert response.json() == {"error": "remote_agents_not_configured"}


def test_reregister_tenant_immutable(tmp_path, monkeypatch):
    _seed_peer(tmp_path)
    _seed_remote(tmp_path, _record(tenant="other"))
    _patch_fetch(monkeypatch)

    with TestClient(_app(tmp_path)) as client:
        response = client.post("/api/remote-agents", json=_register_body(), headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {"error": "remote_agent_tenant_immutable"}
