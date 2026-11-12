"""Run deterministic eval suites and enforce the publish gate."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from .core import (
    AgentManifest,
    EvalCase,
    EvalCaseResult,
    EvalReport,
    EvalSuiteSpec,
    Invocation,
    InvocationResult,
)

AgentCall = Callable[[Invocation], Awaitable[InvocationResult]]


class EvalGateFailed(Exception):
    """The manifest's eval suite is missing, mismatched, or below threshold."""


class EvalRunner:
    """Score an agent against an eval suite. No model judge, no retries."""

    def __init__(self, call: AgentCall) -> None:
        self.call = call

    async def run(self, suite: EvalSuiteSpec, invocation: Invocation) -> EvalReport:
        results = [await self._run_case(case, invocation) for case in suite.cases]
        return EvalReport(
            suite_id=suite.suite_id,
            version=suite.version,
            passed=sum(1 for result in results if result.passed),
            total=len(results),
            results=results,
        )

    async def _run_case(self, case: EvalCase, parent: Invocation) -> EvalCaseResult:
        child = parent.model_copy(update={"run_id": uuid.uuid4().hex, "input": case.input})
        try:
            result = await self.call(child)
        except Exception as exc:  # noqa: BLE001
            return EvalCaseResult(case_id=case.id, passed=False, error=type(exc).__name__)

        return EvalCaseResult(
            case_id=case.id,
            passed=_matches(case, result.text),
            actual=result.text,
        )


def _matches(case: EvalCase, actual: str) -> bool:
    expected = case.expected.strip()
    if case.match == "exact":
        return actual.strip() == expected
    return expected in actual


def enforce_eval_gate(manifest: AgentManifest, report: EvalReport | None) -> None:
    """Reject publishing when the declared eval suite is missing or not met."""
    suite = manifest.eval_suite
    if suite is None:
        return
    if report is None:
        raise EvalGateFailed("manifest requires an eval report")
    if report.suite_id != suite.suite_id or report.version != suite.version:
        raise EvalGateFailed(
            f"eval report {report.suite_id}@{report.version} does not match "
            f"{suite.suite_id}@{suite.version}"
        )
    if report.score < suite.pass_threshold:
        raise EvalGateFailed(
            f"eval score {report.score:.3f} is below threshold {suite.pass_threshold}"
        )


__all__ = ["EvalGateFailed", "EvalRunner", "enforce_eval_gate"]
