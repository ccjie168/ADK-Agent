"""SLICE-171: write / idempotency_required fields on ToolSpec and ToolEntry."""

from __future__ import annotations

from adk_agent.tools import ToolSpec
from adk_agent.tools.catalog import ToolEntry


def _spec(**overrides) -> ToolSpec:
    return ToolSpec(tool_id="write", handler=lambda **kwargs: None, **overrides)


def test_tool_spec_write_fields_default_false():
    spec = _spec()
    assert spec.write is False
    assert spec.idempotency_required is None


def test_tool_spec_write_requires_idempotency():
    assert _spec(write=True).requires_idempotency is True


def test_tool_spec_explicit_idempotency_required():
    assert _spec(idempotency_required=True).requires_idempotency is True


def test_tool_entry_write_fields():
    entry = ToolEntry(
        tool_id="write",
        source="function",
        write=True,
        idempotency_required=True,
    )
    assert entry.write is True
    assert entry.idempotency_required is True


def test_tool_entry_write_requires_idempotency():
    entry = ToolEntry(tool_id="write", source="function", write=True)
    assert entry.requires_idempotency is True
