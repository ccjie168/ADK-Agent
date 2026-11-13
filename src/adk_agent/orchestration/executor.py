"""Deterministic executor with retries, timeouts, budget checks, and cancellation."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from ..audit.hashing import hash_text
from ..core import (
    AgentRef,
    ApprovalDecision,
    ApprovalGate,
    ApprovalRequest,
    AuditEvent,
    AuditSink,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanResult,
    PlanStep,
    PolicyEngine,
    QuotaExceeded,
    QuotaManager,
    QuotaPolicy,
    SupervisorDecision,
    plan_ref,
)
from ..metrics import MetricsRegistry
from .cancel import CancellationToken
from .errors import (
    ApprovalDenied,
    ApprovalProtocolError,
    ApprovalRequired,
    ApprovalTimeout,
    BudgetExceeded,
    NoRoute,
    PlanCancelled,
    PlanDenied,
    PlanExecutionError,
    PlanTimeout,
    StepTimeout,
    SupervisorLimit,
    SupervisorProtocolError,
    UnknownAgent,
)

AgentCall = Callable[[Invocation], Awaitable[InvocationResult]]
Status = Literal["ok", "error", "denied"]


def _error_code(error: BaseException) -> str:
    if isinstance(error, PlanDenied):
        return "policy_denied"
    if isinstance(error, UnknownAgent):
        return "unknown_agent"
    if isinstance(error, NoRoute):
        return "no_route"
    if isinstance(error, PlanCancelled):
        return "cancelled"
    if isinstance(error, PlanTimeout):
        return "plan_timeout"
    if isinstance(error, StepTimeout):
        return "StepTimeout"
    if isinstance(error, BudgetExceeded):
        return "budget_exceeded"
    if isinstance(error, ApprovalRequired):
        return "approval_required"
    if isinstance(error, ApprovalDenied):
        return "approval_denied"
    if isinstance(error, ApprovalTimeout):
        return "approval_timeout"
    if isinstance(error, ApprovalProtocolError):
        return "approval_protocol"
    if isinstance(error, SupervisorProtocolError):
        return "supervisor_protocol"
    if isinstance(error, SupervisorLimit):
        return "round_limit"
    if isinstance(error, QuotaExceeded):
        return "quota_exceeded"
    if isinstance(error, PlanExecutionError):
        return getattr(error.error, "error_code", type(error.error).__name__)
    return getattr(error, "error_code", type(error).__name__)


class PlanExecutor:
    def __init__(
        self,
        agents: Mapping[str, AgentCall],
        policy: PolicyEngine,
        audit: AuditSink | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.agents = dict(agents)
        self.policy = policy
        self.audit = audit
        self.metrics = metrics

    async def run(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None = None,
        approvals: ApprovalGate | None = None,
        *,
        quota: QuotaManager | None = None,
        quota_policy: QuotaPolicy | None = None,
    ) -> PlanResult:
        started = time.perf_counter()
        try:
            if quota is None or quota_policy is None:
                result = await self._dispatch(plan, invocation, cancel, approvals)
            else:
                try:
                    async with quota.reserve(invocation.principal.tenant, quota_policy):
                        result = await self._dispatch(plan, invocation, cancel, approvals)
                except QuotaExceeded:
                    await self._audit_run(
                        invocation,
                        plan_ref(plan),
                        plan,
                        status="denied",
                        error_code="quota_exceeded",
                        result_text=None,
                        started=started,
                    )
                    raise
        except QuotaExceeded as exc:
            self._record_run(plan, invocation, "denied", started)
            self._record_quota_denial(invocation, exc.limit)
            raise
        except Exception:
            self._record_run(plan, invocation, "error", started)
            raise

        self._record_run(plan, invocation, "ok", started)
        return result

    def _record_run(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        status: str,
        started: float,
    ) -> None:
        if self.metrics is None:
            return
        tenant = invocation.principal.tenant
        self.metrics.inc(
            "adk_agent_plan_runs_total",
            {"plan": plan.plan_id, "tenant": tenant, "status": status},
        )
        self.metrics.observe(
            "adk_plan_duration_seconds",
            time.perf_counter() - started,
            {"plan": plan.plan_id, "tenant": tenant},
        )

    def _record_quota_denial(self, invocation: Invocation, limit: str) -> None:
        if self.metrics is None:
            return
        self.metrics.inc(
            "adk_agent_quota_denials_total",
            {"tenant": invocation.principal.tenant, "limit": limit},
        )

    async def _dispatch(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
    ) -> PlanResult:
        if plan.strategy == "routing":
            return await self._run_routing(plan, invocation, cancel, approvals)
        if plan.strategy == "fan_out":
            return await self._run_fan_out(plan, invocation, cancel, approvals)
        if plan.strategy == "supervisor":
            return await self._run_supervisor(plan, invocation, cancel, approvals)
        return await self._run_sequential(plan, invocation, cancel, approvals)

    async def _run_sequential(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
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
                spent_usd += await self._run_step(
                    step, invocation, outputs, spent_usd, cancel, approvals=approvals
                )
                if invocation.budget_usd is not None and spent_usd > invocation.budget_usd:
                    raise BudgetExceeded("plan budget exceeded")
        except Exception as exc:
            status: Status = (
                "denied"
                if isinstance(exc, (PlanDenied, BudgetExceeded, ApprovalDenied, ApprovalRequired))
                else "error"
            )
            await self._audit_run(
                invocation,
                reference,
                plan,
                status=status,
                error_code=_error_code(exc),
                result_text=None,
                started=started,
                cost_usd=spent_usd,
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
            cost_usd=spent_usd,
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

    async def _run_routing(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
    ) -> PlanResult:
        started = time.perf_counter()
        reference = plan_ref(plan)
        step = self._select_route(plan, invocation.input)
        if step is None:
            await self._audit_run(
                invocation,
                reference,
                plan,
                status="error",
                error_code="no_route",
                result_text=None,
                started=started,
            )
            raise NoRoute(f"no route matched plan {plan.plan_id!r}")

        outputs: dict[str, str] = {}
        spent_usd = 0.0
        try:
            self._check_cancelled(cancel)
            self._check_deadline(invocation)
            self._check_budget(invocation, 0.0)
            spent_usd = await self._run_step(
                step, invocation, outputs, 0.0, cancel, approvals=approvals
            )
        except Exception as exc:
            status: Status = (
                "denied"
                if isinstance(exc, (PlanDenied, BudgetExceeded, ApprovalDenied, ApprovalRequired))
                else "error"
            )
            await self._audit_run(
                invocation,
                reference,
                plan,
                status=status,
                error_code=_error_code(exc),
                result_text=None,
                started=started,
                cost_usd=spent_usd,
            )
            raise

        final_text = outputs[step.id]
        await self._audit_run(
            invocation,
            reference,
            plan,
            status="ok",
            error_code=None,
            result_text=final_text,
            started=started,
            cost_usd=spent_usd,
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

    async def _run_fan_out(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
    ) -> PlanResult:
        started = time.perf_counter()
        reference = plan_ref(plan)
        outputs: dict[str, str] = {}
        spent_usd = 0.0
        completed: set[str] = set()
        pending = list(plan.order())

        try:
            while pending:
                self._check_cancelled(cancel)
                self._check_deadline(invocation)
                self._check_budget(invocation, spent_usd)
                ready = [
                    step
                    for step in pending
                    if all(dependency in completed for dependency in step.depends_on)
                ]
                if not ready:
                    raise PlanExecutionError("plan", RuntimeError("no ready steps"))
                batch = ready[: plan.max_parallel]
                for step, cost in await self._run_batch(
                    batch, invocation, outputs, spent_usd, cancel, approvals
                ):
                    spent_usd += cost
                    completed.add(step.id)
                    if invocation.budget_usd is not None and spent_usd > invocation.budget_usd:
                        raise BudgetExceeded("plan budget exceeded")
                pending = [step for step in pending if step.id not in completed]
        except Exception as exc:
            status: Status = (
                "denied"
                if isinstance(exc, (PlanDenied, BudgetExceeded, ApprovalDenied, ApprovalRequired))
                else "error"
            )
            await self._audit_run(
                invocation,
                reference,
                plan,
                status=status,
                error_code=_error_code(exc),
                result_text=None,
                started=started,
                cost_usd=spent_usd,
            )
            raise

        final_text = outputs.get(self._sink_id(plan), "")
        await self._audit_run(
            invocation,
            reference,
            plan,
            status="ok",
            error_code=None,
            result_text=final_text,
            started=started,
            cost_usd=spent_usd,
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

    async def _run_batch(
        self,
        batch: list[PlanStep],
        parent: Invocation,
        outputs: dict[str, str],
        spent_usd: float,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
    ) -> list[tuple[PlanStep, float]]:
        if len(batch) == 1:
            step = batch[0]
            cost = await self._run_step(
                step, parent, outputs, spent_usd, cancel, approvals=approvals
            )
            return [(step, cost)]

        tasks = [
            asyncio.create_task(
                self._run_step(step, parent, outputs, spent_usd, cancel, approvals=approvals)
            )
            for step in batch
        ]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        for result in results:
            if isinstance(result, BaseException):
                raise result
        costs = cast(list[float], results)
        return list(zip(batch, costs, strict=True))

    def _select_route(self, plan: OrchestrationPlan, text: str) -> PlanStep | None:
        for step in plan.steps:
            if step.route_when is None or step.route_when.matches(text):
                return step
        return None

    def _sink_id(self, plan: OrchestrationPlan) -> str:
        for step in plan.steps:
            if not any(step.id in other.depends_on for other in plan.steps):
                return step.id
        raise PlanExecutionError("plan", RuntimeError("fan_out plan has no sink"))

    async def _run_supervisor(
        self,
        plan: OrchestrationPlan,
        invocation: Invocation,
        cancel: CancellationToken | None,
        approvals: ApprovalGate | None,
    ) -> PlanResult:
        started = time.perf_counter()
        reference = plan_ref(plan)
        supervisor = plan.supervisor
        if supervisor is None:
            raise PlanExecutionError("plan", RuntimeError("supervisor missing"))
        outputs: dict[str, str] = {}
        history: list[tuple[str, str, str]] = []
        spent_usd = 0.0

        try:
            for round_no in range(1, plan.max_rounds + 1):
                self._check_cancelled(cancel)
                self._check_deadline(invocation)
                self._check_budget(invocation, spent_usd)
                state = self._supervisor_state(plan, invocation, history, round_no)
                decision, supervisor_cost = await self._supervisor_decision(
                    plan, invocation, state, round_no, spent_usd, cancel
                )
                spent_usd += supervisor_cost
                if invocation.budget_usd is not None and spent_usd > invocation.budget_usd:
                    raise BudgetExceeded("plan budget exceeded")

                if decision.action == "done":
                    final_text = decision.final or (history[-1][2] if history else "")
                    await self._audit_run(
                        invocation,
                        reference,
                        plan,
                        status="ok",
                        error_code=None,
                        result_text=final_text,
                        started=started,
                        cost_usd=spent_usd,
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

                worker = self._worker_for(plan, decision.worker or "")
                if worker is None:
                    raise SupervisorProtocolError(f"unknown worker {decision.worker!r}")
                worker_input = decision.input or invocation.input
                output_key = f"{worker.id}#{round_no}"
                spent_usd += await self._run_step(
                    worker,
                    invocation,
                    outputs,
                    spent_usd,
                    cancel,
                    input_override=worker_input,
                    output_key=output_key,
                    approvals=approvals,
                )
                history.append((worker.id, worker_input, outputs[output_key]))
                if invocation.budget_usd is not None and spent_usd > invocation.budget_usd:
                    raise BudgetExceeded("plan budget exceeded")

            raise SupervisorLimit(f"plan {plan.plan_id!r} exceeded {plan.max_rounds} rounds")
        except Exception as exc:
            status: Status = (
                "denied"
                if isinstance(exc, (PlanDenied, BudgetExceeded, ApprovalDenied, ApprovalRequired))
                else "error"
            )
            await self._audit_run(
                invocation,
                reference,
                plan,
                status=status,
                error_code=_error_code(exc),
                result_text=None,
                started=started,
                cost_usd=spent_usd,
            )
            raise

    async def _supervisor_decision(
        self,
        plan: OrchestrationPlan,
        parent: Invocation,
        state: str,
        round_no: int,
        spent_usd: float,
        cancel: CancellationToken | None,
    ) -> tuple[SupervisorDecision, float]:
        supervisor = plan.supervisor
        if supervisor is None:
            raise PlanExecutionError("plan", RuntimeError("supervisor missing"))
        decision = await self.policy.decide(parent, "agent.invoke", supervisor.id)
        child = self._supervisor_invocation(supervisor, parent, state, spent_usd)
        started = time.perf_counter()

        if decision.decision != "allow":
            await self._audit_supervisor(
                child,
                supervisor,
                round_no,
                state,
                None,
                "denied",
                "policy_denied",
                started,
            )
            raise PlanDenied(f"agent {supervisor.id!r} is not allowed")

        call = self.agents.get(supervisor.id)
        if call is None:
            await self._audit_supervisor(
                child,
                supervisor,
                round_no,
                state,
                None,
                "error",
                "unknown_agent",
                started,
            )
            raise UnknownAgent(f"agent {supervisor.id!r} is not registered")

        try:
            result = await self._call_with_controls(
                call, child, supervisor.id, self._remaining_seconds(parent), cancel
            )
        except PlanCancelled:
            await self._audit_supervisor(
                child, supervisor, round_no, state, None, "error", "cancelled", started
            )
            raise
        except StepTimeout:
            await self._audit_supervisor(
                child, supervisor, round_no, state, None, "error", "plan_timeout", started
            )
            raise PlanTimeout("plan deadline exceeded during supervisor call") from None
        except Exception as exc:
            code = _error_code(exc)
            await self._audit_supervisor(
                child, supervisor, round_no, state, None, "error", code, started
            )
            raise PlanExecutionError("supervisor", exc) from exc

        try:
            parsed = SupervisorDecision.model_validate_json(result.text)
        except ValueError as exc:
            await self._audit_supervisor(
                child,
                supervisor,
                round_no,
                state,
                None,
                "error",
                "supervisor_protocol",
                started,
            )
            raise SupervisorProtocolError(f"invalid supervisor decision: {exc}") from exc

        await self._audit_supervisor(
            child,
            supervisor,
            round_no,
            state,
            result.text,
            "ok",
            None,
            started,
            cost_usd=result.cost_usd,
        )
        return parsed, result.cost_usd

    def _supervisor_invocation(
        self,
        supervisor: AgentRef,
        parent: Invocation,
        state: str,
        spent_usd: float,
    ) -> Invocation:
        budget = parent.budget_usd - spent_usd if parent.budget_usd is not None else None
        return Invocation(
            run_id=uuid.uuid4().hex,
            trace_id=parent.trace_id,
            principal=parent.principal,
            agent_ref=supervisor,
            input=state,
            deadline=parent.deadline,
            budget_usd=budget,
        )

    def _supervisor_state(
        self,
        plan: OrchestrationPlan,
        parent: Invocation,
        history: list[tuple[str, str, str]],
        round_no: int,
    ) -> str:
        lines = [
            f"Task: {parent.input}",
            f"Round: {round_no}/{plan.max_rounds}",
            "Workers: " + ", ".join(step.id for step in plan.steps),
            'Reply with JSON: {"action":"call","worker":"<id>","input":"..."} '
            'or {"action":"done","final":"..."}.',
        ]
        if history:
            lines.append("History:")
            for index, (worker, text, output) in enumerate(history, start=1):
                lines.append(f"[{index}] worker={worker} input={text!r} output={output!r}")
        return "\n".join(lines)

    def _worker_for(self, plan: OrchestrationPlan, worker_id: str) -> PlanStep | None:
        for step in plan.steps:
            if step.id == worker_id:
                return step
        return None

    async def _audit_supervisor(
        self,
        child: Invocation,
        supervisor: AgentRef,
        round_no: int,
        input_text: str,
        output_text: str | None,
        status: Status,
        error_code: str | None,
        started: float,
        *,
        cost_usd: float | None = None,
    ) -> None:
        if self.audit is None:
            return
        event = AuditEvent(
            event_id=uuid.uuid4().hex,
            run_id=child.run_id,
            trace_id=child.trace_id,
            tenant=child.principal.tenant,
            principal=child.principal,
            agent_ref=supervisor,
            action="orchestration.supervisor",
            target=f"round:{round_no}",
            args_hash=hash_text(input_text),
            result_hash=hash_text(output_text) if output_text is not None else None,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=cost_usd,
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)

    async def _run_step(
        self,
        step: PlanStep,
        parent: Invocation,
        outputs: dict[str, str],
        spent_usd: float,
        cancel: CancellationToken | None,
        *,
        input_override: str | None = None,
        output_key: str | None = None,
        approvals: ApprovalGate | None = None,
    ) -> float:
        decision = await self.policy.decide(parent, "agent.invoke", step.agent_ref.id)
        input_text = (
            input_override
            if input_override is not None
            else self._step_input(step, parent, outputs)
        )
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

        if step.requires_approval:
            await self._require_approval(
                step, child, input_text, approvals, remaining, cancel, step_started
            )

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

            outputs[output_key or step.id] = result.text
            await self._audit_step(
                child,
                step,
                input_text,
                result.text,
                "ok",
                None,
                step_started,
                cost_usd=result.cost_usd,
            )
            return result.cost_usd

        raise PlanExecutionError(step.id, RuntimeError("retry loop exhausted"))

    async def _require_approval(
        self,
        step: PlanStep,
        child: Invocation,
        input_text: str,
        approvals: ApprovalGate | None,
        timeout: float | None,
        cancel: CancellationToken | None,
        step_started: float,
    ) -> None:
        requested_at = datetime.now(timezone.utc)
        request = ApprovalRequest(
            request_id=uuid.uuid4().hex,
            run_id=child.run_id,
            trace_id=child.trace_id,
            step_id=step.id,
            agent_ref=step.agent_ref,
            principal=child.principal,
            input=input_text,
            reason=step.approval_reason,
            requested_at=requested_at,
            expires_at=(requested_at + timedelta(seconds=timeout) if timeout is not None else None),
        )
        if approvals is None:
            await self._audit_step(
                child, step, input_text, None, "denied", "approval_required", step_started
            )
            raise ApprovalRequired(f"step {step.id!r} needs approval")

        started = time.perf_counter()
        try:
            decision = await self._await_approval(approvals, request, timeout, cancel)
        except PlanCancelled:
            await self._audit_step(
                child, step, input_text, None, "error", "cancelled", step_started
            )
            raise
        except ApprovalTimeout:
            await self._audit_step(
                child, step, input_text, None, "error", "approval_timeout", step_started
            )
            raise
        except Exception as exc:
            await self._audit_step(
                child, step, input_text, None, "error", _error_code(exc), step_started
            )
            raise PlanExecutionError("approval", exc) from exc

        if decision.request_id != request.request_id:
            await self._audit_approval(
                child,
                step,
                input_text,
                decision,
                request.request_id,
                "denied",
                "approval_protocol",
                started,
            )
            await self._audit_step(
                child, step, input_text, None, "error", "approval_protocol", step_started
            )
            raise ApprovalProtocolError("approval response does not match request")

        if not decision.approved:
            await self._audit_approval(
                child,
                step,
                input_text,
                decision,
                request.request_id,
                "denied",
                "approval_denied",
                started,
            )
            await self._audit_step(
                child, step, input_text, None, "denied", "approval_denied", step_started
            )
            raise ApprovalDenied(f"step {step.id!r} was not approved")

        await self._audit_approval(
            child,
            step,
            input_text,
            decision,
            request.request_id,
            "ok",
            None,
            started,
        )

    async def _await_approval(
        self,
        gate: ApprovalGate,
        request: ApprovalRequest,
        timeout: float | None,
        cancel: CancellationToken | None,
    ) -> ApprovalDecision:
        async def invoke() -> ApprovalDecision:
            return await gate.request(request)

        task: asyncio.Task[ApprovalDecision] = asyncio.create_task(invoke())
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
            raise ApprovalTimeout(f"approval for step {request.step_id!r} timed out")

        if task in done:
            if waiter is not None:
                waiter.cancel()
                await asyncio.gather(waiter, return_exceptions=True)
            return task.result()

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise PlanCancelled(f"plan cancelled during approval for step {request.step_id!r}")

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

    async def _audit_approval(
        self,
        child: Invocation,
        step: PlanStep,
        input_text: str,
        decision: ApprovalDecision,
        request_id: str,
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
            approver=decision.approver,
            agent_ref=step.agent_ref,
            action="orchestration.approval",
            target=step.id,
            args_hash=hash_text(input_text),
            result_hash=None,
            policy_decision_id=request_id,
            data_classes=[],
            latency_ms=int((time.perf_counter() - started) * 1000),
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)

    async def _audit_step(
        self,
        child: Invocation,
        step: PlanStep,
        input_text: str,
        output_text: str | None,
        status: Status,
        error_code: str | None,
        started: float,
        *,
        cost_usd: float | None = None,
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
            cost_usd=cost_usd,
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
        cost_usd: float | None = None,
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
            cost_usd=cost_usd,
            egress="none",
            status=status,
            error_code=error_code,
            timestamp=datetime.now(timezone.utc),
        )
        await self.audit.emit(event)
