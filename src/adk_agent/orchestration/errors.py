"""Plan execution failures."""

from __future__ import annotations


class PlanError(Exception):
    """Base class for orchestration failures."""


class PlanDenied(PlanError):
    """The policy engine denied an agent invocation."""


class UnknownAgent(PlanError):
    """The plan references an agent the executor cannot resolve."""


class NoRoute(PlanError):
    """No routing step matched the input and there is no default."""


class SupervisorProtocolError(PlanError):
    error_code = "supervisor_protocol"


class SupervisorLimit(PlanError):
    error_code = "round_limit"


class PlanCancelled(PlanError):
    """The caller cancelled the plan."""


class PlanTimeout(PlanError):
    """The plan deadline expired."""


class StepTimeout(PlanError):
    def __init__(self, step_id: str, timeout_seconds: float) -> None:
        self.step_id = step_id
        self.timeout_seconds = timeout_seconds
        super().__init__(f"step {step_id!r} exceeded {timeout_seconds}s")


class BudgetExceeded(PlanError):
    def __init__(self, message: str, step_id: str | None = None) -> None:
        self.step_id = step_id
        super().__init__(message)


class PlanExecutionError(PlanError):
    def __init__(self, step_id: str, error: Exception) -> None:
        self.step_id = step_id
        self.error = error
        super().__init__(f"step {step_id!r} failed: {error}")
