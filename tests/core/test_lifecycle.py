"""SLICE-076: lifecycle transitions follow ADR-0010."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adk_agent.core import AgentLifecycle, LifecycleTransitionError, transition_lifecycle

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def _lifecycle(status: str) -> AgentLifecycle:
    return AgentLifecycle(
        status=status,
        changed_at=NOW if status != "published" else None,
        changed_by="ops" if status != "published" else None,
        reason="seed" if status != "published" else "",
    )


def test_default_is_published():
    assert AgentLifecycle.default() == AgentLifecycle(
        status="published", changed_at=None, changed_by=None, reason=""
    )


def test_transition_matrix():
    for current, target in (
        ("published", "deprecated"),
        ("published", "retired"),
        ("deprecated", "published"),
        ("deprecated", "retired"),
    ):
        record = transition_lifecycle(
            _lifecycle(current), target, changed_by="alice", reason="test", now=NOW
        )
        assert record.status == target
        assert record.changed_by == "alice"
        assert record.changed_at == NOW


def test_retired_is_terminal():
    for target in ("published", "deprecated"):
        with pytest.raises(LifecycleTransitionError):
            transition_lifecycle(_lifecycle("retired"), target, changed_by="alice")


def test_idempotent_set():
    current = _lifecycle("deprecated")

    record = transition_lifecycle(current, "deprecated", changed_by="alice")

    assert record is current
