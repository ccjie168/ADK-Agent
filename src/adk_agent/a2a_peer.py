"""Per-peer identity and per-agent action authorization for A2A (ADR-0014).

The middlewares run inside the trace middleware and outside rate limiting, so
identity is resolved before authorization, which is resolved before throttling.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .audit.hashing import hash_text
from .core import AgentRef, AuditEvent, AuditSink, PeerStoreError, Principal
from .identity.peer_tokens import match_peer

_current_principal: ContextVar[Principal | None] = ContextVar("a2a_peer_principal", default=None)

_ACTION_BY_METHOD = {
    "message/send": "invoke",
    "message/stream": "invoke",
    "tasks/cancel": "invoke",
    "tasks/get": "read",
    "tasks/resubscribe": "read",
}


def current_peer_principal() -> Principal | None:
    return _current_principal.get()


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _forbidden() -> JSONResponse:
    return JSONResponse({"error": "forbidden"}, status_code=403)


def _store_unavailable() -> JSONResponse:
    return JSONResponse({"error": "peer_store_unavailable"}, status_code=503)


def _dev_ref(agent_id: str) -> AgentRef:
    digest = hashlib.sha256(agent_id.encode("utf-8")).hexdigest()
    return AgentRef(id=agent_id, version="dev", digest=f"sha256:{digest}")


class PeerTokenMiddleware(BaseHTTPMiddleware):
    """Hash-match a presented bearer token and install the peer principal."""

    def __init__(self, app: ASGIApp, peers: Any, tokens: dict[str, str]) -> None:
        super().__init__(app)
        self.peers = peers
        self.tokens = tokens

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        header = request.headers.get("authorization", "")
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return _unauthorized()
        peer_id = match_peer(self.tokens, parts[1])
        if peer_id is None:
            return _unauthorized()
        try:
            peer = await self.peers.get(peer_id)
        except PeerStoreError:
            return _store_unavailable()
        if peer is None or not peer.enabled:
            return _forbidden()
        principal = Principal(
            tenant=peer.tenant, subject=peer.peer_id, kind=peer.kind, roles=peer.roles
        )
        request.state.principal = principal
        token = _current_principal.set(principal)
        try:
            return await call_next(request)
        finally:
            _current_principal.reset(token)


class PeerIdentityMiddleware(BaseHTTPMiddleware):
    """Map an OIDC subject to a peer and install the peer principal."""

    def __init__(self, app: ASGIApp, peers: Any) -> None:
        super().__init__(app)
        self.peers = peers

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return _unauthorized()
        try:
            peer = await self.peers.get_by_subject(principal.subject)
        except PeerStoreError:
            return _store_unavailable()
        if peer is None or not peer.enabled:
            return _forbidden()
        if principal.tenant != peer.tenant:
            return _forbidden()
        peer_principal = Principal(
            tenant=peer.tenant, subject=peer.peer_id, kind=peer.kind, roles=peer.roles
        )
        request.state.principal = peer_principal
        token = _current_principal.set(peer_principal)
        try:
            return await call_next(request)
        finally:
            _current_principal.reset(token)


class PeerAuthzMiddleware:
    """Map a request to ``read`` or ``invoke`` and enforce the peer's grant."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        agent_id: str,
        grants: Any,
        audit: AuditSink | None,
        max_body_bytes: int = 1_048_576,
        trace_id: Callable[[], str | None] | None = None,
    ) -> None:
        self.app = app
        self.agent_id = agent_id
        self.grants = grants
        self.audit = audit
        self.max_body_bytes = max_body_bytes
        self._trace_id = trace_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        principal = (scope.get("state") or {}).get("principal")
        if principal is None:
            await self._respond(scope, receive, send, _unauthorized())
            return

        method = scope["method"].upper()
        action: str | None
        label: str
        rpc_id: Any
        body: bytes
        if method == "GET":
            action, label, rpc_id, body = "read", "card", None, b""
        elif method == "POST":
            body, oversized = await _read_body(receive, self.max_body_bytes)
            if oversized:
                await self._respond(
                    scope,
                    receive,
                    send,
                    JSONResponse({"error": "request_too_large"}, status_code=413),
                )
                return
            method_name, rpc_id = _parse_rpc(body)
            action = _ACTION_BY_METHOD.get(method_name) if method_name else None
            label = method_name or ""
            if action is None:
                await self._deny(scope, receive, send, principal, label, rpc_id, get=False)
                return
        else:
            await self._respond(scope, receive, send, _forbidden())
            return

        try:
            grant = await self.grants.get(principal.subject, self.agent_id)
        except PeerStoreError:
            await self._respond(scope, receive, send, _store_unavailable())
            return

        allowed = grant is not None and grant.tenant == principal.tenant and action in grant.actions
        if not allowed:
            await self._deny(scope, receive, send, principal, label, rpc_id, get=(method == "GET"))
            return

        if method == "POST":
            await self._forward(scope, receive, send, body)
        else:
            await self.app(scope, receive, send)

    async def _deny(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        principal: Principal,
        label: str,
        rpc_id: Any,
        *,
        get: bool,
    ) -> None:
        if get:
            response = JSONResponse({"error": "not_found"}, status_code=404)
        else:
            response = JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32001, "message": "forbidden"}},
                status_code=403,
            )
        await self._audit_denial(principal, label)
        await self._respond(scope, receive, send, response)

    async def _audit_denial(self, principal: Principal, label: str) -> None:
        if self.audit is None:
            return
        trace_id = (self._trace_id() if self._trace_id is not None else None) or uuid.uuid4().hex
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=uuid.uuid4().hex,
            trace_id=trace_id,
            tenant=principal.tenant,
            principal=principal,
            agent_ref=_dev_ref(self.agent_id),
            action="peer.call",
            target=self.agent_id,
            args_hash=hash_text(label),
            result_hash=None,
            data_classes=[],
            egress="none",
            status="denied",
            error_code=None,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)

    async def _forward(self, scope: Scope, receive: Receive, send: Send, body: bytes) -> None:
        sent = False

        async def replay() -> Any:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _respond(scope: Scope, receive: Receive, send: Send, response: Response) -> None:
        await response(scope, receive, send)


async def _read_body(receive: Receive, cap: int) -> tuple[bytes, bool]:
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            return bytes(body), False
        if message["type"] != "http.request":
            continue
        body.extend(message.get("body", b""))
        if len(body) > cap:
            return bytes(body), True
        if not message.get("more_body", False):
            return bytes(body), False


def _parse_rpc(body: bytes) -> tuple[str | None, Any]:
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    method = payload.get("method")
    rpc_id = payload.get("id")
    if not isinstance(method, str) or not method:
        return None, None
    return method, rpc_id


__all__ = [
    "PeerAuthzMiddleware",
    "PeerIdentityMiddleware",
    "PeerTokenMiddleware",
    "current_peer_principal",
]
