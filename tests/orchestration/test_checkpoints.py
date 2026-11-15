"""SLICE-111: sequential plans resume from the last completed step."""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime, timezone

import pytest

from adk_agent.core import (
    AgentRef,
    ApprovalDecision,
    ApprovalRequest,
    Invocation,
    InvocationResult,
    OrchestrationPlan,
    PlanStep,
    Principal,
    plan_digest,
)
from adk_agent.orchestration import (
    AgentGrantPolicyEngine,
    ApprovalRequired,
    CallbackApprovalGate,
    CheckpointCorrupt,
    CheckpointTerminal,
    InMemoryCheckpointStore,
    PlanExecutionError,
    PlanExecutor,
    RunCheckpoint,
)

_DIGEST = "d" * 64


class Recorder:
    def __init__(self, fail_at: int | None = None) -> None:
        self.calls: list[Invocation] = []
        self.fail_at = fail_at

    async def call(self, invocation: Invocation) -> InvocationResult:
        self.calls.append(invocation)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RuntimeError("process stopped")
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=f"out:{invocation.input}",
        )


def _ref(name: str = "worker") -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _parent() -> Invocation:
    return Invocation(
        run_id="run-1",
        trace_id="trace-1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=_ref("flow"),
        input="root",
    )


def _plan() -> OrchestrationPlan:
    return OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="sequential",
        steps=[
            PlanStep(id="a", agent_ref=_ref(), input="one"),
            PlanStep(
                id="b",
                agent_ref=_ref(),
                depends_on=["a"],
                inputs_from=["a"],
                input="two",
            ),
            PlanStep(
                id="c",
                agent_ref=_ref(),
                depends_on=["b"],
                inputs_from=["b"],
                input="three",
                max_attempts=1,
            ),
        ],
    )


def _executor(recorder: Recorder, store: InMemoryCheckpointStore) -> PlanExecutor:
    return PlanExecutor(
        {"worker": recorder.call},
        policy=AgentGrantPolicyEngine(["worker"]),
        checkpoints=store,
    )


def test_resume_after_failure() -> None:
    plan = _plan()
    store = InMemoryCheckpointStore()
    failing = Recorder(fail_at=3)

    with pytest.raises(PlanExecutionError):
        asyncio.run(_executor(failing, store).run(plan, _parent()))

    checkpoint = asyncio.run(store.load("t1", "run-1"))
    assert checkpoint is not None
    assert checkpoint.status == "failed"
    assert checkpoint.completed_steps == ["a", "b"]
    assert set(checkpoint.outputs) == {"a", "b"}

    resumed = Recorder()
    result = asyncio.run(_executor(resumed, store).run(plan, _parent()))

    assert len(resumed.calls) == 1
    assert resumed.calls[0].input.startswith("three")
    assert set(result.outputs) == {"a", "b", "c"}
    assert result.run_id == "run-1"

    finished = asyncio.run(store.load("t1", "run-1"))
    assert finished is not None
    assert finished.status == "completed"
    assert finished.completed_steps == ["a", "b", "c"]

    again = Recorder()
    repeated = asyncio.run(_executor(again, store).run(plan, _parent()))
    assert again.calls == []
    assert repeated.outputs == result.outputs


def test_approval_wait_resumes() -> None:
    plan = OrchestrationPlan(
        plan_id="flow",
        version="1.0.0",
        strategy="sequential",
        steps=[
            PlanStep(
                id="a",
                agent_ref=_ref(),
                input="one",
                requires_approval=True,
                approval_reason="touches production",
            ),
            PlanStep(
                id="b",
                agent_ref=_ref(),
                depends_on=["a"],
                inputs_from=["a"],
                input="two",
            ),
        ],
    )
    store = InMemoryCheckpointStore()

    with pytest.raises(ApprovalRequired):
        asyncio.run(_executor(Recorder(), store).run(plan, _parent()))

    waiting = asyncio.run(store.load("t1", "run-1"))
    assert waiting is not None
    assert waiting.status == "waiting_approval"
    assert waiting.waiting_step == "a"

    def approve(request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(
            request_id=request.request_id,
            approved=True,
            approver="alice",
            reason="ok",
            decided_at=datetime.now(timezone.utc),
        )

    recorder = Recorder()
    result = asyncio.run(
        _executor(recorder, store).run(plan, _parent(), approvals=CallbackApprovalGate(approve))
    )

    assert len(recorder.calls) == 2
    assert set(result.outputs) == {"a", "b"}


def _checkpoint(status: str, *, plan_digest_value: str | None = None) -> RunCheckpoint:
    return RunCheckpoint(
        tenant="t1",
        run_id="run-1",
        plan_id="flow",
        plan_version="1.0.0",
        plan_digest=plan_digest_value or plan_digest(_plan()),
        status=status,
        updated_at=datetime.now(timezone.utc),
    )


def test_cancelled_checkpoint_is_terminal() -> None:
    store = InMemoryCheckpointStore()
    asyncio.run(store.save(_checkpoint("cancelled")))

    with pytest.raises(CheckpointTerminal):
        asyncio.run(_executor(Recorder(), store).run(_plan(), _parent()))


def test_plan_digest_mismatch_fails_closed() -> None:
    store = InMemoryCheckpointStore()
    asyncio.run(store.save(_checkpoint("running", plan_digest_value="f" * 64)))

    with pytest.raises(CheckpointCorrupt):
        asyncio.run(_executor(Recorder(), store).run(_plan(), _parent()))


def test_store_is_tenant_scoped() -> None:
    store = InMemoryCheckpointStore()
    asyncio.run(store.save(_checkpoint("running")))
    assert asyncio.run(store.load("t2", "run-1")) is None


def test_build_picks_in_memory() -> None:
    from adk_agent.orchestration import build_checkpoint_store

    assert isinstance(build_checkpoint_store(None), InMemoryCheckpointStore)
    assert isinstance(build_checkpoint_store(""), InMemoryCheckpointStore)


@pytest.mark.skipif(
    importlib.util.find_spec("asyncpg") is None,
    reason="asyncpg is not installed",
)
def test_build_accepts_postgres() -> None:
    from adk_agent.orchestration import PostgresCheckpointStore, build_checkpoint_store

    assert isinstance(
        build_checkpoint_store("postgresql://u:p@localhost:5432/db"),
        PostgresCheckpointStore,
    )


def test_build_rejects_unknown_dsn() -> None:
    from adk_agent.orchestration import CheckpointStoreUnavailable, build_checkpoint_store

    with pytest.raises(CheckpointStoreUnavailable):
        build_checkpoint_store("sqlite:///checkpoints.db")
