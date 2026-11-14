"""SLICE-090: per-peer identity, authorization and audit for A2A."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from adk_agent.a2a_peer import (
    PeerAuthzMiddleware,
    PeerIdentityMiddleware,
    PeerTokenMiddleware,
)
from adk_agent.audit import ListAuditSink
from adk_agent.audit.hashing import hash_text
from adk_agent.auth import OidcAuthMiddleware
from adk_agent.core import PeerGrant, PeerIdentity, Principal
from adk_agent.identity.peer_tokens import load_peer_tokens, match_peer
from adk_agent.runtime.audit_proxy import AuditedRunner

PEER = PeerIdentity(peer_id="peer-a", tenant="acme", subject="sub-1", kind="service", roles=["a2a"])

READ = PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["read"])
INVOKE = PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["invoke"])
BOTH = PeerGrant(peer_id="peer-a", tenant="acme", agent_id="bot", actions=["read", "invoke"])

AUTH = {"Authorization": "Bearer tok-a"}


class MemPeers:
    def __init__(self, *identities: PeerIdentity) -> None:
        self._by_id = {peer.peer_id: peer for peer in identities}
        self._by_subject = {peer.subject: peer for peer in identities}

    async def get(self, peer_id: str) -> PeerIdentity | None:
        return self._by_id.get(peer_id)

    async def get_by_subject(self, subject: str) -> PeerIdentity | None:
        return self._by_subject.get(subject)

    async def list(self) -> list[PeerIdentity]:
        return list(self._by_id.values())

    async def put(self, identity: PeerIdentity) -> PeerIdentity:
        self._by_id[identity.peer_id] = identity
        return identity


class MemGrants:
    def __init__(self, *grants: PeerGrant) -> None:
        self._grants = {(grant.peer_id, grant.agent_id): grant for grant in grants}

    async def get(self, peer_id: str, agent_id: str) -> PeerGrant | None:
        return self._grants.get((peer_id, agent_id))

    async def list(self) -> list[PeerGrant]:
        return list(self._grants.values())

    async def put(self, grant: PeerGrant) -> PeerGrant:
        self._grants[(grant.peer_id, grant.agent_id)] = grant
        return grant


class FakeProvider:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def resolve(self, credential: str) -> Principal:
        return self.principal


def _tokens(mapping: dict[str, str]) -> dict[str, str]:
    return {
        peer_id: hashlib.sha256(token.encode()).hexdigest() for peer_id, token in mapping.items()
    }


async def _card(request: Request) -> JSONResponse:
    return JSONResponse({"name": "bot"})


async def _rpc(request: Request) -> JSONResponse:
    return JSONResponse({"result": "ok"})


def _inner_app() -> Starlette:
    return Starlette(
        routes=[
            Route("/.well-known/agent-card.json", _card, methods=["GET"]),
            Route("/", _rpc, methods=["POST"]),
        ]
    )


def _token_app(peers, grants, *, tokens, audit=None, max_body_bytes: int = 1_048_576) -> Starlette:
    app = _inner_app()
    app.add_middleware(
        PeerAuthzMiddleware,
        agent_id="bot",
        grants=grants,
        audit=audit,
        max_body_bytes=max_body_bytes,
    )
    app.add_middleware(PeerTokenMiddleware, peers=peers, tokens=tokens)
    return app


def _oidc_app(peers, grants, *, principal, audit=None) -> Starlette:
    app = _inner_app()
    app.add_middleware(PeerAuthzMiddleware, agent_id="bot", grants=grants, audit=audit)
    app.add_middleware(PeerIdentityMiddleware, peers=peers)
    app.add_middleware(OidcAuthMiddleware, provider=FakeProvider(principal), open_paths=frozenset())
    return app


def test_token_file(tmp_path):
    digest = hashlib.sha256(b"tok-a").hexdigest()
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"peer-a": digest.upper()}), encoding="utf-8")

    tokens = load_peer_tokens(str(path))

    assert tokens == {"peer-a": digest}
    assert match_peer(tokens, "tok-a") == "peer-a"
    assert match_peer(tokens, "wrong") is None


def test_token_file_rejects_bad_shapes(tmp_path):
    short = tmp_path / "short.json"
    short.write_text(json.dumps({"peer-a": "abc"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_peer_tokens(str(short))

    not_object = tmp_path / "list.json"
    not_object.write_text(json.dumps(["peer-a"]), encoding="utf-8")
    with pytest.raises(ValueError):
        load_peer_tokens(str(not_object))


def test_unknown_token_unauthorized():
    app = _token_app(MemPeers(PEER), MemGrants(BOTH), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        response = client.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send"})

    assert response.status_code == 401


def test_subject_mapping():
    principal = Principal(tenant="acme", subject="sub-1", kind="human", roles=[])
    app = _oidc_app(MemPeers(PEER), MemGrants(BOTH), principal=principal)

    with TestClient(app) as client:
        response = client.post(
            "/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send"}, headers=AUTH
        )

    assert response.status_code == 200


def test_tenant_mismatch_rejected():
    principal = Principal(tenant="other", subject="sub-1", kind="human", roles=[])
    app = _oidc_app(MemPeers(PEER), MemGrants(BOTH), principal=principal)

    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json", headers=AUTH)

    assert response.status_code == 403


def test_disabled_peer():
    disabled = PEER.model_copy(update={"enabled": False})
    app = _token_app(MemPeers(disabled), MemGrants(BOTH), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json", headers=AUTH)

    assert response.status_code == 403


def test_invoke_denied():
    app = _token_app(MemPeers(PEER), MemGrants(READ), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        response = client.post(
            "/", json={"jsonrpc": "2.0", "id": "7", "method": "message/send"}, headers=AUTH
        )

    assert response.status_code == 403
    assert response.json()["id"] == "7"
    assert response.json()["error"] == {"code": -32001, "message": "forbidden"}


def test_action_mapping():
    app = _token_app(MemPeers(PEER), MemGrants(BOTH), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        send = client.post(
            "/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send"}, headers=AUTH
        )
        stream = client.post(
            "/", json={"jsonrpc": "2.0", "id": "2", "method": "message/stream"}, headers=AUTH
        )
        cancel = client.post(
            "/", json={"jsonrpc": "2.0", "id": "3", "method": "tasks/cancel"}, headers=AUTH
        )
        get = client.post(
            "/", json={"jsonrpc": "2.0", "id": "4", "method": "tasks/get"}, headers=AUTH
        )
        resubscribe = client.post(
            "/", json={"jsonrpc": "2.0", "id": "5", "method": "tasks/resubscribe"}, headers=AUTH
        )

    assert send.status_code == 200
    assert stream.status_code == 200
    assert cancel.status_code == 200
    assert get.status_code == 200
    assert resubscribe.status_code == 200


def test_unknown_method_denied():
    app = _token_app(MemPeers(PEER), MemGrants(BOTH), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        response = client.post(
            "/", json={"jsonrpc": "2.0", "id": "6", "method": "bogus/method"}, headers=AUTH
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == -32001


def test_card_hidden():
    app = _token_app(MemPeers(PEER), MemGrants(INVOKE), tokens=_tokens({"peer-a": "tok-a"}))

    with TestClient(app) as client:
        response = client.get("/.well-known/agent-card.json", headers=AUTH)

    assert response.status_code == 404


def test_body_too_large():
    app = _token_app(
        MemPeers(PEER),
        MemGrants(BOTH),
        tokens=_tokens({"peer-a": "tok-a"}),
        max_body_bytes=16,
    )

    with TestClient(app) as client:
        response = client.post(
            "/",
            content=b"x" * 100,
            headers={**AUTH, "content-type": "application/json"},
        )

    assert response.status_code == 413


def test_denial_audited():
    sink = ListAuditSink()
    app = _token_app(
        MemPeers(PEER),
        MemGrants(READ),
        tokens=_tokens({"peer-a": "tok-a"}),
        audit=sink,
    )

    with TestClient(app) as client:
        response = client.post(
            "/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send"}, headers=AUTH
        )

    assert response.status_code == 403
    [event] = sink.recent(10)
    assert event.action == "peer.call"
    assert event.status == "denied"
    assert event.target == "bot"
    assert event.tenant == "acme"
    assert event.principal.subject == "peer-a"
    assert event.args_hash == hash_text("message/send")


class _Part:
    thought = False

    def __init__(self, text: str) -> None:
        self.text = text


class _Content:
    def __init__(self, text: str) -> None:
        self.parts = [_Part(text)]


class _Event:
    def __init__(self, text: str) -> None:
        self.content = _Content(text)

    def is_final_response(self) -> bool:
        return True


class _FakeRunner:
    async def run_async(self, **kwargs):
        yield _Event("hello")


def test_run_audited_as_peer():
    sink = ListAuditSink()
    principal = Principal(tenant="acme", subject="peer-a", kind="service", roles=[])
    proxy = AuditedRunner(
        _FakeRunner(),
        agent_name="bot",
        principal=lambda: principal,
        audit=sink,
        quota=None,
        quota_policy=None,
    )

    async def drain() -> None:
        async for _ in proxy.run_async(new_message=None):
            pass

    asyncio.run(drain())

    [event] = sink.recent(10)
    assert event.action == "agent.run"
    assert event.tenant == "acme"
    assert event.principal.subject == "peer-a"
