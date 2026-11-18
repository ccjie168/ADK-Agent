"""Registry control-plane service: publish, read and upload artifacts (ADR-0009)."""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..audit.hashing import hash_text
from ..auth import BearerAuthMiddleware, OidcAuthMiddleware, resolve_http_auth
from ..core import (
    AgentLifecycle,
    AgentLifecycleStore,
    AgentRef,
    AgentRegistry,
    ArtifactStore,
    AuditEvent,
    AuditSink,
    ConnectorConflict,
    ConnectorNotFound,
    ConnectorSpec,
    ConnectorStore,
    ConnectorStoreError,
    ConnectorStoreUnavailable,
    CredentialBinding,
    CredentialConflict,
    CredentialNotFound,
    CredentialStore,
    CredentialStoreError,
    EvalReport,
    EvalReportStore,
    IdentityProvider,
    LifecycleStatus,
    LifecycleTransitionError,
    Principal,
    PublishedAgent,
    credential_version,
    declared_execution_tier,
    manifest_digest,
)
from ..core.artifact import MAX_ARTIFACT_BYTES, MEDIA_TYPE
from ..ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from ..sandbox.agent import agent_sandbox_available
from ..secretstore import KeyBackend, KeyBackendError, credential_aad
from .artifacts import ArtifactStoreError
from .file import RegistryConflict, RegistryError, RegistryIntegrityError
from .reports import EvalReportConflict
from .signing import PublishUnavailable
from .trust import ArtifactTrustError, TrustStore

logger = logging.getLogger(__name__)

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

_LIFECYCLE_STATUSES = frozenset({"published", "deprecated", "retired"})


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


async def _lifecycle_state(
    store: AgentLifecycleStore | None, record: PublishedAgent
) -> AgentLifecycle:
    if store is None:
        return AgentLifecycle.default()
    return await store.get(record.manifest.tenant, record.manifest.id, record.manifest.version)


def _with_lifecycle(record: PublishedAgent, state: AgentLifecycle) -> dict[str, Any]:
    payload = record.model_dump(mode="json")
    payload["lifecycle"] = state.model_dump(mode="json")
    return payload


def _read_error(exc: RegistryError) -> JSONResponse:
    if isinstance(exc, RegistryIntegrityError):
        return _error("registry_integrity_error", 502)
    return _error("registry_unavailable", 502)


def _connector_spec_error(exc: ConnectorStoreError) -> JSONResponse:
    if isinstance(exc, ConnectorConflict):
        return _error("connector_conflict", 409)
    if isinstance(exc, ConnectorNotFound):
        return _error("connector_not_found", 404)
    if isinstance(exc, ConnectorStoreUnavailable):
        return _error("connector_store_failed", 502)
    return _error("connector_store_failed", 502)


def _connector_visible(principal: Principal | None, tenant: str | None) -> bool:
    return (
        tenant is None
        or principal is None
        or "admin" in principal.roles
        or tenant == principal.tenant
    )


def _connector_actor(principal: Principal | None, tenant: str | None) -> Principal:
    return principal or Principal(
        tenant=tenant or "global", subject="registry_operator", kind="human", roles=["admin"]
    )


def _connector_ref(spec: ConnectorSpec) -> AgentRef:
    return AgentRef(
        id=spec.connector_id,
        version="connector",
        digest=f"sha256:{hash_text(spec.model_dump_json())}",
    )


