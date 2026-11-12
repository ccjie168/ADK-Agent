"""SLICE-040: the OIDC bearer middleware resolves principals per request."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from adk_agent.auth import OidcAuthMiddleware
from adk_agent.core import Principal
from adk_agent.identity import IdentityUnavailable, InvalidIdentity

ALICE = Principal(tenant="acme", subject="alice", kind="human")


class _FakeProvider:
    def __init__(self, principals: dict[str, Principal]) -> None:
        self._principals = principals

    async def resolve(self, credential: str) -> Principal:
        principal = self._principals.get(credential)
        if principal is None:
            raise InvalidIdentity("invalid token")
        return principal


class _DownProvider:
    async def resolve(self, credential: str) -> Principal:
        raise IdentityUnavailable("issuer unreachable")


def _app(provider) -> FastAPI:
    app = FastAPI()
    app.add_middleware(OidcAuthMiddleware, provider=provider, open_paths=frozenset({"/healthz"}))

    @app.get("/who")
    async def who(request: Request) -> dict[str, str]:
        return {"subject": request.state.principal.subject}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_valid_token_sets_request_principal():
    with TestClient(_app(_FakeProvider({"alice-token": ALICE}))) as client:
        response = client.get("/who", headers={"Authorization": "Bearer alice-token"})

    assert response.status_code == 200
    assert response.json() == {"subject": "alice"}


def test_missing_header_is_401():
    with TestClient(_app(_FakeProvider({"alice-token": ALICE}))) as client:
        response = client.get("/who")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_401():
    with TestClient(_app(_FakeProvider({"alice-token": ALICE}))) as client:
        response = client.get("/who", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_provider_unavailable_is_503():
    with TestClient(_app(_DownProvider())) as client:
        response = client.get("/who", headers={"Authorization": "Bearer alice-token"})

    assert response.status_code == 503
    assert response.json() == {"error": "identity_unavailable"}


def test_open_path_skips_auth():
    with TestClient(_app(_DownProvider())) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
