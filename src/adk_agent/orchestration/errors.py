"""Plan execution failures."""

from __future__ import annotations


class PlanError(Exception):
    """Base class for orchestration failures."""


class PlanDenied(PlanError):
    """The policy engine denied an agent invocation."""


class UnknownAgent(PlanError):
    """The plan references an agent the executor cannot resolve."""


class PlanExecutionError(PlanError):
    def __init__(self, step_id: str, error: Exception) -> None:
        self.step_id = step_id
        self.error = error
        super().__init__(f"step {step_id!r} failed: {error}")
