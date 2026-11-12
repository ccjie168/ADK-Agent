"""Deterministic executor for single and sequential orchestration plans."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Literal

from ..audit.hashing import hash_text
from ..core import (
    AgentRef,
    AuditEvent,
    AuditSink,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanResult,
    PlanStep,
    PolicyEngine,
    plan_ref,
)
from .errors import PlanDenied, PlanExecutionError, UnknownAgent

AgentCall = Callable[[Invocation], Awaitable[InvocationResult]]
Status = Literal["ok", "error", "denied"]


def _error_code(error: BaseException) -> str:
    if isinstance(error, PlanDenied):
        return "policy_denied"
    if isinstance(error, UnknownAgent):
        return "unknown_agent"
    if isinstance(error, PlanExecutionError):
        return getattr(error.error, "error_code", type(error.error).__name__)
    return getattr(error, "error_code", type(error).__name__)


class PlanExecutor:
    def __init__(
        self,
        agents: Mapping[str, AgentCall],
        policy: PolicyEngine,
        audit: AuditSink | None = None,
    ) -> None:
        self.agents = dict(agents)
        self.policy = policy
        self.audit = audit

    async def run(self, plan: OrchestrationPlan, invocation: Invocation) -> PlanResult:
        started = time.perf_counter()
        reference = plan_ref(plan)
        outputs: dict[str, str] = {}
        ordered = plan.order()

        try:
            for step in ordered:
                await self._run_step(step, invocation, outputs)
        except Exception as exc:
            await self._audit_run(
                invocation,
                reference,
                plan,
                status="denied" if isinstance(exc, PlanDenied) else "error",
                error_code=_error_code(exc),
                result_text=None,
                started=started,
            )
            raise

        final_text = outputs.get(ordered[-1].id, "")
        await self._audit_run(
            invocation,
            reference,
            plan,
            status="ok",
            error_code=None,
            result_text=final_text,
            started=started,
        )
        return PlanResult(
            plan_id=plan.plan_id,
            version=plan.version,
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            outputs=outputs,
            final_text=final_text,
        )

    async def _run_step(
        self,
        step: PlanStep,
        parent: Invocation,
        outputs: dict[str, str],
    ) -> None:
        decision = await self.policy.decide(parent, "agent.invoke", step.agent_ref.id)
        input_text = self._step_input(step, parent, outputs)
        child = self._child_invocation(step, parent, input_text)
        started = time.perf_counter()

        if decision.decision != "allow":
            await self._audit_step(
                child, step, input_text, None, "denied", "policy_denied", started
            )
            raise PlanDenied(f"agent {step.agent_ref.id!r} is not allowed")

        call = self.agents.get(step.agent_ref.id)
        if call is None:
            await self._audit_step(child, step, input_text, None, "error", "unknown_agent", started)
            raise UnknownAgent(f"agent {step.agent_ref.id!r} is not registered")

        try:
            result = await call(child)
        except Exception as exc:
            await self._audit_step(
                child, step, input_text, None, "error", _error_code(exc), started
            )
            raise PlanExecutionError(step.id, exc) from exc

        outputs[step.id] = result.text
        await self._audit_step(child, step, input_text, result.text, "ok", None, started)

    def _step_input(
        self,
        step: PlanStep,
        parent: Invocation,
        outputs: dict[str, str],
    ) -> str:
        parts = [step.input] if step.input else []
        parts.extend(outputs[source] for source in step.inputs_from)
        return "\n\n".join(parts) if parts else parent.input

    def _child_invocation(
        self,
        step: PlanStep,
        parent: Invocation,
        input_text: str,
    ) -> Invocation:
        deadline = parent.deadline
        if step.timeout_seconds is not None:
            limit = datetime.now(timezone.utc) + timedelta(seconds=step.timeout_seconds)
            deadline = min(deadline, limit) if deadline is not None else limit

        budget = parent.budget_usd
        if step.budget_usd is not None:
            budget = min(budget, step.budget_usd) if budget is not None else step.budget_usd

        return Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=parent.trace_id,
            principal=parent.principal,
            agent_ref=step.agent_ref,
            input=input_text,
            deadline=deadline,
            budget_usd=budget,
        )

    async def _audit_step(
        self,
        child: Invocation,
        step: PlanStep,
        input_text: str,
        output_text: str | None,
        status: Status,
        error_code: str | None,
        started: float,
    ) -> None:
        if self.audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=child.run_id,
            trace_id=child.trace_id,
            tenant=child.principal.tenant,
            principal=child.principal,
            agent_ref=step.agent_ref,
            action="orchestration.step",
            target=step.id,
            args_hash=hash_text(input_text),
            result_hash=hash_text(output_text) if output_text is not None else None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)

    async def _audit_run(
        self,
        parent: Invocation,
        reference: AgentRef,
        plan: OrchestrationPlan,
        *,
        status: Status,
        error_code: str | None,
        result_text: str | None,
        started: float,
    ) -> None:
        if self.audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=parent.run_id,
            trace_id=parent.trace_id,
            tenant=parent.principal.tenant,
            principal=parent.principal,
            agent_ref=reference,
            action="orchestration.run",
            target=f"{plan.plan_id}@{plan.version}",
            args_hash=hash_text(parent.input),
            result_hash=hash_text(result_text) if result_text is not None else None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)
