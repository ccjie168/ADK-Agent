"""SLICE-175: risk_level drives idempotency, L3/L4 force it (ADR-0034 slice 4)."""

from __future__ import annotations

from adk_agent.tools import ToolSpec
from adk_agent.tools.catalog import ToolEntry


def _spec(**overrides) -> ToolSpec:
    return ToolSpec(tool_id="write", handler=lambda **kwargs: None, **overrides)


def test_l4_write_forces_idempotency_even_with_opt_out():
    spec = _spec(write=True, risk_level="L4", idempotency_required=False)
    assert spec.requires_idempotency is True


def test_l3_write_forces_idempotency():
    assert _spec(write=True, risk_level="L3").requires_idempotency is True


def test_l2_write_defaults_to_idempotent():
    assert _spec(write=True, risk_level="L2").requires_idempotency is True


def test_l2_write_can_opt_out():
    spec = _spec(write=True, risk_level="L2", idempotency_required=False)
    assert spec.requires_idempotency is False


def test_read_tool_does_not_require_idempotency():
    assert _spec(write=False).requires_idempotency is False


def test_idempotency_required_defaults_none():
    assert _spec().idempotency_required is None
    entry = ToolEntry(tool_id="write", source="function")
    assert entry.idempotency_required is None
