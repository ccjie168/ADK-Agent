"""Standalone webhook trigger execution service (SLICE-125)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.adk.sessions import InMemorySessionService

from .audit.hashing import hash_text
from .core import (
    AgentLifecycleStore,
    AgentRef,
    AgentRegistry,
    AgentTrigger,
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
from .sandbox.agent import AgentSandboxBackend, AgentSandboxUnavailable, require_execution_supported
from .sandbox.errors import SandboxCrashed, SandboxTimeout, SandboxViolation
from .tools.enforcement import install_declared_guards
from .tracing import resolve_trace_id

logger = logging.getLogger(__name__)

_MAX_INPUT = 8000
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_TRIGGER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_ERROR_STATUS = {
    "trigger_not_found": 404,
    "digest_mismatch": 409,
    "version_retired": 409,
    "approval_required": 409,
    "sandbox_unavailable": 409,
    "tool_mediation_unavailable": 409,
    "sandbox_timeout": 500,
    "sandbox_crashed": 500,
    "sandbox_violation": 500,
    "agent_load_failed": 502,
    "quota_exceeded": 429,
    "invalid_request": 400,
}


@dataclass(frozen=True)
class TriggerExecution:
    """Outcome of one trigger run, shared by the webhook and schedule paths."""

    status: Literal["ok", "error", "denied"]
    error_code: str | None
    run_id: str
    trace_id: str
    text: str = ""


def _error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status_code)


def _execution_response(execution: TriggerExecution) -> JSONResponse:
    if execution.status == "ok":
        return JSONResponse(
            {
                "run_id": execution.run_id,
                "trace_id": execution.trace_id,
                "status": "ok",
                "duplicate": False,
                "text": execution.text,
            }
        )
    code = execution.error_code
    if code is not None:
        status_code = _ERROR_STATUS.get(code)
        if status_code is not None:
            return _error(code, status_code)
    return _error("run_failed", 500)


def _request_input(body: dict[str, Any], fallback: str) -> str | None:
    """Resolve the run input, or ``None`` when the request is invalid."""
    text = body.get("input", fallback)
    if not isinstance(text, str) or not 1 <= len(text) <= _MAX_INPUT:
        return None
    return text


async def run_schedule_tick(
    *,
    triggers: TriggerStore,
    fire_store: TriggerFireStore,
    execute: Callable[..., Awaitable[TriggerExecution]],
    now: datetime,
    attempts: int,
) -> list[TriggerExecution]:
    """Run every due schedule trigger for the current slot, at most once each."""
    results: list[TriggerExecution] = []
    for trigger in await triggers.list_all():
        if not trigger.enabled or trigger.kind != "schedule":
            continue
        every_seconds = trigger.every_seconds
        if not every_seconds:
            continue
        slot = int(now.timestamp() // every_seconds)
        fire = TriggerFire(
            tenant=trigger.tenant,
            trigger_id=trigger.trigger_id,
            idempotency_key=f"slot-{slot}",
            run_id=uuid.uuid4().hex,
            trace_id=uuid.uuid4().hex,
            status="running",
            created_at=now,
        )
        try:
            claimed = await fire_store.claim(fire)
        except Exception:  # noqa: BLE001
            logger.exception(
                "trigger %s/%s slot %s claim failed", trigger.tenant, trigger.trigger_id, slot
            )
            continue
        if claimed.run_id != fire.run_id:
            continue
        try:
            results.append(
                await execute(
                    trigger,
                    trigger.input,
                    fire=fire,
                    run_id=fire.run_id,
                    trace_id=fire.trace_id,
                    attempts=attempts,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "trigger %s/%s slot %s execution failed",
                trigger.tenant,
                trigger.trigger_id,
                slot,
            )
    return results


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
    sandbox: AgentSandboxBackend | None = None,
    scheduler: bool = False,
    schedule_tick: float = 15.0,
    trigger_attempts: int = 3,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """Build the trigger service. Only ``/healthz`` is open."""
    if schedule_tick < 5:
        raise ValueError("schedule_tick must be at least 5 seconds")
    if trigger_attempts < 1:
        raise ValueError("trigger_attempts must be at least 1")
    if scheduler and fire_store is None:
        raise ValueError("scheduler requires a fire store")

    metrics = metrics if metrics is not None else MetricsRegistry()

    async def execute(
        trigger: AgentTrigger,
        input_text: str,
        *,
        fire: TriggerFire | None,
        run_id: str,
        trace_id: str,
        attempts: int,
    ) -> TriggerExecution:
        started = time.perf_counter()
        tenant = trigger.tenant
        trigger_id = trigger.trigger_id

        async def finish(
            status: Literal["ok", "error", "denied"], error_code: str | None = None
        ) -> None:
            if fire is None or fire_store is None:
                return
            try:
                await fire_store.finish(
                    fire.tenant,
                    fire.trigger_id,
                    fire.idempotency_key,
                    status=status,
                    error_code=error_code,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "failed to finish trigger fire %s/%s/%s",
                    fire.tenant,
                    fire.trigger_id,
                    fire.idempotency_key,
                )

        expected_digest = trigger.digest.removeprefix("sha256:")
        ref = AgentRef(id=trigger.agent_id, version=trigger.version, digest=expected_digest)
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

        async def record_agent_run(
            status: Literal["ok", "error", "denied"],
            error_code: str | None,
            started_at: float,
            result_text: str | None = None,
        ) -> None:
            """Record the agent dimension of a sandboxed run, never raising."""
            elapsed = time.perf_counter() - started_at
            metrics.inc(
                "adk_agent_runs_total",
                {
                    "source": "trigger",
                    "tenant": tenant,
                    "agent": trigger.agent_id,
                    "status": status,
                },
            )
            metrics.observe(
                "adk_agent_run_duration_seconds",
                elapsed,
                {"agent": trigger.agent_id, "tenant": tenant},
            )
            if audit is None:
                return
            try:
                await audit.emit(
                    AuditEvent(
                        event_id=uuid.uuid4().hex,
                        run_id=run_id,
                        trace_id=trace_id,
                        tenant=tenant,
                        principal=principal,
                        agent_ref=ref,
                        action="agent.run",
                        target=f"{trigger.agent_id}@{trigger.version}",
                        args_hash=hash_text(input_text),
                        result_hash=hash_text(result_text) if result_text is not None else None,
                        data_classes=[],
                        latency_ms=int(elapsed * 1000),
                        egress="third_party",
                        status=status,
                        error_code=error_code,
                        timestamp=datetime.now(timezone.utc),
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("trigger %s/%s agent.run audit failed", tenant, trigger_id)

        if not input_text:
            await finish("error", "invalid_request")
            await emit("error", "invalid_request", run_id, trace_id)
            return TriggerExecution("error", "invalid_request", run_id, trace_id)

        published: Any = None
        for attempt in range(1, attempts + 1):
            try:
                published = await registry.get(ref, tenant)
                if published is None:
                    records = await registry.list(tenant)
                    registered = next(
                        (
                            record
                            for record in records
                            if record.manifest.id == trigger.agent_id
                            and record.manifest.version == trigger.version
                        ),
                        None,
                    )
                    code = (
                        "digest_mismatch"
                        if registered is not None and registered.digest != expected_digest
                        else "trigger_not_found"
                    )
                    await finish("error", code)
                    await emit("error", code, run_id, trace_id)
                    return TriggerExecution("error", code, run_id, trace_id)
                if published.digest != expected_digest:
                    await finish("error", "digest_mismatch")
                    await emit("error", "digest_mismatch", run_id, trace_id)
                    return TriggerExecution("error", "digest_mismatch", run_id, trace_id)
                if lifecycle is not None:
                    state = await lifecycle.get(tenant, trigger.agent_id, trigger.version)
                    if state.status == "retired":
                        await finish("error", "version_retired")
                        await emit("error", "version_retired", run_id, trace_id)
                        return TriggerExecution("error", "version_retired", run_id, trace_id)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == attempts:
                    code = type(exc).__name__
                    logger.exception("trigger %s/%s registry read failed", tenant, trigger_id)
                    await finish("error", code)
                    await emit("error", code, run_id, trace_id)
                    return TriggerExecution("error", code, run_id, trace_id)
                await asyncio.sleep(0.2 * attempt)

        is_sandboxed = published.manifest.execution_tier == "sandboxed"
        if is_sandboxed:
            if sandbox is None:
                await finish("error", "sandbox_unavailable")
                await emit("error", "sandbox_unavailable", run_id, trace_id)
                return TriggerExecution("error", "sandbox_unavailable", run_id, trace_id)
            if published.manifest.tool_grants:
                await finish("error", "tool_mediation_unavailable")
                await emit("error", "tool_mediation_unavailable", run_id, trace_id)
                return TriggerExecution("error", "tool_mediation_unavailable", run_id, trace_id)
            active_sandbox = sandbox
        else:
            try:
                require_execution_supported(published.manifest)
            except AgentSandboxUnavailable:
                await finish("error", "sandbox_unavailable")
                await emit("error", "sandbox_unavailable", run_id, trace_id)
                return TriggerExecution("error", "sandbox_unavailable", run_id, trace_id)

        if any(grant.requires_approval for grant in published.manifest.tool_grants):
            await finish("denied", "approval_required")
            await emit("denied", "approval_required", run_id, trace_id)
            return TriggerExecution("denied", "approval_required", run_id, trace_id)

        if is_sandboxed:
            artifact = published.artifact
            if artifact is None:
                await finish("error", "agent_load_failed")
                await emit("error", "agent_load_failed", run_id, trace_id)
                return TriggerExecution("error", "agent_load_failed", run_id, trace_id)
            try:
                trust.verify(artifact)
                data = await artifact_store.get(artifact.digest)
            except Exception:  # noqa: BLE001
                logger.exception("trigger %s/%s artifact fetch failed", tenant, trigger_id)
                data = None
            if data is None:
                await finish("error", "agent_load_failed")
                await emit("error", "agent_load_failed", run_id, trace_id)
                return TriggerExecution("error", "agent_load_failed", run_id, trace_id)

            started_at = time.perf_counter()
            policy = quota_config.tenants.get(tenant) if quota_config is not None else None
            try:
                if quota is not None and policy is not None:
                    async with quota.reserve(tenant, policy):
                        sandbox_result = await active_sandbox.run(
                            artifact, data, input_text, manifest=published.manifest
                        )
                else:
                    sandbox_result = await active_sandbox.run(
                        artifact, data, input_text, manifest=published.manifest
                    )
            except QuotaExceeded as exc:
                metrics.inc("adk_agent_quota_denials_total", {"tenant": tenant, "limit": exc.limit})
                await finish("denied", "quota_exceeded")
                await record_agent_run("denied", "quota_exceeded", started_at)
                await emit("denied", "quota_exceeded", run_id, trace_id)
                return TriggerExecution("denied", "quota_exceeded", run_id, trace_id)
            except SandboxTimeout:
                await finish("error", "sandbox_timeout")
                await record_agent_run("error", "sandbox_timeout", started_at)
                await emit("error", "sandbox_timeout", run_id, trace_id)
                return TriggerExecution("error", "sandbox_timeout", run_id, trace_id)
            except SandboxViolation:
                await finish("error", "sandbox_violation")
                await record_agent_run("error", "sandbox_violation", started_at)
                await emit("error", "sandbox_violation", run_id, trace_id)
                return TriggerExecution("error", "sandbox_violation", run_id, trace_id)
            except SandboxCrashed:
                await finish("error", "sandbox_crashed")
                await record_agent_run("error", "sandbox_crashed", started_at)
                await emit("error", "sandbox_crashed", run_id, trace_id)
                return TriggerExecution("error", "sandbox_crashed", run_id, trace_id)
            except Exception:  # noqa: BLE001
                logger.exception("trigger %s/%s sandbox run failed", tenant, trigger_id)
                await finish("error", "run_failed")
                await record_agent_run("error", "run_failed", started_at)
                await emit("error", "run_failed", run_id, trace_id)
                return TriggerExecution("error", "run_failed", run_id, trace_id)

            await finish("ok")
            await record_agent_run("ok", None, started_at, sandbox_result.text)
            await emit("ok", None, run_id, trace_id, sandbox_result.text)
            return TriggerExecution("ok", None, run_id, trace_id, sandbox_result.text)

        agent: Any = None
        for attempt in range(1, attempts + 1):
            try:
                if published.artifact is None:
                    raise ValueError("published agent has no artifact")
                trust.verify(published.artifact)
                agent = await loader.load(published.artifact, artifact_store)
                break
            except Exception:  # noqa: BLE001
                if attempt < attempts:
                    await asyncio.sleep(0.2 * attempt)
        else:
            logger.warning(
                "trigger %s/%s agent load failed after %d attempts", tenant, trigger_id, attempts
            )
            await finish("error", "agent_load_failed")
            await emit("error", "agent_load_failed", run_id, trace_id)
            return TriggerExecution("error", "agent_load_failed", run_id, trace_id)

        install_declared_guards(
            agent,
            audit,
            overlay=tool_grants,
            grants=list(published.manifest.tool_grants),
        )

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

            session = await service.create_session(app_name=agent.name, user_id=principal.subject)
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
            await finish("denied", "quota_exceeded")
            await emit("denied", "quota_exceeded", run_id, trace_id)
            return TriggerExecution("denied", "quota_exceeded", run_id, trace_id)
        except Exception as exc:  # noqa: BLE001
            code = type(exc).__name__
            await finish("error", code)
            await emit("error", code, run_id, trace_id)
            return TriggerExecution("error", code, run_id, trace_id)

        await finish("ok")
        await emit("ok", None, run_id, trace_id, result.text)
        return TriggerExecution("ok", None, run_id, trace_id, result.text)

    async def _schedule_loop() -> None:
        store = cast("TriggerFireStore", fire_store)
        while True:
            try:
                now = clock() if clock is not None else datetime.now(timezone.utc)
                await run_schedule_tick(
                    triggers=triggers,
                    fire_store=store,
                    execute=execute,
                    now=now,
                    attempts=trigger_attempts,
                )
            except Exception:  # noqa: BLE001
                logger.exception("trigger schedule tick failed")
            await asyncio.sleep(schedule_tick)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        if scheduler:
            task = asyncio.create_task(_schedule_loop())
            application.state.scheduler_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="ADK Trigger Service", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/tenants/{tenant}/triggers/{trigger_id}/fire")
    async def fire(request: Request, tenant: str, trigger_id: str) -> JSONResponse:
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

        run_id = uuid.uuid4().hex
        fire_record: TriggerFire | None = None
        if idempotency_key is not None and fire_store is not None:
            candidate = TriggerFire(
                tenant=tenant,
                trigger_id=trigger_id,
                idempotency_key=idempotency_key,
                run_id=run_id,
                trace_id=trace_id,
                status="running",
                created_at=datetime.now(timezone.utc),
            )
            previous = await fire_store.claim(candidate)
            if previous.run_id != candidate.run_id:
                if previous.status == "running":
                    return _error("fire_in_progress", 409)
                return JSONResponse(
                    {
                        "run_id": previous.run_id,
                        "trace_id": previous.trace_id,
                        "status": previous.status,
                        "duplicate": True,
                        "text": "",
                        "error_code": previous.error_code,
                    }
                )
            fire_record = candidate

        execution = await execute(
            trigger,
            input_text,
            fire=fire_record,
            run_id=run_id,
            trace_id=trace_id,
            attempts=trigger_attempts,
        )
        return _execution_response(execution)

    if rate_limit is not None:
        app.add_middleware(
            RateLimitMiddleware,
            limiter=build_rate_limiter(rate_limit, surface="triggers", metrics=metrics),
            surface="triggers",
            exempt=frozenset({"/healthz"}),
            metrics=metrics,
        )
    return app


__all__ = ["TriggerExecution", "build_triggers_app", "run_schedule_tick"]
