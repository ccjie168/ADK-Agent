"""SLICE-091: console peer and peer grant management."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from google.adk.agents import LlmAgent

from adk_agent.audit import ListAuditSink
from adk_agent.console import build_console_app
from adk_agent.core import AgentRef, AuditEvent, PeerGrant, PeerIdentity, Principal
from adk_agent.registry import FilePeerGrantStore, FilePeerStore

AUTH = {"Authorization": "Bearer secret"}


def _identity(**overrides) -> PeerIdentity:
    data = {"peer_id": "peer-a", "tenant": "acme", "subject": "sub-a"}
    data.update(overrides)
    return PeerIdentity(**data)


def _grant(**overrides) -> PeerGrant:
    data = {
        "peer_id": "peer-a",
        "tenant": "acme",
        "agent_id": "bot",
        "actions": ["read", "invoke"],
    }
    data.update(overrides)
    return PeerGrant(**data)


def _app(tmp_path, *, roles=("admin",), peers=True, grants=True, audit=None):
    return build_console_app(
        {"probe": LlmAgent(name="probe", model="gemini-2.5-pro", instruction="x")},
        auth_token="secret",
        roles=roles,
        peers=FilePeerStore(tmp_path / "peer-state") if peers else None,
        peer_grants=FilePeerGrantStore(tmp_path / "peer-state") if grants else None,
        audit_sink=audit,
    )


def _seed(tmp_path, identity: PeerIdentity | None = None, grant: PeerGrant | None = None):
    asyncio.run(FilePeerStore(tmp_path / "peer-state").put(identity or _identity()))
    if grant is not None:
        asyncio.run(FilePeerGrantStore(tmp_path / "peer-state").put(grant))


def test_list_peers_with_grants(tmp_path):
    _seed(tmp_path, _identity(peer_id="peer-b", subject="sub-b"), _grant(peer_id="peer-b"))
    _seed(tmp_path, _identity(peer_id="peer-a"), _grant(peer_id="peer-a"))

    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/peers", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert [row["peer"]["peer_id"] for row in body] == ["peer-a", "peer-b"]
    assert body[0]["grants"] == [_grant().model_dump(mode="json")]
    assert body[1]["grants"] == [_grant(peer_id="peer-b").model_dump(mode="json")]


def test_tenant_visibility(tmp_path):
    _seed(tmp_path, _identity(peer_id="peer-a", tenant="acme", subject="sub-a"))
    _seed(tmp_path, _identity(peer_id="local-p", tenant="local", subject="sub-l"))

    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        scoped = client.get("/api/peers", headers=AUTH)
    with TestClient(_app(tmp_path)) as client:
        everything = client.get("/api/peers", headers=AUTH)
        filtered = client.get("/api/peers?tenant=acme", headers=AUTH)

    assert [row["peer"]["peer_id"] for row in scoped.json()] == ["local-p"]
    assert [row["peer"]["peer_id"] for row in everything.json()] == ["local-p", "peer-a"]
    assert [row["peer"]["peer_id"] for row in filtered.json()] == ["peer-a"]


def test_register_audited(tmp_path):
    sink = ListAuditSink()
    body = {"peer_id": "peer-a", "tenant": "acme", "subject": "sub-a"}

    with TestClient(_app(tmp_path, audit=sink)) as client:
        created = client.post("/api/peers", json=body, headers=AUTH)
        again = client.post("/api/peers", json=body, headers=AUTH)

    assert created.status_code == 200
    assert again.status_code == 200
    assert created.json() == _identity().model_dump(mode="json")
    events = [event for event in sink.recent() if event.action == "peer.register"]
    assert events
    assert all(event.target == "peer-a" for event in events)
    assert all(event.tenant == "local" for event in events)


def test_tenant_immutable(tmp_path):
    _seed(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/peers",
            json={"peer_id": "peer-a", "tenant": "other", "subject": "sub-a"},
            headers=AUTH,
        )

    assert response.status_code == 409
    assert response.json() == {"error": "peer_tenant_immutable"}


def test_disable_idempotent(tmp_path):
    sink = ListAuditSink()
    _seed(tmp_path)

    with TestClient(_app(tmp_path, audit=sink)) as client:
        first = client.post("/api/peers/peer-a/disable", headers=AUTH)
        second = client.post("/api/peers/peer-a/disable", headers=AUTH)
        missing = client.post("/api/peers/missing/disable", headers=AUTH)

    assert first.status_code == 200
    assert first.json()["enabled"] is False
    assert second.status_code == 200
    assert missing.status_code == 404
    assert missing.json() == {"error": "peer_not_found"}
    events = [event for event in sink.recent() if event.action == "peer.disable"]
    assert len(events) == 1
    assert events[0].target == "peer-a"


def test_grant_and_revoke(tmp_path):
    sink = ListAuditSink()
    _seed(tmp_path)

    with TestClient(_app(tmp_path, audit=sink)) as client:
        granted = client.post(
            "/api/peers/peer-a/grants",
            json={"agent_id": "bot", "actions": ["read", "invoke"]},
            headers=AUTH,
        )
        listed = client.get("/api/peers", headers=AUTH)
        revoked = client.delete("/api/peers/peer-a/grants/bot", headers=AUTH)
        missing = client.delete("/api/peers/peer-a/grants/bot", headers=AUTH)

    assert granted.status_code == 200
    assert granted.json() == _grant().model_dump(mode="json")
    assert listed.json()[0]["grants"] == [_grant().model_dump(mode="json")]
    assert revoked.status_code == 200
    assert revoked.json() == {"revoked": True}
    assert missing.status_code == 200
    assert missing.json() == {"revoked": False}
    grant_events = [event for event in sink.recent() if event.action == "peer.grant"]
    assert [event.target for event in grant_events] == ["peer-a/bot"]
    revoke_events = [event for event in sink.recent() if event.action == "peer.revoke"]
    assert [event.target for event in revoke_events] == ["peer-a/bot"]


def test_grant_tenant_follows_peer(tmp_path):
    _seed(tmp_path, _identity(tenant="acme"))

    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/api/peers/peer-a/grants",
            json={"agent_id": "bot", "actions": ["read"], "tenant": "other"},
            headers=AUTH,
        )

    assert response.status_code == 200
    assert response.json()["tenant"] == "acme"


def test_invalid_grant(tmp_path):
    _seed(tmp_path)

    with TestClient(_app(tmp_path)) as client:
        empty = client.post(
            "/api/peers/peer-a/grants",
            json={"agent_id": "bot", "actions": []},
            headers=AUTH,
        )
        unknown = client.post(
            "/api/peers/peer-a/grants",
            json={"agent_id": "bot", "actions": ["write"]},
            headers=AUTH,
        )
        no_agent = client.post(
            "/api/peers/peer-a/grants",
            json={"actions": ["read"]},
            headers=AUTH,
        )

    for response in (empty, unknown, no_agent):
        assert response.status_code == 400
        assert response.json() == {"error": "invalid_grant"}


def test_writes_require_admin(tmp_path):
    _seed(tmp_path)
    _seed(tmp_path, _identity(peer_id="local-p", tenant="local", subject="sub-l"))

    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        registered = client.post(
            "/api/peers",
            json={"peer_id": "peer-b", "tenant": "local", "subject": "sub-b"},
            headers=AUTH,
        )
        disabled = client.post("/api/peers/local-p/disable", headers=AUTH)
        granted = client.post(
            "/api/peers/local-p/grants",
            json={"agent_id": "bot", "actions": ["read"]},
            headers=AUTH,
        )

    assert registered.status_code == 403
    assert registered.json() == {"error": "forbidden"}
    assert disabled.status_code == 403
    assert granted.status_code == 403


def test_cross_tenant_forbidden(tmp_path):
    _seed(tmp_path, _identity(peer_id="foreign", tenant="acme"))

    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        disabled = client.post("/api/peers/foreign/disable", headers=AUTH)
        granted = client.post(
            "/api/peers/foreign/grants",
            json={"agent_id": "bot", "actions": ["read"]},
            headers=AUTH,
        )
        revoked = client.delete("/api/peers/foreign/grants/bot", headers=AUTH)

    assert disabled.status_code == 403
    assert disabled.json() == {"error": "tenant_forbidden"}
    assert granted.status_code == 403
    assert granted.json() == {"error": "tenant_forbidden"}
    assert revoked.status_code == 403
    assert revoked.json() == {"error": "tenant_forbidden"}


def test_not_configured(tmp_path):
    with TestClient(_app(tmp_path, peers=False, grants=False)) as client:
        listed = client.get("/api/peers", headers=AUTH)
        registered = client.post(
            "/api/peers",
            json={"peer_id": "peer-a", "tenant": "acme", "subject": "sub-a"},
            headers=AUTH,
        )
        disabled = client.post("/api/peers/peer-a/disable", headers=AUTH)
        granted = client.post(
            "/api/peers/peer-a/grants",
            json={"agent_id": "bot", "actions": ["read"]},
            headers=AUTH,
        )
        revoked = client.delete("/api/peers/peer-a/grants/bot", headers=AUTH)

    for response in (listed, registered, disabled, granted, revoked):
        assert response.status_code == 404
        assert response.json() == {"error": "peers_not_configured"}


def test_peer_call_in_audit_view(tmp_path):
    sink = ListAuditSink()
    asyncio.run(
        sink.emit(
            AuditEvent(
                event_id="event-1",
                run_id="run-1",
                trace_id="trace-1",
                tenant="local",
                principal=Principal(tenant="local", subject="peer-a", kind="service"),
                agent_ref=AgentRef(id="bot", version="1.0.0", digest="sha256:" + "0" * 64),
                action="peer.call",
                target="bot",
                status="denied",
                error_code="peer_denied",
                timestamp=datetime(2026, 11, 14, 9, 30, tzinfo=timezone.utc),
            )
        )
    )

    with TestClient(_app(tmp_path, audit=sink)) as client:
        response = client.get("/api/audit", headers=AUTH)

    assert response.status_code == 200
    assert [item["action"] for item in response.json()] == ["peer.call"]


def test_read_requires_capability(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, roles=["viewer"])) as client:
        response = client.get("/api/peers", headers=AUTH)

    assert response.status_code == 403
    assert response.json() == {"error": "forbidden"}


def test_operator_can_read_peers(tmp_path):
    _seed(tmp_path)
    with TestClient(_app(tmp_path, roles=["operator"])) as client:
        response = client.get("/api/peers", headers=AUTH)

    assert response.status_code == 200
