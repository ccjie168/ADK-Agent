"""SLICE-169: PlanStep.needs_approval and AuditEvent.risk_level."""

from __future__ import annotations

from datetime import datetime, timezone

from adk_agent.core import AgentRef, AuditEvent, PlanStep, Principal


def _step(**overrides) -> PlanStep:
    return PlanStep(id="a", agent_ref=AgentRef(id="bot", version="1", digest="d" * 64), **overrides)


def _event(**overrides) -> AuditEvent:
    return AuditEvent(
        event_id="e1",
        run_id="r1",
        trace_id="tr1",
        tenant="t1",
        principal=Principal(tenant="t1", subject="alice", kind="human"),
        agent_ref=AgentRef(id="bot", version="1", digest="d" * 64),
        action="orchestration.step",
        target="a",
        status="ok",
        timestamp=datetime.now(timezone.utc),
        **overrides,
    )


def test_step_needs_approval_for_l3_risk():
    assert _step(risk_level="L3").needs_approval is True


def test_step_needs_approval_for_l4_risk():
    assert _step(risk_level="L4").needs_approval is True


def test_step_no_approval_for_l2_risk():
    assert _step(risk_level="L2").needs_approval is False


def test_step_approval_flag_still_wins():
    assert _step(requires_approval=True).needs_approval is True


def test_audit_event_carries_risk_level():
    assert _event(risk_level="L3").risk_level == "L3"