def build_registry_service_app(
    registry: AgentRegistry,
    *,
    artifact_store: ArtifactStore | None = None,
    eval_reports: EvalReportStore | None = None,
    lifecycle: AgentLifecycleStore | None = None,
    connectors: ConnectorStore | None = None,
    credentials: CredentialStore | None = None,
    key_backend: KeyBackend | None = None,
    audit: AuditSink | None = None,
    trust: TrustStore | None = None,
    builder_keys: TrustStore | None = None,
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
        try:
            agents = [
                _with_lifecycle(record, await _lifecycle_state(lifecycle, record))
                for record in records
            ]
        except Exception:  # noqa: BLE001
            logger.exception("lifecycle read failure")
            return _error("lifecycle_store_unavailable", 503)
        return JSONResponse({"agents": agents, "count": len(agents)})

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
                try:
                    state = await _lifecycle_state(lifecycle, record)
                except Exception:  # noqa: BLE001
                    logger.exception("lifecycle read failure")
                    return _error("lifecycle_store_unavailable", 503)
                return JSONResponse(_with_lifecycle(record, state))
        return _error("not_found", 404)

    @app.get("/v1/agents/{tenant}/{agent_id}/{version}/lifecycle")
    async def get_lifecycle(
        request: Request, tenant: str, agent_id: str, version: str
    ) -> JSONResponse:
        if _cross_tenant(_principal(request), tenant):
            return _error("tenant_forbidden", 403)
        if lifecycle is None:
            return _error("lifecycle_store_unavailable", 503)
        try:
            state = await lifecycle.get(tenant, agent_id, version)
        except Exception:  # noqa: BLE001
            logger.exception("lifecycle read failure")
            return _error("lifecycle_store_unavailable", 503)
        return JSONResponse(state.model_dump(mode="json"))

    @app.put("/v1/agents/{tenant}/{agent_id}/{version}/lifecycle")
    async def put_lifecycle(
        request: Request, tenant: str, agent_id: str, version: str
    ) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return _error("invalid_request", 400)
        if not isinstance(body, dict):
            return _error("invalid_request", 400)
        raw_status = body.get("status")
        if not isinstance(raw_status, str) or raw_status not in _LIFECYCLE_STATUSES:
            return _error("invalid_status", 400)
        status = cast(LifecycleStatus, raw_status)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            return _error("invalid_request", 400)

        principal = _principal(request)
        if _cross_tenant(principal, tenant):
            return _error("tenant_forbidden", 403)
        if principal is not None and "admin" not in principal.roles:
            return _error("forbidden", 403)

        try:
            records = await registry.list(tenant)
        except RegistryError as exc:
            return _read_error(exc)
        except Exception:  # noqa: BLE001
            logger.exception("registry list failure")
            return _error("registry_unavailable", 502)
        record = next(
            (
                candidate
                for candidate in records
                if candidate.manifest.id == agent_id and candidate.manifest.version == version
            ),
            None,
        )
        if record is None:
            return _error("not_found", 404)
        if lifecycle is None:
            return _error("lifecycle_store_unavailable", 503)

        actor = principal or Principal(
            tenant=tenant, subject="registry_operator", kind="human", roles=["admin"]
        )
        try:
            previous = await lifecycle.get(tenant, agent_id, version)
            changed = await lifecycle.set(
                tenant,
                agent_id,
                version,
                status=status,
                changed_by=actor.subject,
                reason=reason,
            )
        except LifecycleTransitionError:
            return _error("invalid_transition", 409)
        except Exception:  # noqa: BLE001
            logger.exception("lifecycle write failure")
            return _error("lifecycle_store_unavailable", 503)

        if audit is not None and changed.status != previous.status:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=actor.tenant,
                    principal=actor,
                    agent_ref=AgentRef(id=agent_id, version=version, digest=record.digest),
                    action="agent.lifecycle",
                    target=f"{tenant}/{agent_id}@{version}",
                    args_hash=hash_text(f"{previous.status}->{changed.status}"),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(changed.model_dump(mode="json"))

    @app.get("/v1/connectors")
    async def list_connectors(request: Request, tenant: str | None = None) -> JSONResponse:
        if connectors is None:
            return _error("connector_store_unavailable", 503)
        caller = _principal(request)
        if tenant is not None and _cross_tenant(caller, tenant):
            return _error("tenant_forbidden", 403)
        try:
            if tenant is not None:
                records = await connectors.list(tenant)
            elif caller is None or "admin" in caller.roles:
                records = await connectors.list_all()
            else:
                records = await connectors.list(caller.tenant)
        except ConnectorStoreError as exc:
            return _connector_spec_error(exc)
        records.sort(key=lambda spec: spec.connector_id)
        return JSONResponse(
            {
                "connectors": [spec.model_dump(mode="json") for spec in records],
                "count": len(records),
            }
        )

    @app.get("/v1/connectors/{connector_id}")
    async def get_connector(request: Request, connector_id: str) -> JSONResponse:
        if connectors is None:
            return _error("connector_store_unavailable", 503)
        try:
            spec = await connectors.get(connector_id)
        except ConnectorStoreError as exc:
            return _connector_spec_error(exc)
        if spec is None:
            return _error("connector_not_found", 404)
        if not _connector_visible(_principal(request), spec.tenant):
            return _error("tenant_forbidden", 403)
        return JSONResponse(spec.model_dump(mode="json"))

    @app.post("/v1/connectors")
    async def register_connector(request: Request) -> JSONResponse:
        caller = _principal(request)
        if caller is not None and "admin" not in caller.roles:
            return _error("forbidden", 403)
        if connectors is None:
            return _error("connector_store_unavailable", 503)
        try:
            body = await request.json()
        except ValueError:
            return _error("invalid_json", 400)
        if not isinstance(body, dict):
            return _error("invalid_json", 400)
        try:
            spec = ConnectorSpec.model_validate(body)
        except ValidationError:
            return _error("invalid_connector", 400)
        try:
            stored = await connectors.add(spec)
        except ConnectorStoreError as exc:
            return _connector_spec_error(exc)
        if audit is not None:
            actor = _connector_actor(caller, spec.tenant)
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=actor.tenant,
                    principal=actor,
                    agent_ref=_connector_ref(spec),
                    action="connector.register",
                    target=f"{spec.tenant or 'global'}/{spec.connector_id}",
                    args_hash=hash_text(stored.model_dump_json()),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)

    @app.post("/v1/connectors/{connector_id}/disable")
    async def disable_connector(request: Request, connector_id: str) -> JSONResponse:
        caller = _principal(request)
        if caller is not None and "admin" not in caller.roles:
            return _error("forbidden", 403)
        if connectors is None:
            return _error("connector_store_unavailable", 503)
        try:
            existing = await connectors.get(connector_id)
        except ConnectorStoreError as exc:
            return _connector_spec_error(exc)
        if existing is None:
            return _error("connector_not_found", 404)
        if not _connector_visible(caller, existing.tenant):
            return _error("tenant_forbidden", 403)
        actor = _connector_actor(caller, existing.tenant)
        try:
            disabled = await connectors.disable(connector_id, by=actor.subject)
        except ConnectorStoreError as exc:
            return _connector_spec_error(exc)
        if audit is not None and existing.enabled:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=actor.tenant,
                    principal=actor,
                    agent_ref=_connector_ref(existing),
                    action="connector.disable",
                    target=f"{existing.tenant or 'global'}/{connector_id}",
                    args_hash=hash_text("enabled->disabled"),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(disabled.model_dump(mode="json"))

    def _credential_ref(binding: CredentialBinding, version: str) -> AgentRef:
        payload = binding.model_dump_json(exclude={"wrapped_secret"})
        return AgentRef(
            id=binding.credential_id, version=version, digest=f"sha256:{hash_text(payload)}"
        )

    @app.post("/v1/credentials")
    async def register_credential(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return _error("invalid_request", 400)
        if not isinstance(body, dict):
            return _error("invalid_request", 400)
        caller = _principal(request)
        if caller is not None and "admin" not in caller.roles:
            return _error("forbidden", 403)
        unknown = set(body) - {"tenant", "credential_id", "secret_ref", "description", "secret"}
        if unknown:
            return _error("invalid_credential", 400)
        tenant = body.get("tenant")
        credential_id = body.get("credential_id")
        secret_ref = body.get("secret_ref")
        if (
            not isinstance(tenant, str)
            or not isinstance(credential_id, str)
            or not isinstance(secret_ref, str)
        ):
            return _error("invalid_credential", 400)
        if _cross_tenant(caller, tenant):
            return _error("tenant_forbidden", 403)
        if credentials is None:
            return _error("credential_store_unavailable", 503)
        secret = body.get("secret")
        wrapped: dict[str, Any] | None = None
        key_id: str | None = None
        if secret is not None:
            if (
                not isinstance(secret, str)
                or not secret.strip()
                or len(secret) > 8192
                or "\r" in secret
                or "\n" in secret
            ):
                return _error("invalid_credential", 400)
            if key_backend is None:
                return _error("key_backend_unavailable", 503)
            try:
                wrapped = key_backend.wrap(
                    secret.encode("utf-8"), credential_aad(tenant, credential_id)
                )
                key_id = key_backend.current_key_id()
            except KeyBackendError as exc:
                logger.error("credential encryption failed: %s", type(exc).__name__)
                return _error("encryption_failed", 500)
        actor = caller or Principal(
            tenant=tenant, subject="registry_operator", kind="human", roles=["admin"]
        )
        try:
            binding = CredentialBinding(
                credential_id=credential_id,
                tenant=tenant,
                secret_ref=secret_ref,
                description=body.get("description", ""),
                created_by=actor.subject,
                created_at=datetime.now(timezone.utc),
                wrapped_secret=wrapped,
                secret_key_id=key_id,
                secret_version=1 if wrapped is not None else None,
            )
        except ValidationError:
            return _error("invalid_credential", 400)
        try:
            stored = await credentials.add(binding)
        except CredentialConflict:
            return _error("credential_conflict", 409)
        except CredentialStoreError:
            logger.exception("credential register failed")
            return _error("credential_store_unavailable", 503)
        if audit is not None:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=actor.tenant,
                    principal=actor,
                    agent_ref=_credential_ref(stored, credential_version(stored.secret_key_id)),
                    action="credential.register",
                    target=f"{stored.tenant}/{stored.credential_id}",
                    args_hash=hash_text(stored.model_dump_json(exclude={"wrapped_secret"})),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(
            stored.model_dump(mode="json", exclude={"wrapped_secret"}), status_code=201
        )

    @app.post("/v1/credentials/{credential_id}/disable")
    async def disable_credential(
        request: Request, credential_id: str, tenant: str | None = None
    ) -> JSONResponse:
        caller = _principal(request)
        if caller is not None and "admin" not in caller.roles:
            return _error("forbidden", 403)
        if credentials is None:
            return _error("credential_store_unavailable", 503)
        if tenant is None and caller is None:
            return _error("invalid_request", 400)
        if not _SAFE_NAME.fullmatch(credential_id) or (
            tenant is not None and not _SAFE_NAME.fullmatch(tenant)
        ):
            return _error("invalid_request", 400)
        actor = caller or Principal(
            tenant=cast("str", tenant), subject="registry_operator", kind="human", roles=["admin"]
        )
        target = tenant or actor.tenant
        if not _SAFE_NAME.fullmatch(target):
            return _error("invalid_request", 400)
        if _cross_tenant(caller, target):
            return _error("tenant_forbidden", 403)
        try:
            existing = await credentials.get(target, credential_id)
        except CredentialStoreError:
            logger.exception("credential read failed")
            return _error("credential_store_unavailable", 503)
        if existing is None:
            return _error("credential_not_found", 404)
        try:
            disabled = await credentials.disable(target, credential_id, by=actor.subject)
        except CredentialNotFound:
            return _error("credential_not_found", 404)
        except CredentialStoreError:
            logger.exception("credential disable failed")
            return _error("credential_store_unavailable", 503)
        if audit is not None and existing.enabled:
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=uuid.uuid4().hex,
                    trace_id=uuid.uuid4().hex,
                    tenant=actor.tenant,
                    principal=actor,
                    agent_ref=_credential_ref(disabled, credential_version(disabled.secret_key_id)),
                    action="credential.disable",
                    target=f"{disabled.tenant}/{disabled.credential_id}",
                    args_hash=hash_text("enabled->disabled"),
                    status="ok",
                    timestamp=datetime.now(timezone.utc),
                )
            )
        return JSONResponse(disabled.model_dump(mode="json", exclude={"wrapped_secret"}))

    @app.get("/v1/agents/{tenant}/{agent_id}/{version}/eval")
    async def get_eval_report(
        request: Request, tenant: str, agent_id: str, version: str
    ) -> JSONResponse:
        if _cross_tenant(_principal(request), tenant):
            return _error("tenant_forbidden", 403)
        if eval_reports is None:
            return _error("eval_store_unavailable", 502)
        try:
            report = await eval_reports.get(tenant, agent_id, version)
        except RegistryError:
            return _error("eval_store_unavailable", 502)
        except Exception:  # noqa: BLE001
            logger.exception("eval report read failure")
            return _error("eval_store_unavailable", 502)
        if report is None:
            return _error("eval_report_not_found", 404)
        return JSONResponse(report.model_dump(mode="json"))

    @app.put("/v1/agents/{tenant}/{agent_id}/{version}/eval")
    async def put_eval_report(
        request: Request, tenant: str, agent_id: str, version: str
    ) -> JSONResponse:
        try:
            body: Any = await request.json()
        except ValueError:
            return _error("invalid_json", 400)
        try:
            report = EvalReport.model_validate(body)
        except ValidationError:
            return _error("invalid_report", 400)
        if _cross_tenant(_principal(request), tenant):
            return _error("tenant_forbidden", 403)
        try:
            records = await registry.list(tenant)
        except RegistryError as exc:
            return _read_error(exc)
        except Exception:  # noqa: BLE001
            logger.exception("registry list failure")
            return _error("registry_unavailable", 502)
        if not any(
            record.manifest.id == agent_id and record.manifest.version == version
            for record in records
        ):
            return _error("not_found", 404)
        if eval_reports is None:
            return _error("eval_store_unavailable", 502)
        try:
            stored = await eval_reports.put(tenant, agent_id, version, report)
        except EvalReportConflict:
            return _error("eval_report_conflict", 409)
        except RegistryError:
            return _error("eval_store_unavailable", 502)
        except Exception:  # noqa: BLE001
            logger.exception("eval report write failure")
            return _error("eval_store_unavailable", 502)
        return JSONResponse(stored.model_dump(mode="json"), status_code=201)

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
        manifest_data = body.get("manifest") if isinstance(body, dict) else None
        if not isinstance(manifest_data, dict):
            return _error("invalid_record", 400)
        try:
            tier = declared_execution_tier(manifest_data)
        except ValueError:
            return _error("invalid_record", 400)
        if tier == "sandboxed" and not agent_sandbox_available():
            return _error("sandbox_unavailable", 409)

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

        if tier == "in_process" and artifact is not None:
            if builder_keys is None:
                return _error("builder_key_unavailable", 503)
            try:
                builder_keys.verify_builder(artifact)
            except ArtifactTrustError:
                return _error("artifact_untrusted", 400)
            except PublishUnavailable:
                return _error("builder_key_unavailable", 503)

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
            limiter=build_rate_limiter(rate_limit, surface="registry"),
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
