"""Standalone webhook trigger execution service (SLICE-125)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.adk.sessions import InMemorySessionService

from .audit.hashing import hash_text
from .core import (
    AgentLifecycleStore,
    AgentRef,
    AgentRegistry,
    ArtifactLoader,
    ArtifactStore,
    AuditEvent,
    AuditSink,
    Invocation,
    Principal,
    QuotaConfig,
    QuotaExceeded,
    QuotaManager,
    ToolGrantStore,
    TriggerFire,
    TriggerFireStore,
    TriggerStore,
)
from .metrics import MetricsRegistry
from .ratelimit import RateLimit, RateLimitMiddleware, build_rate_limiter
from .runtime.execution import AgentRuntime
from .tools.enforcement import install_declared_guards
from .tracing import resolve_trace_id

_MAX_INPUT = 8000
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)


def _request_input(body: dict[str, Any], fallback: str) -> str | None:
    """Resolve the run input, or ``None`` when the request is invalid."""
    text = body.get("input", fallback)
    if not isinstance(text, str) or not 1 <= len(text) <= _MAX_INPUT:
        return None
    return text


def build_triggers_app(
    *,
    triggers: TriggerStore,
    registry: AgentRegistry,
    artifact_store: ArtifactStore,
    trust: Any,
    loader: ArtifactLoader,
    lifecycle: AgentLifecycleStore | None = None,
    tool_grants: ToolGrantStore | None = None,
    audit: AuditSink | None = None,
    quota: QuotaManager | None = None,
    quota_config: QuotaConfig | None = None,
    session_service: Any | None = None,
    runner_factory: Callable[[Any], Any] | None = None,
    rate_limit: RateLimit | None = None,
    metrics: MetricsRegistry | None = None,
    fire_store: TriggerFireStore | None = None,
) -> FastAPI:
    """Build the trigger service. Only ``/healthz`` is open."""
    metrics = metrics if metrics is not None else MetricsRegistry()
    app = FastAPI(title="ADK Trigger Service", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants/{tenant}/triggers/{trigger_id}/fire")
    async def fire(request: Request, tenant: str, trigger_id: str) -> JSONResponse:
        started = time.perf_counter()
        if not _SAFE_NAME.fullmatch(tenant) or not _TRIGGER_ID.fullmatch(trigger_id):
            return _error("trigger_not_found", 404)

        raw = await request.body()
        try:
            body: Any = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return _error("invalid_request", 400)
        if not isinstance(body, dict) or set(body) - {"input"}:
            return _error("invalid_request", 400)

        idempotency_key = request.headers.get("idempotency-key")
        if idempotency_key is not None and not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            return _error("invalid_request", 400)
        trace_id = resolve_trace_id(
            request.headers.get("x-trace-id"), request.headers.get("traceparent")
        )

        trigger = await triggers.get(tenant, trigger_id)
        if trigger is None:
            return _error("trigger_not_found", 404)
        if not trigger.enabled:
            return _error("trigger_disabled", 409)
        if trigger.kind != "webhook":
            return _error("trigger_kind_mismatch", 409)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        expected = trigger.webhook_token_hash or ""
        if (
            scheme.lower() != "bearer"
            or not token
            or not hmac.compare_digest(hashlib.sha256(token.encode("utf-8")).hexdigest(), expected)
        ):
            return _error("unauthorized", 401)

        input_text = _request_input(body, trigger.input)
        if input_text is None:
            return _error("invalid_request", 400)

        ref = AgentRef(id=trigger.agent_id, version=trigger.version, digest=trigger.digest)
        published = await registry.get(ref, tenant)
        if published is None:
            return _error("trigger_not_found", 404)
        if published.digest != trigger.digest:
            return _error("digest_mismatch", 409)

        if lifecycle is not None:
            state = await lifecycle.get(tenant, trigger.agent_id, trigger.version)
            if state.status == "retired":
                return _error("version_retired", 409)

        principal = Principal(tenant=tenant, subject=f"trigger:{trigger_id}", kind="service")

        async def emit(
            status: Literal["ok", "error", "denied"],
            error_code: str | None,
            run_id: str,
            trace: str,
            result_text: str | None = None,
        ) -> None:
            if audit is None:
                return
            await audit.emit(
                AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id=run_id,
                    trace_id=trace,
                    tenant=tenant,
                    principal=principal,
                    agent_ref=ref,
                    action="trigger.fire",
                    target=f"{tenant}/{trigger_id}",
                    args_hash=hash_text(input_text),
                    result_hash=hash_text(result_text) if result_text is not None else None,
                    data_classes=[],
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    egress="none",
                    status=status,
                    error_code=error_code,
                    timestamp=datetime.now(timezone.utc),
                )
            )

        if any(grant.requires_approval for grant in published.manifest.tool_grants):
            await emit("denied", "approval_required", uuid.uuid4().hex, trace_id)
            return _error("approval_required", 409)

        run_id = uuid.uuid4().hex
        claimed: TriggerFire | None = None

        async def finish_fire(
            status: Literal["ok", "error", "denied"], error_code: str | None = None
        ) -> None:
            if claimed is None or fire_store is None or idempotency_key is None:
                return
            await fire_store.finish(
                tenant, trigger_id, idempotency_key, status=status, error_code=error_code
            )

        if idempotency_key is not None and fire_store is not None:
            fire = TriggerFire(
                tenant=tenant,
                trigger_id=trigger_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
                trace_id=trace_id,
                status="running",
                created_at=datetime.now(timezone.utc),
            )
            existing = await fire_store.claim(fire)
            if existing.run_id != fire.run_id:
                if existing.status == "running":
                    return _error("fire_in_progress", 409)
                return JSONResponse(
                    {
                        "run_id": existing.run_id,
                        "trace_id": existing.trace_id,
                        "status": existing.status,
                        "duplicate": True,
                        "text": "",
                        "error_code": existing.error_code,
                    }
                )
            claimed = fire

        try:
            if published.artifact is None:
                raise ValueError("published agent has no artifact")
            trust.verify(published.artifact)
            agent = await loader.load(published.artifact, artifact_store)
        except Exception:  # noqa: BLE001
            await finish_fire("error", "agent_load_failed")
            await emit("error", "agent_load_failed", run_id, trace_id)
            return _error("agent_load_failed", 502)

        install_declared_guards(agent, audit, overlay=tool_grants)

        invocation = Invocation(
            run_id=run_id,
            trace_id=trace_id,
            principal=principal,
            agent_ref=ref,
            input=input_text,
        )
        quota_policy = quota_config.tenants.get(tenant) if quota_config is not None else None

        try:
            service = session_service or InMemorySessionService()

            def default_runner(built: Any) -> Any:
                from google.adk.runners import Runner

                return Runner(app_name=built.name, agent=built, session_service=service)

            session = await service.create_session(
                app_name=trigger.agent_id, user_id=principal.subject
            )
            runner = (runner_factory or default_runner)(agent)
            runtime = AgentRuntime(runner, audit=audit, metrics=metrics, source="trigger")
            result = await runtime.run(
                invocation,
                user_id=principal.subject,
                session_id=str(session.id),
                quota=quota,
                quota_policy=quota_policy,
            )
        except QuotaExceeded:
            await finish_fire("denied", "quota_exceeded")
            await emit("denied", "quota_exceeded", run_id, trace_id)
            return _error("quota_exceeded", 429)
        except Exception as exc:  # noqa: BLE001
            code = type(exc).__name__
            await finish_fire("error", code)
            await emit("error", code, run_id, trace_id)
            return _error("run_failed", 500)

        await finish_fire("ok")
        await emit("ok", None, run_id, trace_id, result.text)
        return JSONResponse(
            {
                "run_id": result.run_id,
                "trace_id": result.trace_id,
                "status": "ok",
                "duplicate": False,
                "text": result.text,
            }
        )

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="triggers", metrics=metrics),
            surface="triggers",
            exempt=frozenset({"/healthz"}),
            metrics=metrics,
        )
    return app


__all__ = ["build_triggers_app"]
