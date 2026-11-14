"""Tool gateway: policy check, invocation, and audit."""

from __future__ import annotations

import inspect
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from ..audit.hashing import hash_json, safe_hash_json
from ..core import (
    AuditEvent,
    AuditSink,
    Invocation,
    PolicyEngine,
    ToolRequest,
    ToolResponse,
)
from ..sandbox import ToolSandbox
from .registry import FunctionRegistry, ToolSpec


class ToolDenied(Exception):
    """The tool call is not allowed."""


class FunctionToolGateway:
    def __init__(
        self,
        registry: FunctionRegistry,
        audit: AuditSink | None = None,
        sandbox: ToolSandbox | None = None,
    ) -> None:
        self.registry = registry
        self.audit = audit
        self.sandbox = sandbox

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

        try:
            if self.sandbox is not None:
                output = self.sandbox.invoke(spec.handler, (), request.args)
            else:
                output = spec.handler(**request.args)
                if inspect.isawaitable(output):
                    output = await output
        except Exception as exc:
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
        return ToolResponse(output=output, data_classes=list(spec.data_classes))

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
