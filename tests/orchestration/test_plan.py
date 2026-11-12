"""SLICE-023: orchestration plans are validated data with a stable digest."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentRef,
    OrchestrationPlan,
    PlanStep,
    plan_digest,
    plan_ref,
)

_DIGEST = "d" * 64


def _ref(name: str = "worker") -> AgentRef:
    return AgentRef(id=name, version="1.0.0", digest=_DIGEST)


def _step(step_id: str, agent: str = "worker", **overrides) -> PlanStep:
    data = {"id": step_id, "agent_ref": _ref(agent)}
    data.update(overrides)
    return PlanStep(**data)


def _plan(steps, strategy: str = "sequential", **overrides) -> OrchestrationPlan:
    data = {
        "plan_id": "flow",
        "version": "1.0.0",
        "strategy": strategy,
        "steps": steps,
    }
    data.update(overrides)
    return OrchestrationPlan(**data)


def test_plan_roundtrip_and_digest():
    plan = _plan([_step("a", input="hello")], strategy="single")
    clone = OrchestrationPlan.model_validate_json(plan.model_dump_json())
    assert clone == plan
    assert len(plan_digest(plan)) == 64
    assert plan_digest(plan) == plan_digest(clone)
    assert plan_digest(plan) != plan_digest(_plan([_step("a", input="other")], strategy="single"))


def test_plan_ref_uses_digest():
    plan = _plan([_step("a")], strategy="single")
    ref = plan_ref(plan)
    assert ref.id == "flow"
    assert ref.version == "1.0.0"
    assert ref.digest == plan_digest(plan)


def test_duplicate_step_ids_rejected():
    with pytest.raises(ValidationError):
        _plan([_step("a"), _step("a")])


def test_unknown_dependency_rejected():
    with pytest.raises(ValidationError):
        _plan([_step("a", depends_on=["missing"])])


def test_cycle_rejected():
    with pytest.raises(ValidationError):
        _plan(
            [
                _step("a", depends_on=["b"]),
                _step("b", depends_on=["a"]),
            ]
        )


def test_inputs_from_must_be_dependency():
    with pytest.raises(ValidationError):
        _plan([_step("a"), _step("b", inputs_from=["a"])])


def test_single_strategy_shape():
    with pytest.raises(ValidationError):
        _plan([_step("a"), _step("b")], strategy="single")
    with pytest.raises(ValidationError):
        _plan([_step("a", depends_on=["a"])], strategy="single")


def test_order_is_stable():
    plan = _plan(
        [
            _step("c", depends_on=["b"]),
            _step("a"),
            _step("b", depends_on=["a"]),
            _step("d"),
        ]
    )
    assert [step.id for step in plan.order()] == ["a", "b", "c", "d"]


def test_order_keeps_declaration_order_for_independent_steps():
    plan = _plan([_step("b"), _step("a")])
    assert [step.id for step in plan.order()] == ["b", "a"]
