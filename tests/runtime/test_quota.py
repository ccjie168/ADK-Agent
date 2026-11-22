"""SLICE-028: per-tenant quotas."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from adk_agent.core import AgentRef, Invocation, Principal, QuotaPolicy
from adk_agent.runtime import AgentRuntime
from adk_agent.runtime.quota import InMemoryQuotaManager, QuotaExceeded


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakePart:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.thought = False


class FakeContent:
    def __init__(self, parts) -> None:
        self.parts = parts


class FakeEvent:
    def __init__(self, parts) -> None:
        self.content = FakeContent(parts)

    def is_final_response(self) -> bool:
        return True


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run_async(self, **kwargs):
        self.calls += 1
        yield FakeEvent([FakePart("ok")])


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


async def _consume(
    manager: InMemoryQuotaManager,
    tenant: str,
    policy: QuotaPolicy,
    times: int,
) -> None:
    for _ in range(times):
        async with manager.reserve(tenant, policy):
            pass


def _invocation(tenant: str = "t1") -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant=tenant, subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="hello",
    )


def test_policy_requires_a_limit():
    with pytest.raises(ValidationError):
        QuotaPolicy()
    with pytest.raises(ValidationError):
        QuotaPolicy(max_runs=0)
    with pytest.raises(ValidationError):
        QuotaPolicy(max_concurrent=0)
    with pytest.raises(ValidationError):
        QuotaPolicy(max_runs=1, window_seconds=0)


def test_run_limit_exceeded():
    manager = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_runs=2, window_seconds=60)
    asyncio.run(_consume(manager, "t1", policy, 2))

    with pytest.raises(QuotaExceeded) as exc:
        asyncio.run(_consume(manager, "t1", policy, 1))
    assert exc.value.tenant == "t1"
    assert exc.value.limit == "max_runs"


def test_window_expiry_frees_slots():
    clock = Clock()
    manager = InMemoryQuotaManager(clock=clock)
    policy = QuotaPolicy(max_runs=1, window_seconds=60)
    asyncio.run(_consume(manager, "t1", policy, 1))

    clock.now += 61
    asyncio.run(_consume(manager, "t1", policy, 1))


def test_concurrency_limit_exceeded():
    manager = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_concurrent=1)

    async def scenario() -> None:
        async with manager.reserve("t1", policy):
            with pytest.raises(QuotaExceeded) as exc:
                async with manager.reserve("t1", policy):
                    pass
            assert exc.value.limit == "max_concurrent"

    asyncio.run(scenario())


def test_tenants_have_separate_quotas():
    manager = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_runs=1, window_seconds=60)
    asyncio.run(_consume(manager, "t1", policy, 1))

    asyncio.run(_consume(manager, "t2", policy, 1))
    with pytest.raises(QuotaExceeded):
        asyncio.run(_consume(manager, "t1", policy, 1))


def test_release_on_error():
    manager = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_concurrent=1)

    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            async with manager.reserve("t1", policy):
                raise RuntimeError("boom")
        async with manager.reserve("t1", policy):
            pass

    asyncio.run(scenario())


def test_failed_concurrency_check_does_not_consume_run_slot():
    manager = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_runs=2, max_concurrent=1, window_seconds=60)

    async def scenario() -> None:
        async with manager.reserve("t1", policy):
            with pytest.raises(QuotaExceeded):
                async with manager.reserve("t1", policy):
                    pass
        async with manager.reserve("t1", policy):
            pass
        with pytest.raises(QuotaExceeded):
            async with manager.reserve("t1", policy):
                pass

    asyncio.run(scenario())


def test_runtime_denies_over_quota():
    runner = FakeRunner()
    auditor = FakeAudit()
    runtime = AgentRuntime(runner, audit=auditor)
    quota = InMemoryQuotaManager(clock=Clock())
    policy = QuotaPolicy(max_runs=1, window_seconds=60)

    asyncio.run(
        runtime.run(
            _invocation(),
            user_id="u1",
            session_id="s1",
            quota=quota,
            quota_policy=policy,
        )
    )
    with pytest.raises(QuotaExceeded):
        asyncio.run(
            runtime.run(
                _invocation(),
                user_id="u1",
                session_id="s1",
                quota=quota,
                quota_policy=policy,
            )
        )

    assert runner.calls == 1
    last = auditor.events[-1]
    assert last.action == "agent.run"
    assert last.status == "denied"
    assert last.error_code == "quota_exceeded"


def test_runtime_without_quota_is_unlimited():
    runner = FakeRunner()
    runtime = AgentRuntime(runner)

    for _ in range(3):
        asyncio.run(runtime.run(_invocation(), user_id="u1", session_id="s1"))

    assert runner.calls == 3


def test_inmemory_quota_usage_reflects_runs():
    manager = InMemoryQuotaManager()
    policy = QuotaPolicy(max_runs=2, window_seconds=60)

    before = asyncio.run(manager.usage("t1", policy))
    assert before.window_runs == 0
    assert before.active_leases == 0

    async def _reserve_once() -> Any:
        async with manager.reserve("t1", policy):
            return await manager.usage("t1", policy)

    during = asyncio.run(_reserve_once())
    assert during.window_runs == 1
    assert during.max_runs == 2
    assert during.window_seconds == 60
