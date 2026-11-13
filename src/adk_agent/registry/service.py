"""Registry control-plane service: publish, read and upload artifacts (ADR-0009)."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from ..core import (
    AgentRegistry,
    ArtifactStore,
    IdentityProvider,
    Principal,
    PublishedAgent,
    manifest_digest,
)
from ..core.artifact import MAX_ARTIFACT_BYTES, MEDIA_TYPE
from ..ratelimit import FixedWindowLimiter, RateLimit, RateLimitMiddleware
from .artifacts import ArtifactStoreError
from .file import RegistryConflict, RegistryError, RegistryIntegrityError
from .signing import PublishUnavailable
from .trust import ArtifactTrustError, TrustStore

logger = logging.getLogger(__name__)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _error(code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status)


def _principal(request: Request) -> Principal | None:
    return getattr(request.state, "principal", None)


def _cross_tenant(principal: Principal | None, tenant: str) -> bool:
    return principal is not None and tenant != principal.tenant and "admin" not in principal.roles


async def _visible_tenants(registry: AgentRegistry, principal: Principal | None) -> list[str]:
    if principal is not None and "admin" not in principal.roles:
        return [principal.tenant]
    return sorted(await registry.tenants())


async def _collect(registry: AgentRegistry, tenants: list[str]) -> list[PublishedAgent]:
    records: list[PublishedAgent] = []
    for tenant in tenants:
        records.extend(await registry.list(tenant))
    return records


def _read_error(exc: RegistryError) -> JSONResponse:
    if isinstance(exc, RegistryIntegrityError):
        return _error("registry_integrity_error", 502)
    return _error("registry_unavailable", 502)


def build_registry_service_app(
    registry: AgentRegistry,
    *,
    artifact_store: ArtifactStore | None = None,
    trust: TrustStore | None = None,
    host: str = "127.0.0.1",
    auth_token: str | None = None,
    allow_unauthenticated: bool = False,
    oidc: IdentityProvider | None = None,
    rate_limit: RateLimit | None = None,
) -> FastAPI:
    """Build the registry control plane. Every path except /healthz needs credentials."""
    token = resolve_http_auth(host, auth_token, allow_unauthenticated) if oidc is None else None
    app = FastAPI(title="ADK Agent Registry", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/tenants")
    async def tenants(request: Request) -> JSONResponse:
        try:
            names = await _visible_tenants(registry, _principal(request))
        except RegistryError as exc:
            return _read_error(exc)
        return JSONResponse({"tenants": names})

    @app.get("/v1/agents")
    async def list_agents(request: Request, tenant: str | None = None) -> JSONResponse:
        principal = _principal(request)
        if tenant is not None and _cross_tenant(principal, tenant):
            return _error("tenant_forbidden", 403)
        try:
            names = [tenant] if tenant is not None else await _visible_tenants(registry, principal)
            records = await _collect(registry, names)
        except RegistryError as exc:
            return _read_error(exc)
        records.sort(
            key=lambda record: (record.manifest.tenant, record.manifest.id, record.manifest.version)
        )
        return JSONResponse(
            {
                "agents": [record.model_dump(mode="json") for record in records],
                "count": len(records),
            }
        )

    @app.get("/v1/agents/{tenant}/{agent_id}/{version}")
    async def get_agent(request: Request, tenant: str, agent_id: str, version: str) -> JSONResponse:
        if _cross_tenant(_principal(request), tenant):
            return _error("tenant_forbidden", 403)
        try:
            records = await registry.list(tenant)
        except RegistryError as exc:
            return _read_error(exc)
        for record in records:
            if record.manifest.id == agent_id and record.manifest.version == version:
                return JSONResponse(record.model_dump(mode="json"))
        return _error("not_found", 404)

    @app.post("/v1/agents")
    async def publish(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return _error("invalid_json", 400)
        try:
            record = PublishedAgent.model_validate(body)
        except ValidationError:
            return _error("invalid_record", 400)
        if manifest_digest(record.manifest) != record.digest:
            return _error("invalid_record", 400)
        if _cross_tenant(_principal(request), record.manifest.tenant):
            return _error("tenant_forbidden", 403)

        artifact = record.artifact
        if artifact is not None:
            if trust is None:
                return _error("artifact_trust_unavailable", 503)
            if artifact.signature is None or artifact.key_id is None:
                return _error("artifact_untrusted", 400)
            try:
                trust.verify(artifact)
            except ArtifactTrustError:
                return _error("artifact_untrusted", 400)
            except PublishUnavailable:
                return _error("artifact_trust_unavailable", 503)
            if artifact_store is None:
                return _error("artifact_store_unavailable", 503)

        try:
            stored = await registry.publish(record)
        except RegistryConflict:
            return _error("version_conflict", 409)
        except RegistryIntegrityError:
            return _error("registry_integrity_error", 502)
        except RegistryError:
            return _error("registry_unavailable", 502)
        except Exception:  # noqa: BLE001
            logger.exception("registry publish failure")
            return _error("registry_unavailable", 502)
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)

    @app.put("/v1/artifacts/{digest}")
    async def upload_artifact(request: Request, digest: str) -> JSONResponse:
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != MEDIA_TYPE:
            return _error("unsupported_media_type", 415)

        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_ARTIFACT_BYTES:
                    return _error("too_large", 413)
            except ValueError:
                pass
        data = await request.body()
        if len(data) > MAX_ARTIFACT_BYTES:
            return _error("too_large", 413)

        if _DIGEST.fullmatch(digest) is None:
            return _error("invalid_digest", 400)

        principal = _principal(request)
        try:
            names = [principal.tenant] if principal is not None else await registry.tenants()
            record = await _record_for_digest(registry, names, digest)
        except RegistryError as exc:
            return _read_error(exc)
        if record is None or record.artifact is None:
            return _error("artifact_not_published", 409)
        artifact = record.artifact

        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        if actual != digest:
            return _error("digest_mismatch", 400)
        if len(data) != artifact.size:
            return _error("size_mismatch", 400)

        if trust is None:
            return _error("artifact_trust_unavailable", 503)
        try:
            trust.verify(artifact)
        except ArtifactTrustError:
            return _error("artifact_untrusted", 409)
        except PublishUnavailable:
            return _error("artifact_trust_unavailable", 503)

        if artifact_store is None:
            return _error("artifact_store_unavailable", 503)
        try:
            await artifact_store.put(artifact, data)
        except ArtifactStoreError:
            return _error("artifact_store_failed", 502)
        return JSONResponse({"digest": digest, "size": len(data)}, status_code=201)

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=FixedWindowLimiter(rate_limit.limit, rate_limit.window_seconds),
            surface="registry",
        )
    if oidc is not None:
        app.add_middleware(OidcAuthMiddleware, provider=oidc, open_paths=frozenset({"/healthz"}))
    elif token:
        app.add_middleware(BearerAuthMiddleware, token=token, open_paths=frozenset({"/healthz"}))
    return app


async def _record_for_digest(
    registry: AgentRegistry, tenants: list[str], digest: str
) -> PublishedAgent | None:
    for tenant in tenants:
        for record in await registry.list(tenant):
            if record.artifact is not None and record.artifact.digest == digest:
                return record
    return None


__all__ = ["build_registry_service_app"]
