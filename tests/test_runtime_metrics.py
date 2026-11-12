"""SLICE-047: runtime and plan executor metrics."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import (
    AgentRef,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    QuotaExceeded,
    QuotaPolicy,
)
from adk_agent.metrics import MetricsRegistry
from adk_agent.orchestration import AgentGrantPolicyEngine, PlanExecutor
from adk_agent.runtime import AgentRuntime
from adk_agent.runtime.quota import InMemoryQuotaManager

_DIGEST = "d" * 64


class FakePart:
    def __init__(self, text: str) -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, text: str) -> None:
        self.parts = [FakePart(text)]


class FakeEvent:
    def __init__(self, text: str) -> None:
        self.content = FakeContent(text)

    def is_final_response(self) -> bool:
        return True


class OkRunner:
    async def run_async(self, **kwargs):
        yield FakeEvent("ok")


class FailRunner:
    async def run_async(self, **kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover


class Recorder:
    async def __call__(self, invocation: Invocation) -> InvocationResult:
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.input}",
        )


def _ref(name: str = "probe") -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _invocation(tenant: str = "acme") -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=_ref(),
        input="hello",
    )


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="single",
        steps=[PlanStep(id="a", agent_ref=_ref("worker"))],
    )


def _executor(metrics: MetricsRegistry) -> PlanExecutor:
    return PlanExecutor(
        {"worker": Recorder()},
        policy=AgentGrantPolicyEngine(["worker"]),
        metrics=metrics,
    )


def test_runtime_counts_ok_and_error():
    metrics = MetricsRegistry()
    runtime = AgentRuntime(OkRunner(), metrics=metrics, source="test")

    asyncio.run(runtime.run(_invocation(), user_id="u", session_id="s"))
    with pytest.raises(RuntimeError):
        asyncio.run(
            AgentRuntime(FailRunner(), metrics=metrics, source="test").run(
                _invocation(), user_id="u", session_id="s"
            )
        )

    text = metrics.render()
    assert 'adk_agent_runs_total{agent="probe",source="test",status="ok",tenant="acme"} 1' in text
    assert (
        'adk_agent_runs_total{agent="probe",source="test",status="error",tenant="acme"} 1' in text
    )
    assert 'adk_agent_run_duration_seconds_count{agent="probe",tenant="acme"} 2' in text


def test_plan_executor_counts_runs():
    metrics = MetricsRegistry()

    asyncio.run(_executor(metrics).run(_plan(), _invocation()))

    text = metrics.render()
    assert 'adk_agent_plan_runs_total{plan="flow",status="ok",tenant="acme"} 1' in text
    assert 'adk_plan_duration_seconds_count{plan="flow",tenant="acme"} 1' in text


def test_plan_quota_denial_counts():
    metrics = MetricsRegistry()
    executor = _executor(metrics)
    quota = InMemoryQuotaManager()
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    async def scenario() -> None:
        await executor.run(_plan(), _invocation(), quota=quota, quota_policy=policy)
        with pytest.raises(QuotaExceeded):
            await executor.run(_plan(), _invocation(), quota=quota, quota_policy=policy)

    asyncio.run(scenario())

    text = metrics.render()
    assert 'adk_agent_plan_runs_total{plan="flow",status="denied",tenant="acme"} 1' in text
    assert 'adk_agent_quota_denials_total{limit="max_runs",tenant="acme"} 1' in text


def test_runtime_without_metrics_is_unaffected():
    runtime = AgentRuntime(OkRunner())
    result = asyncio.run(runtime.run(_invocation(), user_id="u", session_id="s"))
    assert result.text == "ok"
