"""Wrap an MCP agent runner with audit and tenant quota.

The MCP server paths call ADK's ``_run_agent`` directly, bypassing
``AgentRuntime``.  This proxy restores the two guarantees that matter at the
MCP boundary: every tool call is audited, and listed tenants cannot exceed
their quota.
"""

from __future__ import annotations

import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from typing import Any, Literal

from ..audit.hashing import hash_text
from ..core import (
    AuditEvent,
    AuditSink,
    Principal,
    QuotaExceeded,
    QuotaManager,
    QuotaPolicy,
)
from ..runtime.execution import dev_agent_ref

__all__ = ["AuditedMcpRunner", "wrap_runner"]


class AuditedMcpRunner:
    """Audit and quota proxy around an MCP agent runner.

    Events yielded by the inner runner pass through unchanged.  A successful
    run emits one ``agent.run`` event with the result hash; a failed run emits
    ``error`` and re-raises; a failed reservation emits ``denied`` without
    calling the inner runner.
    """

    def __init__(
        self,
        inner: Any,
        *,
        agent_name: str,
        principal: Principal,
        input_text: str,
        audit: AuditSink | None,
        quota: QuotaManager | None,
        quota_policy: QuotaPolicy | None,
        trace_id: str | None = None,
    ) -> None:
        self._inner = inner
        self._agent_name = agent_name
        self._principal = principal
        self._input_text = input_text
        self._audit = audit
        self._quota = quota
        self._quota_policy = quota_policy
        self._trace_id = trace_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def run_async(self, **kwargs: Any):
        started = time.perf_counter()
        run_id = uuid.uuid4().hex
        trace_id = self._trace_id or uuid.uuid4().hex

        stack = AsyncExitStack()
        if self._quota is not None and self._quota_policy is not None:
            try:
                await stack.enter_async_context(
                    self._quota.reserve(self._principal.tenant, self._quota_policy)
                )
            except QuotaExceeded:
                await self._emit(
                    run_id=run_id,
                    trace_id=trace_id,
                    status="denied",
                    error_code="quota_exceeded",
                    result_hash=None,
                    started=started,
                )
                raise

        try:
            reply_parts: list[str] = []
            try:
                async for event in self._inner.run_async(**kwargs):
                    if event.is_final_response() and event.content and event.content.parts:
                        for part in event.content.parts:
                            if not part.thought and part.text:
                                reply_parts.append(part.text)
                    yield event
            except Exception as exc:
                await self._emit(
                    run_id=run_id,
                    trace_id=trace_id,
                    status="error",
                    error_code=type(exc).__name__,
                    result_hash=None,
                    started=started,
                )
                raise

            text = "".join(reply_parts).strip()
            await self._emit(
                run_id=run_id,
                trace_id=trace_id,
                status="ok",
                error_code=None,
                result_hash=hash_text(text),
                started=started,
            )
        finally:
            await stack.aclose()

    async def _emit(
        self,
        *,
        run_id: str,
        trace_id: str,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        result_hash: str | None,
        started: float,
    ) -> None:
        if self._audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=run_id,
            trace_id=trace_id,
            tenant=self._principal.tenant,
            principal=self._principal,
            agent_ref=dev_agent_ref(self._agent_name),
            action="agent.run",
            target=f"{self._agent_name}@dev",
            args_hash=hash_text(self._input_text),
            result_hash=result_hash,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self._audit.emit(event)


def wrap_runner(inner: Any, **kwargs: Any) -> Any:
    """Wrap ``inner`` only when an audit sink or quota manager is configured."""
    if kwargs.get("audit") is None and kwargs.get("quota") is None:
        return inner
    return AuditedMcpRunner(inner, **kwargs)
