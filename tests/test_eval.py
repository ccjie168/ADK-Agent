"""SLICE-030: deterministic agent evaluation and the publish gate."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from adk_agent.core import (
    AgentManifest,
    AgentRef,
    EvalCase,
    EvalReport,
    EvalSuite,
    EvalSuiteSpec,
    Invocation,
    InvocationResult,
    Principal,
)
from adk_agent.eval import EvalGateFailed, EvalRunner, enforce_eval_gate


class FakeCall:
    def __init__(self, responses: dict[str, str] | None = None, error: Exception | None = None):
        self.responses = responses or {}
        self.error = error
        self.inputs: list[str] = []

    async def __call__(self, invocation: Invocation) -> InvocationResult:
        self.inputs.append(invocation.input)
        if self.error is not None:
            raise self.error
        return InvocationResult(
            run_id=invocation.run_id,
            trace_id=invocation.trace_id,
            agent_ref=invocation.agent_ref,
            text=self.responses.get(invocation.input, "something else"),
        )


def _invocation() -> Invocation:
    return Invocation(
        run_id="r1",
        trace_id="tr1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="support-bot", version="1.0.0", digest="d" * 64),
        input="ignored",
    )


def _suite(*cases: EvalCase) -> EvalSuiteSpec:
    return EvalSuiteSpec(
        suite_id="smoke",
        version="1",
        agent="support-bot",
        cases=list(cases) or [EvalCase(id="c1", input="hi", expected="hello")],
    )


def _manifest(suite: EvalSuite | None = None) -> AgentManifest:
    return AgentManifest(
        id="support-bot",
        version="1.0.0",
        tenant="team-a",
        owner="team-a",
        model_policy={"provider_allowlist": ["litellm"]},
        eval_suite=suite,
    )


def test_runner_passes_matching_cases():
    call = FakeCall({"hi": "hello there", "bye": "goodbye"})
    suite = _suite(
        EvalCase(id="c1", input="hi", expected="hello"),
        EvalCase(id="c2", input="bye", expected="bye"),
    )

    report = asyncio.run(EvalRunner(call).run(suite, _invocation()))

    assert report.passed == 2
    assert report.total == 2
    assert report.score == 1.0
    assert call.inputs == ["hi", "bye"]
    assert [result.case_id for result in report.results] == ["c1", "c2"]


def test_runner_distinguishes_match_modes():
    call = FakeCall({"q": "ok!"})
    exact = EvalCase(id="c1", input="q", expected="ok", match="exact")
    contains = EvalCase(id="c2", input="q", expected="ok", match="contains")

    exact_report = asyncio.run(EvalRunner(call).run(_suite(exact), _invocation()))
    contains_report = asyncio.run(EvalRunner(call).run(_suite(contains), _invocation()))

    assert exact_report.passed == 0
    assert contains_report.passed == 1


def test_runner_marks_errors():
    call = FakeCall(error=RuntimeError("boom"))
    report = asyncio.run(EvalRunner(call).run(_suite(), _invocation()))

    assert report.passed == 0
    [result] = report.results
    assert result.passed is False
    assert result.error == "RuntimeError"
    assert result.actual == ""


def test_report_rejects_impossible_counts():
    with pytest.raises(ValidationError):
        EvalReport(suite_id="s", version="1", passed=2, total=1)
    with pytest.raises(ValidationError):
        EvalReport(suite_id="s", version="1", passed=0, total=0)


def test_suite_requires_cases():
    with pytest.raises(ValidationError):
        EvalSuiteSpec(suite_id="s", version="1", agent="a", cases=[])
    with pytest.raises(ValidationError):
        EvalCase(id="c", input="q", expected="a", match="fuzzy")


def test_gate_allows_passing_report():
    manifest = _manifest(EvalSuite(suite_id="smoke", version="1", pass_threshold=0.8))
    report = EvalReport(suite_id="smoke", version="1", passed=4, total=5)

    enforce_eval_gate(manifest, report)


def test_gate_rejects_suite_mismatch():
    manifest = _manifest(EvalSuite(suite_id="smoke", version="1", pass_threshold=0.5))
    wrong_id = EvalReport(suite_id="other", version="1", passed=1, total=1)
    wrong_version = EvalReport(suite_id="smoke", version="2", passed=1, total=1)

    with pytest.raises(EvalGateFailed):
        enforce_eval_gate(manifest, wrong_id)
    with pytest.raises(EvalGateFailed):
        enforce_eval_gate(manifest, wrong_version)


def test_gate_rejects_missing_report_and_low_score():
    manifest = _manifest(EvalSuite(suite_id="smoke", version="1", pass_threshold=0.9))
    with pytest.raises(EvalGateFailed):
        enforce_eval_gate(manifest, None)

    failed = EvalReport(suite_id="smoke", version="1", passed=1, total=2)
    with pytest.raises(EvalGateFailed):
        enforce_eval_gate(manifest, failed)


def test_gate_is_open_without_suite():
    enforce_eval_gate(_manifest(), None)
