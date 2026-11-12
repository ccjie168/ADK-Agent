"""SLICE-038: eval reports persist beside their published version."""

from __future__ import annotations

import asyncio

import pytest

from adk_agent.core import EvalCaseResult, EvalReport
from adk_agent.registry.reports import EvalReportConflict, FileEvalReportStore

_TENANT = "team-a"
_AGENT = "support-bot"
_VERSION = "1.0.0"


def _report(*, passed: int = 2, actual: str = "ok") -> EvalReport:
    return EvalReport(
        suite_id="smoke",
        version="1",
        passed=passed,
        total=2,
        results=[EvalCaseResult(case_id="a", passed=passed == 2, actual=actual)],
    )


def test_put_then_get_report(tmp_path):
    store = FileEvalReportStore(tmp_path)
    report = _report()

    stored = asyncio.run(store.put(_TENANT, _AGENT, _VERSION, report))

    assert stored == report
    assert asyncio.run(store.has(_TENANT, _AGENT, _VERSION)) is True
    assert asyncio.run(store.get(_TENANT, _AGENT, _VERSION)) == report
    assert (tmp_path / _TENANT / _AGENT / f"{_VERSION}.eval.json").is_file()


def test_put_same_report_is_idempotent(tmp_path):
    store = FileEvalReportStore(tmp_path)
    report = _report()

    first = asyncio.run(store.put(_TENANT, _AGENT, _VERSION, report))
    second = asyncio.run(store.put(_TENANT, _AGENT, _VERSION, report))

    assert first == second
    assert len(list((tmp_path / _TENANT / _AGENT).glob("*.eval.json"))) == 1


def test_put_different_report_conflicts(tmp_path):
    store = FileEvalReportStore(tmp_path)
    asyncio.run(store.put(_TENANT, _AGENT, _VERSION, _report(passed=2)))

    with pytest.raises(EvalReportConflict):
        asyncio.run(store.put(_TENANT, _AGENT, _VERSION, _report(passed=1)))


@pytest.mark.parametrize(
    ("tenant", "agent_id", "version"),
    [
        ("../x", _AGENT, _VERSION),
        (_TENANT, "../x", _VERSION),
        (_TENANT, _AGENT, "../x"),
    ],
)
def test_report_paths_reject_unsafe_components(tmp_path, tenant, agent_id, version):
    store = FileEvalReportStore(tmp_path)

    with pytest.raises(ValueError):
        asyncio.run(store.put(tenant, agent_id, version, _report()))
    with pytest.raises(ValueError):
        asyncio.run(store.get(tenant, agent_id, version))
    with pytest.raises(ValueError):
        asyncio.run(store.has(tenant, agent_id, version))
