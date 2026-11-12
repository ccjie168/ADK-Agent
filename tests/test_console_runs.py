"""SLICE-038: the console summarizes recent runs by run_id."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adk_agent.console import _summarize_runs
from adk_agent.core import AgentRef, AuditEvent, Principal

UTC = timezone.utc
_START = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)


def _event(
    run_id: str,
    *,
    at: datetime,
    action: str = "model.call",
    status: str = "ok",
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    agent_id: str = "probe",
) -> AuditEvent:
    return AuditEvent(
        event_id=f"{run_id}-{at.isoformat()}-{action}-{latency_ms}",
        run_id=run_id,
        trace_id=f"trace-{run_id}",
        tenant="local",
        principal=Principal(tenant="local", subject="console_user", kind="human"),
        agent_ref=AgentRef(id=agent_id, version="dev", digest="d" * 64),
        action=action,
        target=agent_id,
        status=status,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        timestamp=at,
    )


def test_runs_group_by_run_id():
    events = [
        _event("r1", at=_START, latency_ms=40),
        _event("r2", at=_START + timedelta(seconds=5), status="error", agent_id="other"),
        _event("r1", at=_START + timedelta(seconds=1), latency_ms=120, cost_usd=0.002),
    ]

    summaries = _summarize_runs(events, 50)

    assert [item["run_id"] for item in summaries] == ["r2", "r1"]
    run = summaries[1]
    assert run["trace_id"] == "trace-r1"
    assert run["agent_id"] == "probe"
    assert run["tenant"] == "local"
    assert run["status"] == "ok"
    assert run["started_at"] == _START.isoformat()
    assert run["last_at"] == (_START + timedelta(seconds=1)).isoformat()
    assert run["events"] == 2
    assert run["latency_ms"] == 120
    assert run["cost_usd"] == 0.002


def test_runs_limit_is_clamped():
    events = [_event(f"r{index}", at=_START + timedelta(seconds=index)) for index in range(3)]

    assert len(_summarize_runs(events, 0)) == 1
    assert len(_summarize_runs(events, 999)) == 3
    assert _summarize_runs([], 50) == []


def test_runs_ignore_missing_optional_values():
    first = _event("r1", at=_START, latency_ms=100, cost_usd=0.5)
    last = _event("r1", at=_START + timedelta(seconds=1))

    [with_values] = _summarize_runs([first, last], 50)
    assert with_values["latency_ms"] == 100
    assert with_values["cost_usd"] == 0.5

    [without_values] = _summarize_runs([_event("r2", at=_START)], 50)
    assert without_values["latency_ms"] is None
    assert without_values["cost_usd"] is None
