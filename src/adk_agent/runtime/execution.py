"""Run an agent with trace metadata and audit."""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from google.adk.agents.run_config import RunConfig
from google.genai import types

from ..core import (
    AgentRef,
    AuditEvent,
    AuditSink,
    Invocation,
    InvocationResult,
    QuotaExceeded,
    QuotaManager,
    QuotaPolicy,
)
from ..core.context import reset_invocation, set_invocation


class AgentRuntime:
    """Wrap an ADK Runner and carry run identity into the agent."""

    def __init__(self, runner: Any, audit: AuditSink | None = None) -> None:
        self.runner = runner
        self.audit = audit

    async def run(
        self,
        invocation: Invocation,
        *,
        user_id: str,
        session_id: str,
        quota: QuotaManager | None = None,
        quota_policy: QuotaPolicy | None = None,
    ) -> InvocationResult:
        started = time.perf_counter()
        if quota is None or quota_policy is None:
            return await self._run(invocation, user_id, session_id, started)
        try:
            async with quota.reserve(invocation.principal.tenant, quota_policy):
                return await self._run(invocation, user_id, session_id, started)
        except QuotaExceeded:
            await self._audit(
                invocation,
                status="denied",
                error_code="quota_exceeded",
                started=started,
            )
            raise

    async def _run(
        self,
        invocation: Invocation,
        user_id: str,
        session_id: str,
        started: float,
    ) -> InvocationResult:
        run_config = RunConfig(
            custom_metadata={
                "run_id": invocation.run_id,
                "trace_id": invocation.trace_id,
                "principal": invocation.principal.model_dump(mode="json"),
                "agent_ref": invocation.agent_ref.model_dump(mode="json"),
            }
        )
        new_message = types.Content(role="user", parts=[types.Part(text=invocation.input)])
        reply_parts: list[str] = []
        token = set_invocation(invocation)
        try:
            async for event in self.runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=new_message,
                run_config=run_config,
            ):
                if event.is_final_response() and event.content and event.content.parts:
                    for part in event.content.parts:
                        if not part.thought and part.text:
                            reply_parts.append(part.text)
        except Exception as exc:
            await self._audit(
                invocation,
                status="error",
                error_code=type(exc).__name__,
                started=started,
            )
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
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=text,
        )

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
