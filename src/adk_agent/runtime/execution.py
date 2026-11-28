"""Run an agent with trace metadata and audit."""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from google.genai import types

from ..adapters.adk.events import to_run_event
from ..adapters.adk.runner import run_config
from ..core import (
    AgentRef,
    AuditEvent,
    AuditSink,
    Invocation,
    InvocationResult,
    ProgressEvent,
    ProgressKind,
    QuotaExceeded,
    QuotaManager,
    QuotaPolicy,
    RunEvent,
)
from ..core.context import reset_invocation, set_invocation
from ..metrics import MetricsRegistry

if TYPE_CHECKING:  # pragma: no cover
    from ..rag.context import RagContext

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[ProgressEvent], Awaitable[None]]


class _Progress:
    """Build progress events and deliver them without breaking the run."""

    def __init__(
        self,
        callback: ProgressCallback | None,
        invocation: Invocation,
        started: float,
    ) -> None:
        self._callback = callback
        self._invocation = invocation
        self._started = started

    async def emit(
        self,
        kind: ProgressKind,
        *,
        author: str | None = None,
        tool: str | None = None,
        text: str | None = None,
        detail: str | None = None,
    ) -> None:
        if self._callback is None:
            return
        event = ProgressEvent(
            kind=kind,
            run_id=self._invocation.run_id,
            trace_id=self._invocation.trace_id,
            author=author,
            tool=tool,
            text=text,
            detail=detail,
            elapsed_ms=int((time.perf_counter() - self._started) * 1000),
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await self._callback(event)
        except Exception:  # noqa: BLE001
            logger.exception("progress callback failed")


class AgentRuntime:
    """Wrap an ADK Runner and carry run identity into the agent."""

    def __init__(
        self,
        runner: Any,
        audit: AuditSink | None = None,
        metrics: MetricsRegistry | None = None,
        source: str = "agent",
        rag: RagContext | None = None,
    ) -> None:
        self.runner = runner
        self.audit = audit
        self.metrics = metrics
        self.source = source
        self.rag = rag

    async def run(
        self,
        invocation: Invocation,
        *,
        user_id: str,
        session_id: str,
        quota: QuotaManager | None = None,
        quota_policy: QuotaPolicy | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> InvocationResult:
        started = time.perf_counter()
        progress = _Progress(on_progress, invocation, started)
        await progress.emit("run.started")

        try:
            if quota is None or quota_policy is None:
                result = await self._run(invocation, user_id, session_id, started, progress)
            else:
                try:
                    async with quota.reserve(invocation.principal.tenant, quota_policy):
                        result = await self._run(invocation, user_id, session_id, started, progress)
                except QuotaExceeded:
                    await self._audit(
                        invocation,
                        status="denied",
                        error_code="quota_exceeded",
                        started=started,
                    )
                    await progress.emit("run.failed", detail="QuotaExceeded")
                    raise
        except QuotaExceeded as exc:
            self._record_run(invocation, "denied", started)
            self._record_quota_denial(invocation, exc.limit)
            raise
        except Exception:
            self._record_run(invocation, "error", started)
            raise

        self._record_run(invocation, "ok", started)
        return result

    def _record_run(self, invocation: Invocation, status: str, started: float) -> None:
        if self.metrics is None:
            return
        tenant = invocation.principal.tenant
        agent = invocation.agent_ref.id
        self.metrics.inc(
            "adk_agent_runs_total",
            {"source": self.source, "tenant": tenant, "agent": agent, "status": status},
        )
        self.metrics.observe(
            "adk_agent_run_duration_seconds",
            time.perf_counter() - started,
            {"agent": agent, "tenant": tenant},
        )

    def _record_quota_denial(self, invocation: Invocation, limit: str) -> None:
        if self.metrics is None:
            return
        self.metrics.inc(
            "adk_agent_quota_denials_total",
            {"tenant": invocation.principal.tenant, "limit": limit},
        )

    async def _run(
        self,
        invocation: Invocation,
        user_id: str,
        session_id: str,
        started: float,
        progress: _Progress,
    ) -> InvocationResult:
        config = run_config(
            {
                "run_id": invocation.run_id,
                "trace_id": invocation.trace_id,
                "principal": invocation.principal.model_dump(mode="json"),
                "agent_ref": invocation.agent_ref.model_dump(mode="json"),
            }
        )
        reply_parts: list[str] = []
        token = set_invocation(invocation)
        try:
            text = invocation.input
            if self.rag is not None:
                block = await self.rag.prefix(invocation)
                if block:
                    text = block + "\n\n" + text
            new_message = types.Content(role="user", parts=[types.Part(text=text)])
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=new_message,
                run_config=config,
            ):
                run_event = to_run_event(event)
                await self._emit_progress(progress, run_event)
                if run_event.final:
                    reply_parts.append(run_event.text)
        except Exception as exc:
            await self._audit(
                invocation,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
            await progress.emit("run.failed", detail=type(exc).__name__)
            raise
        finally:
            reset_invocation(token)

        text = "".join(reply_parts).strip()
        await self._audit(
            invocation,
            status="ok",
            error_code=None,
            started=started,
            text=text,
        )
        await progress.emit("run.finished", text=text)
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
        )

    async def _emit_progress(self, progress: _Progress, event: RunEvent) -> None:
        for part in event.parts:
            if part.kind == "tool_call":
                await progress.emit("tool.call", author=event.author, tool=part.name)
            elif part.kind == "tool_result":
                await progress.emit("tool.result", author=event.author, tool=part.name)
            elif part.text:
                await progress.emit("model.text", author=event.author, text=part.text)

    async def _audit(
        self,
        invocation: Invocation,
        *,
        status: Literal["ok", "error", "denied"],
        error_code: str | None,
        started: float,
        text: str | None = None,
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
            action="agent.run",
            target=f"{invocation.agent_ref.id}@{invocation.agent_ref.version}",
            args_hash=_hash(invocation.input),
            result_hash=_hash(text) if text is not None else None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)


def dev_agent_ref(name: str) -> AgentRef:
    """Build a dev-only ref for an unpublished console agent."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return AgentRef(id=name, version="dev", digest=digest)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
