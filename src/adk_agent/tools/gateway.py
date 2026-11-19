"""Tool gateway: policy check, invocation, and audit."""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from ..audit.hashing import hash_json, safe_hash_json
from ..core import (
    AuditEvent,
    AuditSink,
    Invocation,
    PolicyEngine,
    ToolExecutionRecord,
    ToolIdempotencyError,
    ToolIdempotencyStore,
    ToolRequest,
    ToolResponse,
)
from ..sandbox import ToolSandbox
from .registry import FunctionRegistry, ToolSpec

logger = logging.getLogger(__name__)


class ToolDenied(Exception):
    """The tool call is not allowed."""


class ToolIdempotencyMissing(Exception):
    """A write tool was called without the required idempotency key."""


class ToolResultUnknown(Exception):
    """A write tool executed but its result could not be serialized."""


class ToolIdempotencyInProgress(Exception):
    """A concurrent request for the same idempotency key is still running."""


class FunctionToolGateway:
    def __init__(
        self,
        registry: FunctionRegistry,
        audit: AuditSink | None = None,
        sandbox: ToolSandbox | None = None,
        idempotency: ToolIdempotencyStore | None = None,
        idempotency_ttl_seconds: int = 86400,
    ) -> None:
        self.registry = registry
        self.audit = audit
        self.sandbox = sandbox
        self.idempotency = idempotency
        self.idempotency_ttl_seconds = idempotency_ttl_seconds

    async def invoke(
        self, invocation: Invocation, request: ToolRequest, policy: PolicyEngine
    ) -> ToolResponse:
        started = time.perf_counter()
        args_hash = hash_json(request.args)
        spec = self.registry.get(request.tool_id)
        if spec is None:
            await self._audit(
                invocation,
                request,
                spec=None,
                status="denied",
                error_code="tool_unavailable",
                started=started,
                args_hash=args_hash,
            )
            raise ToolDenied(f"tool {request.tool_id!r} is not registered")

        decision = await policy.decide(invocation, "tool.call", request.tool_id)
        if decision.decision != "allow":
            await self._audit(
                invocation,
                request,
                spec=spec,
                status="denied",
                error_code="policy_denied",
                started=started,
                args_hash=args_hash,
            )
            raise ToolDenied(decision.reason)

        if spec.requires_idempotency and not request.idempotency_key:
            await self._audit(
                invocation,
                request,
                spec=spec,
                status="denied",
                error_code="idempotency_missing",
                started=started,
                args_hash=args_hash,
            )
            raise ToolIdempotencyMissing("idempotency key required")

        if spec.requires_approval:
            await self._audit(
                invocation,
                request,
                spec=spec,
                status="denied",
                error_code="approval_required",
                started=started,
                args_hash=args_hash,
            )
            raise ToolDenied("approval required")

        record: ToolExecutionRecord | None = None
        store: ToolIdempotencyStore | None = None
        idempotency_key: str | None = None
        if spec.requires_idempotency and self.idempotency is not None:
            store = self.idempotency
            idempotency_key = request.idempotency_key
            if idempotency_key is None:  # rejected earlier, defensive
                raise ToolIdempotencyMissing("idempotency key required")
            claim_id = uuid.uuid4().hex
            now = datetime.now(timezone.utc)
            record = await store.claim(
                ToolExecutionRecord(
                    tenant=invocation.principal.tenant,
                    tool_id=request.tool_id,
                    idempotency_key=idempotency_key,
                    claim_id=claim_id,
                    status="claimed",
                    created_at=now,
                    expires_at=now + timedelta(seconds=self.idempotency_ttl_seconds),
                )
            )
            if record.claim_id != claim_id:
                if record.status == "completed":
                    await self._audit(
                        invocation,
                        request,
                        spec=spec,
                        status="ok",
                        error_code=None,
                        started=started,
                        args_hash=args_hash,
                        output=record.output,
                    )
                    return ToolResponse(
                        output=record.output, data_classes=list(record.data_classes)
                    )
                if record.status == "unknown":
                    raise ToolResultUnknown("tool already executed but its result is unknown")
                raise ToolIdempotencyInProgress(
                    "a concurrent request is still executing this idempotency key"
                )

        try:
            if self.sandbox is not None:
                output = self.sandbox.invoke(spec.handler, (), request.args)
            else:
                output = spec.handler(**request.args)
                if inspect.isawaitable(output):
                    output = await output
        except Exception as exc:
            if record is not None and store is not None and idempotency_key is not None:
                try:
                    await store.release(
                        invocation.principal.tenant, request.tool_id, idempotency_key
                    )
                except ToolIdempotencyError:
                    logger.warning("failed to release idempotency claim for %s", request.tool_id)
            await self._audit(
                invocation,
                request,
                spec=spec,
                status="error",
                error_code=getattr(exc, "error_code", type(exc).__name__),
                started=started,
                args_hash=args_hash,
            )
            raise

        response = ToolResponse(output=output, data_classes=list(spec.data_classes))
        if record is not None:
            if store is None or idempotency_key is None:  # unreachable, defensive
                raise RuntimeError("idempotency store was not configured")
            try:
                response.model_dump(mode="json")
            except Exception:
                await store.finish(
                    invocation.principal.tenant,
                    request.tool_id,
                    idempotency_key,
                    status="unknown",
                    error_code="serialization_failed",
                )
                await self._audit(
                    invocation,
                    request,
                    spec=spec,
                    status="error",
                    error_code="serialization_failed",
                    started=started,
                    args_hash=args_hash,
                )
                raise ToolResultUnknown(
                    "tool executed but its result could not be serialized"
                ) from None
            await store.finish(
                invocation.principal.tenant,
                request.tool_id,
                idempotency_key,
                status="completed",
                output=output,
                data_classes=list(spec.data_classes),
            )

        await self._audit(
            invocation,
            request,
            spec=spec,
            status="ok",
            error_code=None,
            started=started,
            args_hash=args_hash,
            output=output,
        )
        return response

    async def _audit(
        self,
        invocation: Invocation,
        request: ToolRequest,
        *,
        spec: ToolSpec | None,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        started: float,
        args_hash: str,
        output: Any = None,
    ) -> None:
        if self.audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            tenant=invocation.principal.tenant,
            principal=invocation.principal,
            agent_ref=invocation.agent_ref,
            action="tool.call",
            target=request.tool_id,
            args_hash=args_hash,
            result_hash=safe_hash_json(output) if output is not None else None,
            data_classes=list(spec.data_classes) if spec is not None else [],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress=spec.egress if spec is not None else "none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)
