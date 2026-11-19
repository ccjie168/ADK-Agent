"""Deterministic orchestration plans. The plan is data, not prompt logic."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .manifest import AgentRef
from .policy import RiskLevel

PlanStrategy = Literal["single", "sequential", "routing", "fan_out", "supervisor"]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class RouteWhen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    equals: str | None = None
    contains: str | None = None
    prefix: str | None = None

    @model_validator(mode="after")
    def _one_operator(self) -> RouteWhen:
        count = sum(value is not None for value in (self.equals, self.contains, self.prefix))
        if count != 1:
            raise ValueError("route_when needs exactly one of equals, contains, prefix")
        return self

    def matches(self, text: str) -> bool:
        if self.equals is not None:
            return text == self.equals
        if self.contains is not None:
            return self.contains in text
        return text.startswith(self.prefix or "")


class SupervisorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["call", "done"]
    worker: str | None = None
    input: str = ""
    final: str = ""

    @model_validator(mode="after")
    def _shape(self) -> SupervisorDecision:
        if self.action == "call" and not self.worker:
            raise ValueError("call needs a worker")
        if self.action == "done" and self.worker is not None:
            raise ValueError("done cannot name a worker")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, pattern=_SAFE_NAME.pattern)
    agent_ref: AgentRef
    input: str = ""
    route_when: RouteWhen | None = None
    inputs_from: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    budget_usd: float | None = Field(default=None, ge=0)
    max_attempts: int = Field(default=1, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=0.0, ge=0, le=60)
    requires_approval: bool = False
    approval_reason: str = ""
    risk_level: RiskLevel | None = None

    @field_validator("depends_on", "inputs_from")
    @classmethod
    def _valid_references(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate step reference")
        for item in value:
            if not _SAFE_NAME.fullmatch(item):
                raise ValueError(f"invalid step reference {item!r}")
        return value


def _topological_order(steps: list[PlanStep]) -> list[PlanStep]:
    by_id = {step.id: step for step in steps}
    index = {step.id: position for position, step in enumerate(steps)}
    indegree = {step.id: len(set(step.depends_on)) for step in steps}
    children: dict[str, list[str]] = {step.id: [] for step in steps}
    for step in steps:
        for dependency in set(step.depends_on):
            children[dependency].append(step.id)

    ready = sorted(
        (step_id for step_id, degree in indegree.items() if degree == 0),
        key=lambda step_id: index[step_id],
    )
    ordered: list[PlanStep] = []
    while ready:
        current = ready.pop(0)
        ordered.append(by_id[current])
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
        ready.sort(key=lambda step_id: index[step_id])

    if len(ordered) != len(steps):
        raise ValueError("plan has a dependency cycle")
    return ordered


class OrchestrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str = Field(min_length=1, pattern=_SAFE_NAME.pattern)
    version: str = Field(min_length=1, pattern=_SAFE_NAME.pattern)
    strategy: PlanStrategy = "single"
    max_parallel: int = Field(default=1, ge=1, le=16)
    supervisor: AgentRef | None = None
    max_rounds: int = Field(default=5, ge=1, le=20)
    steps: list[PlanStep] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_graph(self) -> OrchestrationPlan:
        step_ids = [step.id for step in self.steps]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("duplicate step id")
        known = set(step_ids)
        for step in self.steps:
            if step.id in step.depends_on:
                raise ValueError(f"step {step.id!r} depends on itself")
            for dependency in step.depends_on:
                if dependency not in known:
                    raise ValueError(f"unknown dependency {dependency!r}")
            for source in step.inputs_from:
                if source not in known:
                    raise ValueError(f"unknown input source {source!r}")
                if source not in step.depends_on:
                    raise ValueError(f"input source {source!r} is not a dependency")

        if self.strategy == "single":
            if len(self.steps) != 1:
                raise ValueError("single strategy needs exactly one step")
            if self.steps[0].depends_on or self.steps[0].inputs_from:
                raise ValueError("single strategy step cannot have dependencies")

        if self.strategy != "routing":
            for step in self.steps:
                if step.route_when is not None:
                    raise ValueError("route_when is only allowed for routing plans")

        if self.strategy == "routing":
            if any(step.depends_on or step.inputs_from for step in self.steps):
                raise ValueError("routing steps cannot have dependencies")
            defaults = [
                position for position, step in enumerate(self.steps) if step.route_when is None
            ]
            if len(defaults) > 1:
                raise ValueError("routing allows at most one default step")
            if defaults and defaults[0] != len(self.steps) - 1:
                raise ValueError("routing default step must be last")

        if self.strategy == "fan_out":
            sinks = [
                step.id
                for step in self.steps
                if not any(step.id in other.depends_on for other in self.steps)
            ]
            if len(sinks) != 1:
                raise ValueError("fan_out needs exactly one sink")

        if self.strategy == "supervisor":
            if self.supervisor is None:
                raise ValueError("supervisor strategy needs a supervisor")
            worker_ids = {step.id for step in self.steps}
            worker_agents = {step.agent_ref.id for step in self.steps}
            if self.supervisor.id in worker_ids or self.supervisor.id in worker_agents:
                raise ValueError("supervisor id must differ from worker ids")
            if any(step.depends_on or step.inputs_from for step in self.steps):
                raise ValueError("supervisor workers cannot have dependencies")
        elif self.supervisor is not None:
            raise ValueError("supervisor is only allowed for supervisor plans")

        _topological_order(self.steps)
        return self

    def order(self) -> list[PlanStep]:
        return _topological_order(self.steps)


class PlanResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    plan_id: str
    version: str
    run_id: str
    trace_id: str
    outputs: dict[str, str] = Field(default_factory=dict)
    final_text: str = ""
    cost_usd: float = Field(default=0.0, ge=0)


class TraceNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: Literal["plan", "step", "supervisor", "approval"]
    status: Literal["ok", "error", "denied"]
    error_code: str | None = None
    latency_ms: int | None = None
    cost_usd: float | None = None
    children: list[TraceNode] = Field(default_factory=list)


def plan_digest(plan: OrchestrationPlan) -> str:
    """Hash the plan's canonical JSON. The digest is not part of the plan."""
    payload = plan.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_ref(plan: OrchestrationPlan) -> AgentRef:
    return AgentRef(id=plan.plan_id, version=plan.version, digest=plan_digest(plan))


TraceNode.model_rebuild()
