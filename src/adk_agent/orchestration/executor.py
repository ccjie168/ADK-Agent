"""Deterministic executor with retries, timeouts, budget checks, and cancellation."""

from __future__ import annotations

import asyncio
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
from .cancel import CancellationToken
from .errors import (
    BudgetExceeded,
    PlanCancelled,
    PlanDenied,
    PlanExecutionError,
    PlanTimeout,
    StepTimeout,
    UnknownAgent,
)

AgentCall = Callable[[Invocation], Awaitable[InvocationResult]]
Status = Literal["ok", "error", "denied"]


def _error_code(error: BaseException) -> str:
    if isinstance(error, PlanDenied):
        return "policy_denied"
    if isinstance(error, UnknownAgent):
        return "unknown_agent"
    if isinstance(error, PlanCancelled):
        return "cancelled"
    if isinstance(error, PlanTimeout):
        return "plan_timeout"
    if isinstance(error, StepTimeout):
        return "StepTimeout"
    if isinstance(error, BudgetExceeded):
        return "budget_exceeded"
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

    async def run(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None = None,
    ) -> PlanResult:
        started = time.perf_counter()
        reference = plan_ref(plan)
        outputs: dict[str, str] = {}
        spent_usd = 0.0
        ordered = plan.order()

        try:
            for step in ordered:
                self._check_cancelled(cancel)
                self._check_deadline(invocation)
                self._check_budget(invocation, spent_usd)
                spent_usd += await self._run_step(step, invocation, outputs, spent_usd, cancel)
                if invocation.budget_usd is not None and spent_usd > invocation.budget_usd:
                    raise BudgetExceeded("plan budget exceeded")
        except Exception as exc:
            status: Status = "denied" if isinstance(exc, (PlanDenied, BudgetExceeded)) else "error"
            await self._audit_run(
                invocation,
                reference,
                plan,
                status=status,
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
            cost_usd=spent_usd,
        )

    async def _run_step(
        self,
        step: PlanStep,
        parent: Invocation,
        outputs: dict[str, str],
        spent_usd: float,
        cancel: CancellationToken | None,
    ) -> float:
        decision = await self.policy.decide(parent, "agent.invoke", step.agent_ref.id)
        input_text = self._step_input(step, parent, outputs)
        remaining = self._remaining_seconds(parent)
        if remaining is not None and remaining <= 0:
            raise PlanTimeout("plan deadline exceeded")

        timeout = step.timeout_seconds
        deadline_limited = False
        if remaining is not None and (timeout is None or remaining < timeout):
            timeout = remaining
            deadline_limited = True

        remaining_budget = parent.budget_usd - spent_usd if parent.budget_usd is not None else None
        child = self._child_invocation(step, parent, input_text, timeout, remaining_budget)
        step_started = time.perf_counter()

        if decision.decision != "allow":
            await self._audit_step(
                child, step, input_text, None, "denied", "policy_denied", step_started
            )
            raise PlanDenied(f"agent {step.agent_ref.id!r} is not allowed")

        call = self.agents.get(step.agent_ref.id)
        if call is None:
            await self._audit_step(
                child, step, input_text, None, "error", "unknown_agent", step_started
            )
            raise UnknownAgent(f"agent {step.agent_ref.id!r} is not registered")

        for attempt in range(1, step.max_attempts + 1):
            attempt_started = time.perf_counter()
            try:
                result = await self._call_with_controls(call, child, step.id, timeout, cancel)
            except PlanCancelled:
                await self._audit_step(
                    child, step, input_text, None, "error", "cancelled", step_started
                )
                raise
            except StepTimeout:
                if deadline_limited:
                    await self._audit_step(
                        child, step, input_text, None, "error", "plan_timeout", step_started
                    )
                    raise PlanTimeout(f"plan deadline exceeded during step {step.id!r}") from None
                if attempt < step.max_attempts:
                    await self._audit_retry(
                        child, step, input_text, "StepTimeout", attempt, attempt_started
                    )
                    await self._retry_wait(step, input_text, child, cancel, step_started)
                    continue
                await self._audit_step(
                    child, step, input_text, None, "error", "StepTimeout", step_started
                )
                raise
            except Exception as exc:
                code = _error_code(exc)
                if attempt < step.max_attempts:
                    await self._audit_retry(child, step, input_text, code, attempt, attempt_started)
                    await self._retry_wait(step, input_text, child, cancel, step_started)
                    continue
                await self._audit_step(child, step, input_text, None, "error", code, step_started)
                raise PlanExecutionError(step.id, exc) from exc

            if step.budget_usd is not None and result.cost_usd > step.budget_usd:
                await self._audit_step(
                    child, step, input_text, None, "error", "budget_exceeded", step_started
                )
                raise BudgetExceeded(f"step {step.id!r} exceeded its budget", step_id=step.id)

            outputs[step.id] = result.text
            await self._audit_step(child, step, input_text, result.text, "ok", None, step_started)
            return result.cost_usd

        raise PlanExecutionError(step.id, RuntimeError("retry loop exhausted"))

    async def _retry_wait(
        self,
        step: PlanStep,
        input_text: str,
        child: Invocation,
        cancel: CancellationToken | None,
        step_started: float,
    ) -> None:
        try:
            await self._sleep_before_retry(step, cancel)
        except PlanCancelled:
            await self._audit_step(
                child, step, input_text, None, "error", "cancelled", step_started
            )
            raise

    async def _call_with_controls(
        self,
        call: AgentCall,
        child: Invocation,
        step_id: str,
        timeout: float | None,
        cancel: CancellationToken | None,
    ) -> InvocationResult:
        async def invoke() -> InvocationResult:
            return await call(child)

        task: asyncio.Task[InvocationResult] = asyncio.create_task(invoke())
        waiter: asyncio.Task[None] | None = (
            asyncio.create_task(cancel.wait()) if cancel is not None else None
        )
        waiters = {task, waiter} if waiter is not None else {task}
        try:
            done, _ = await asyncio.wait(
                waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        except asyncio.CancelledError:
            task.cancel()
            if waiter is not None:
                waiter.cancel()
            await asyncio.gather(
                task, *([waiter] if waiter is not None else []), return_exceptions=True
            )
            raise

        if not done:
            task.cancel()
            if waiter is not None:
                waiter.cancel()
            await asyncio.gather(
                task, *([waiter] if waiter is not None else []), return_exceptions=True
            )
            raise StepTimeout(step_id, timeout or 0.0)

        if task in done:
            if waiter is not None:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            return task.result()

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise PlanCancelled(f"plan cancelled during step {step_id!r}")

    async def _sleep_before_retry(self, step: PlanStep, cancel: CancellationToken | None) -> None:
        delay = step.retry_backoff_seconds
        if delay <= 0:
            self._check_cancelled(cancel)
            return
        if cancel is None:
            await asyncio.sleep(delay)
            return

        waiter = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait({waiter}, timeout=delay)
        finally:
            if not waiter.done():
                waiter.cancel()
            await asyncio.gather(waiter, return_exceptions=True)
        if done:
            raise PlanCancelled("plan cancelled during retry backoff")

    def _check_cancelled(self, cancel: CancellationToken | None) -> None:
        if cancel is not None and cancel.cancelled:
            raise PlanCancelled("plan cancelled")

    def _remaining_seconds(self, parent: Invocation) -> float | None:
        if parent.deadline is None:
            return None
        return (parent.deadline - datetime.now(timezone.utc)).total_seconds()

    def _check_deadline(self, parent: Invocation) -> None:
        remaining = self._remaining_seconds(parent)
        if remaining is not None and remaining <= 0:
            raise PlanTimeout("plan deadline exceeded")

    def _check_budget(self, parent: Invocation, spent_usd: float) -> None:
        if parent.budget_usd is not None and spent_usd >= parent.budget_usd:
            raise BudgetExceeded("plan budget exceeded")

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
        timeout: float | None,
        remaining_budget: float | None,
    ) -> Invocation:
        deadline = parent.deadline
        if timeout is not None:
            limit = datetime.now(timezone.utc) + timedelta(seconds=timeout)
            deadline = min(deadline, limit) if deadline is not None else limit

        budget = remaining_budget if remaining_budget is not None else parent.budget_usd
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

    async def _audit_retry(
        self,
        child: Invocation,
        step: PlanStep,
        input_text: str,
        error_code: str,
        attempt: int,
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
            action="orchestration.retry",
            target=f"{step.id}#{attempt}",
            args_hash=hash_text(input_text),
            result_hash=None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status="error",
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
